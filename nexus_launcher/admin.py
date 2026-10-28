from __future__ import annotations

import ctypes
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import keyring
import qrcode
from nexus_launcher.build_management import BuildManager, BuildMetadata
from PIL import ImageTk
from nexus_launcher.projects import Project, ProjectCatalog, ServerProfile
from nexus_launcher.security import (
    PERMISSIONS,
    AuthenticationError,
    AuthorizationService,
    PermissionDeniedError,
    Session,
    SQLiteSecurityStore,
)
from nexus_launcher.server_controller import LocalServerController, PterodactylServerController, ServerController
from nexus_launcher.server_status import ping

APP_DIR = Path(os.getenv("APPDATA", Path.home())) / ".nexus-launcher"
PROJECTS_FILE = APP_DIR / "projects.json"
PANEL_CONFIG_FILE = APP_DIR / "control-panel.json"
SECURITY_DB_FILE = APP_DIR / "security.db"
WINDOWS_APP_ID = "com.nexus.controlpanel"


def resource(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / name


def apply_window_icon(window) -> None:
    """Apply packaged icons when present; a missing cosmetic asset must never abort startup."""
    ico = resource("control-panel.ico")
    png = resource("control-panel.png")
    try:
        if ico.is_file():
            window.iconbitmap(default=str(ico))
    except tk.TclError:
        pass
    try:
        if png.is_file():
            window._window_icon = tk.PhotoImage(file=str(png))
            window.iconphoto(True, window._window_icon)
    except tk.TclError:
        pass


def format_uptime(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class PasswordStrengthIndicator:
    COLORS = ("#f87171", "#fb923c", "#fbbf24", "#22d3ee", "#4ade80")

    def __init__(self, parent, entry, security, username_getter=lambda: ""):
        self.entry = entry
        self.security = security
        self.username_getter = username_getter
        self.canvas = tk.Canvas(parent, height=5, bg="#101a2b", highlightthickness=0)
        self.canvas.pack(fill="x", pady=(0, 6))
        self.text = tk.StringVar(value="Введите уникальную парольную фразу")
        self.label = tk.Label(parent, textvariable=self.text, bg="#0d1524", fg="#64748b", anchor="w", wraplength=380)
        self.label.pack(fill="x", pady=(0, 12))
        entry.bind("<KeyRelease>", self.update, add="+")

    def update(self, _event=None):
        assessment = self.security.assess_password(self.entry.get(), self.username_getter())
        color = self.COLORS[assessment.score]
        self.canvas.delete("all")
        self.canvas.update_idletasks()
        width = self.canvas.winfo_width() * (assessment.score + 1) / 5
        self.canvas.create_rectangle(0, 0, width, 5, fill=color, outline="")
        reason = assessment.reasons[0] if assessment.reasons else "Пароль соответствует политике безопасности."
        self.text.set(f"{assessment.level} — {reason}")
        self.label.configure(fg=color)


class ServerDialog(tk.Toplevel):
    def __init__(self, parent, server: ServerProfile | None = None):
        super().__init__(parent)
        self.title("Настройки сервера")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        server = server or ServerProfile("", "", "")
        initial = {key: str(value) for key, value in vars(server).items()}
        self.values = {key: tk.StringVar(value=value) for key, value in initial.items()}
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        fields = (
            ("id", "ID (латиница)"),
            ("name", "Название"),
            ("address", "Адрес сервера"),
            ("minecraft_version", "Minecraft"),
            ("loader", "Загрузчик"),
            ("loader_version", "Версия загрузчика"),
            ("manifest_url", "Манифест обновлений"),
            ("news_url", "Новости"),
            ("working_directory", "Рабочая папка"),
            ("java_path", "Java executable"),
            ("server_jar", "Server JAR"),
            ("min_memory_mb", "Minimum RAM (MB)"),
            ("max_memory_mb", "Maximum RAM (MB)"),
            ("additional_arguments", "Дополнительные JVM аргументы"),
            ("management_type", "Управление"),
            ("panel_url", "URL хостинг-панели"),
            ("panel_server_id", "ID сервера в панели"),
            ("credential_key", "Ключ учётных данных"),
        )
        for row, (key, label) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            if key == "loader":
                widget = ttk.Combobox(
                    frame, textvariable=self.values[key], state="readonly", values=("vanilla", "neoforge", "fabric")
                )
            elif key == "management_type":
                widget = ttk.Combobox(
                    frame, textvariable=self.values[key], state="readonly", values=("local", "pterodactyl")
                )
            else:
                widget = ttk.Entry(frame, textvariable=self.values[key], width=54)
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            if key == "working_directory":
                ttk.Button(frame, text="Выбрать папку", command=self._choose_directory).grid(
                    row=row, column=2, padx=(8, 0)
                )
            elif key == "java_path":
                ttk.Button(frame, text="Выбрать", command=self._choose_java).grid(row=row, column=2, padx=(8, 0))
            elif key == "server_jar":
                ttk.Button(frame, text="Выбрать", command=self._choose_jar).grid(row=row, column=2, padx=(8, 0))
        ttk.Label(frame, text="Client API key (хранится в Windows Credential Manager)").grid(
            row=len(fields), column=0, sticky="w", pady=4
        )
        self.api_token = ttk.Entry(frame, width=54, show="•")
        self.api_token.grid(row=len(fields), column=1, sticky="ew", pady=4)
        buttons = ttk.Frame(frame)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=5)
        ttk.Button(buttons, text="Сохранить", style="Accent.TButton", command=self._save).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _choose_directory(self):
        selected = filedialog.askdirectory(parent=self, initialdir=self.values["working_directory"].get() or None)
        if selected:
            self.values["working_directory"].set(selected)

    def _choose_java(self):
        selected = filedialog.askopenfilename(parent=self, filetypes=(("Java", "java.exe"), ("Executable", "*.exe")))
        if selected:
            self.values["java_path"].set(selected)

    def _choose_jar(self):
        initial = self.values["working_directory"].get() or None
        selected = filedialog.askopenfilename(parent=self, initialdir=initial, filetypes=(("Java archive", "*.jar"),))
        if selected:
            directory = Path(self.values["working_directory"].get()) if self.values["working_directory"].get() else None
            path = Path(selected)
            self.values["server_jar"].set(path.name if directory and path.parent == directory else str(path))

    def _save(self):
        data = {key: value.get().strip() for key, value in self.values.items()}
        if not data["id"] or not data["name"] or not data["address"]:
            messagebox.showerror("NEXUS Control Panel", "ID, название и адрес обязательны", parent=self)
            return
        if data["loader"] not in {"vanilla", "neoforge", "fabric"}:
            messagebox.showerror("NEXUS Control Panel", "Выберите загрузчик", parent=self)
            return
        try:
            data["min_memory_mb"] = int(data["min_memory_mb"])
            data["max_memory_mb"] = int(data["max_memory_mb"])
            if data["min_memory_mb"] < 256 or data["max_memory_mb"] < data["min_memory_mb"]:
                raise ValueError
        except ValueError:
            messagebox.showerror("NEXUS Control Panel", "Проверьте значения Minimum/Maximum RAM", parent=self)
            return
        if data["management_type"] == "pterodactyl":
            if not data["panel_url"].startswith("https://") or not data["panel_server_id"]:
                messagebox.showerror(
                    "NEXUS Control Panel", "Для удалённого сервера нужны HTTPS URL и ID сервера", parent=self
                )
                return
            data["credential_key"] = data["credential_key"] or f"server/{data['id']}"
            token = self.api_token.get().strip()
            if token:
                keyring.set_password(PterodactylServerController.KEYRING_SERVICE, data["credential_key"], token)
        self.result = ServerProfile(**data)
        self.destroy()


class AccessWindow(tk.Tk):
    def __init__(self, security: SQLiteSecurityStore):
        super().__init__()
        self.security = security
        self.session = None
        self.title("NEXUS Control Panel — Вход")
        self.geometry("520x760")
        self.resizable(False, False)
        self.configure(bg="#070c15")
        apply_window_icon(self)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build_setup() if not security.has_users() else self._build_login()

    def _clear(self):
        for child in self.winfo_children():
            child.destroy()

    def _header(self, subtitle):
        tk.Label(self, text="NEXUS", bg="#070c15", fg="#f8fafc", font=("Segoe UI Semibold", 26)).pack(pady=(42, 2))
        tk.Label(self, text="CONTROL PANEL", bg="#070c15", fg="#22d3ee", font=("Segoe UI Semibold", 10)).pack()
        tk.Label(self, text=subtitle, bg="#070c15", fg="#64748b", font=("Segoe UI", 10)).pack(pady=(10, 26))

    @staticmethod
    def _entry(parent, label, show=None):
        tk.Label(parent, text=label, bg="#0d1524", fg="#94a3b8", anchor="w", font=("Segoe UI", 9)).pack(fill="x")
        entry = tk.Entry(
            parent,
            bg="#09111e",
            fg="#f8fafc",
            insertbackground="white",
            relief="flat",
            font=("Segoe UI", 11),
            show=show,
        )
        entry.pack(fill="x", ipady=9, pady=(5, 14))
        return entry

    def _card(self):
        card = tk.Frame(self, bg="#0d1524", highlightbackground="#1d2a3b", highlightthickness=1)
        card.pack(fill="x", padx=58)
        body = tk.Frame(card, bg="#0d1524")
        body.pack(fill="both", padx=24, pady=22)
        return body

    def _build_setup(self):
        self._clear()
        self._header("Обновление безопасности — создайте владельца панели")
        body = self._card()
        self.setup_username = self._entry(body, "Имя пользователя")
        self.setup_display = self._entry(body, "Отображаемое имя")
        self.setup_password = self._entry(body, "Пароль — минимум 12 символов", "•")
        PasswordStrengthIndicator(body, self.setup_password, self.security, self.setup_username.get)
        self.setup_repeat = self._entry(body, "Повторите пароль", "•")
        self._show_password_toggle(body, (self.setup_password, self.setup_repeat))
        tk.Button(
            body,
            text="Создать Owner",
            command=self._create_owner,
            bg="#147ca8",
            activebackground="#2563eb",
            fg="white",
            relief="flat",
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        ).pack(fill="x", ipady=10, pady=(4, 0))

    def _create_owner(self):
        username = self.setup_username.get().strip()
        display = self.setup_display.get().strip()
        password = self.setup_password.get()
        if not username or not display:
            messagebox.showerror("NEXUS", "Заполните имя пользователя и отображаемое имя", parent=self)
            return
        if password != self.setup_repeat.get():
            messagebox.showerror("NEXUS", "Пароли не совпадают", parent=self)
            return
        try:
            self.security.create_owner(username, display, password)
            messagebox.showinfo("NEXUS", "Owner создан. Теперь выполните вход.", parent=self)
            self._build_login()
        except (ValueError, PermissionDeniedError, sqlite3.IntegrityError) as error:
            messagebox.showerror("NEXUS", str(error), parent=self)

    def _build_login(self):
        self._clear()
        self._header("Вход в управление инфраструктурой")
        body = self._card()
        self.login_username = self._entry(body, "Имя пользователя")
        self.login_password = self._entry(body, "Пароль", "•")
        self._show_password_toggle(body, (self.login_password,))
        self.login_password.bind("<Return>", lambda _event: self._login())
        self.login_status = tk.StringVar(value="")
        tk.Label(body, textvariable=self.login_status, bg="#0d1524", fg="#f87171", font=("Segoe UI", 9)).pack(
            anchor="w", pady=(0, 8)
        )
        tk.Button(
            body,
            text="Войти",
            command=self._login,
            bg="#147ca8",
            activebackground="#2563eb",
            fg="white",
            relief="flat",
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        ).pack(fill="x", ipady=10)
        self.login_username.focus_set()

    @staticmethod
    def _show_password_toggle(parent, entries):
        visible = tk.BooleanVar(value=False)

        def toggle():
            for entry in entries:
                entry.configure(show="" if visible.get() else "•")

        tk.Checkbutton(
            parent,
            text="Показать пароль",
            variable=visible,
            command=toggle,
            bg="#0d1524",
            fg="#94a3b8",
            selectcolor="#101a2b",
            activebackground="#0d1524",
            activeforeground="white",
        ).pack(anchor="e", pady=(0, 10))

    def _login(self):
        try:
            pending = self.security.authenticate_password(self.login_username.get(), self.login_password.get())
            self.login_password.delete(0, "end")
            if pending.must_change_password:
                change = TemporaryPasswordDialog(self, self.security, pending)
                if not change.pending:
                    return
                pending = change.pending
            if pending.mfa_enabled:
                challenge = MfaChallengeDialog(self, self.security, pending)
                self.session = challenge.session
            elif pending.mfa_required:
                setup = MfaSetupDialog(self, self.security, pending)
                self.session = setup.session
            else:
                self.session = self.security.complete_password_login(pending)
            if not self.session:
                return
            self.destroy()
        except AuthenticationError as error:
            self.login_status.set("Неверные данные для входа." if not error.retry_after else str(error))
            self.login_password.delete(0, "end")


class PasswordChangeDialog(tk.Toplevel):
    def __init__(self, parent, security, session, require_change=False):
        super().__init__(parent)
        self.security = security
        self.current_session = session
        self.session = None
        self.title("Смена пароля")
        self.transient(parent)
        self.grab_set()
        self.configure(bg="#0d1524")
        self.resizable(False, False)
        body = tk.Frame(self, bg="#0d1524")
        body.pack(padx=24, pady=22)
        if require_change:
            tk.Label(
                body,
                text="Необходимо заменить временный пароль",
                bg="#0d1524",
                fg="#fbbf24",
                font=("Segoe UI Semibold", 10),
            ).pack(anchor="w", pady=(0, 12))
        self.old = AccessWindow._entry(body, "Текущий пароль", "•")
        self.new = AccessWindow._entry(body, "Новый пароль — минимум 12 символов", "•")
        PasswordStrengthIndicator(body, self.new, self.security, lambda: session.username)
        self.repeat = AccessWindow._entry(body, "Повторите новый пароль", "•")
        tk.Button(body, text="Сохранить", command=self._save, bg="#147ca8", fg="white", relief="flat").pack(
            fill="x", ipady=9
        )
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _save(self):
        if self.new.get() != self.repeat.get():
            messagebox.showerror("NEXUS", "Новые пароли не совпадают", parent=self)
            return
        try:
            self.session = self.security.change_password(self.current_session, self.old.get(), self.new.get())
            self.destroy()
        except (ValueError, AuthenticationError) as error:
            messagebox.showerror("NEXUS", str(error), parent=self)


class TemporaryPasswordDialog(tk.Toplevel):
    def __init__(self, parent, security, pending):
        super().__init__(parent)
        self.security = security
        self.current_pending = pending
        self.pending = None
        self.title("Установите постоянный пароль")
        self.configure(bg="#0d1524")
        self.transient(parent)
        self.grab_set()
        body = tk.Frame(self, bg="#0d1524")
        body.pack(padx=24, pady=22)
        tk.Label(
            body,
            text="Перед продолжением замените временный пароль",
            bg="#0d1524",
            fg="#fbbf24",
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w", pady=(0, 14))
        self.new = AccessWindow._entry(body, "Новый пароль — минимум 12 символов", "•")
        PasswordStrengthIndicator(body, self.new, security, lambda: pending.username)
        self.repeat = AccessWindow._entry(body, "Повторите новый пароль", "•")
        AccessWindow._show_password_toggle(body, (self.new, self.repeat))
        ttk.Button(body, text="Сохранить пароль", style="Accent.TButton", command=self._save).pack(fill="x")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _save(self):
        if self.new.get() != self.repeat.get():
            messagebox.showerror("NEXUS", "Пароли не совпадают", parent=self)
            return
        try:
            self.pending = self.security.change_temporary_password(self.current_pending, self.new.get())
            self.destroy()
        except ValueError as error:
            messagebox.showerror("NEXUS", str(error), parent=self)


class RecoveryCodesDialog(tk.Toplevel):
    def __init__(self, parent, codes):
        super().__init__(parent)
        self.codes = codes
        self.title("Сохраните резервные коды")
        self.configure(bg="#0d1524")
        self.transient(parent)
        self.grab_set()
        body = tk.Frame(self, bg="#0d1524")
        body.pack(padx=24, pady=22)
        tk.Label(
            body,
            text="Сохраните коды сейчас — повторно они показаны не будут.",
            bg="#0d1524",
            fg="#fbbf24",
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w", pady=(0, 12))
        text = tk.Text(body, width=36, height=11, bg="#09111e", fg="#f8fafc", font=("Cascadia Mono", 11), relief="flat")
        text.insert("1.0", "\n".join(codes))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Копировать", command=self._copy).pack(side="left")
        ttk.Button(buttons, text="Сохранить в файл", command=self._save_file).pack(side="left", padx=8)
        ttk.Button(buttons, text="Готово", style="Accent.TButton", command=self.destroy).pack(side="right")
        self.wait_window()

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.codes))
        self.update()
        messagebox.showinfo("NEXUS", "Коды скопированы. Очистите буфер обмена после сохранения.", parent=self)

    def _save_file(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", filetypes=(("Text", "*.txt"),))
        if path:
            Path(path).write_text("NEXUS Control Panel recovery codes\n\n" + "\n".join(self.codes), encoding="utf-8")


class MfaSetupDialog(tk.Toplevel):
    def __init__(self, parent, security, pending):
        super().__init__(parent)
        self.security = security
        self.pending = pending
        self.session = None
        self.title("Настройка двухфакторной аутентификации")
        self.configure(bg="#0d1524")
        self.transient(parent)
        self.grab_set()
        setup = security.begin_mfa_setup(pending)
        body = tk.Frame(self, bg="#0d1524")
        body.pack(padx=24, pady=20)
        tk.Label(
            body,
            text="Для вашей роли требуется двухфакторная аутентификация",
            bg="#0d1524",
            fg="#22d3ee",
            font=("Segoe UI Semibold", 11),
        ).pack(pady=(0, 10))
        qr_image = qrcode.make(setup.uri).resize((220, 220))
        self.qr_photo = ImageTk.PhotoImage(qr_image)
        tk.Label(body, image=self.qr_photo, bg="#0d1524").pack()
        formatted = " ".join(setup.secret[index : index + 4] for index in range(0, len(setup.secret), 4))
        tk.Label(body, text="Ключ для ручного ввода", bg="#0d1524", fg="#64748b").pack(pady=(12, 4))
        tk.Label(body, text=formatted, bg="#09111e", fg="#f8fafc", font=("Cascadia Mono", 10)).pack(ipadx=10, ipady=7)
        self.code = AccessWindow._entry(body, "Введите 6-значный код")
        ttk.Button(body, text="Подтвердить и включить 2FA", style="Accent.TButton", command=self._confirm).pack(
            fill="x"
        )
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _confirm(self):
        try:
            if isinstance(self.pending, Session):
                self.session, codes = self.security.confirm_mfa_setup_current(self.pending, self.code.get().strip())
            else:
                self.session, codes = self.security.confirm_mfa_setup(self.pending, self.code.get().strip())
            RecoveryCodesDialog(self, codes)
            self.destroy()
        except (ValueError, AuthenticationError) as error:
            messagebox.showerror("NEXUS", str(error), parent=self)


class MfaChallengeDialog(tk.Toplevel):
    def __init__(self, parent, security, pending):
        super().__init__(parent)
        self.security = security
        self.pending = pending
        self.session = None
        self.recovery_mode = False
        self.title("Подтверждение входа")
        self.configure(bg="#0d1524")
        self.transient(parent)
        self.grab_set()
        body = tk.Frame(self, bg="#0d1524")
        body.pack(padx=28, pady=26)
        tk.Label(body, text="Подтверждение входа", bg="#0d1524", fg="#f8fafc", font=("Segoe UI Semibold", 16)).pack()
        self.prompt = tk.StringVar(value="Введите код из приложения-аутентификатора.")
        tk.Label(body, textvariable=self.prompt, bg="#0d1524", fg="#94a3b8").pack(pady=(8, 18))
        self.code = tk.Entry(
            body,
            bg="#09111e",
            fg="#f8fafc",
            insertbackground="white",
            relief="flat",
            font=("Cascadia Mono", 16),
            justify="center",
        )
        self.code.pack(fill="x", ipady=10)
        self.code.bind("<Return>", lambda _event: self._confirm())
        ttk.Button(body, text="Подтвердить", style="Accent.TButton", command=self._confirm).pack(fill="x", pady=(14, 8))
        ttk.Button(body, text="Использовать резервный код", command=self._toggle_recovery).pack(fill="x")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _toggle_recovery(self):
        self.recovery_mode = not self.recovery_mode
        self.prompt.set(
            "Введите одноразовый резервный код." if self.recovery_mode else "Введите код из приложения-аутентификатора."
        )
        self.code.delete(0, "end")

    def _confirm(self):
        try:
            self.session = self.security.complete_mfa_login(
                self.pending, self.code.get().strip(), recovery=self.recovery_mode
            )
            self.destroy()
        except AuthenticationError as error:
            messagebox.showerror("NEXUS", str(error), parent=self)


class ReauthDialog(tk.Toplevel):
    def __init__(self, parent, security, session):
        super().__init__(parent)
        self.security = security
        self.current_session = session
        self.session = None
        self.title("Подтвердите действие")
        self.configure(bg="#0d1524")
        self.transient(parent)
        self.grab_set()
        body = tk.Frame(self, bg="#0d1524")
        body.pack(padx=24, pady=22)
        tk.Label(
            body,
            text="Для опасного действия подтвердите личность",
            bg="#0d1524",
            fg="#fbbf24",
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w", pady=(0, 12))
        self.password = AccessWindow._entry(body, "Пароль", "•")
        self.code = AccessWindow._entry(body, "Код 2FA" if session.mfa_verified else "Код 2FA — не требуется")
        if not session.mfa_verified:
            self.code.configure(state="disabled")
        ttk.Button(body, text="Подтвердить", style="Accent.TButton", command=self._confirm).pack(fill="x")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _confirm(self):
        try:
            self.session = self.security.reauthenticate(
                self.current_session, self.password.get(), self.code.get().strip()
            )
            self.password.delete(0, "end")
            self.destroy()
        except (AuthenticationError, ValueError) as error:
            self.password.delete(0, "end")
            messagebox.showerror("NEXUS", str(error), parent=self)


class SecuritySettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.panel = parent
        self.security = parent.security
        self.title("Безопасность аккаунта")
        self.geometry("620x640")
        self.configure(bg="#0d1524")
        self.transient(parent)
        body = tk.Frame(self, bg="#0d1524")
        body.pack(fill="both", expand=True, padx=28, pady=24)
        tk.Label(body, text="Безопасность аккаунта", bg="#0d1524", fg="#f8fafc", font=("Segoe UI Semibold", 18)).pack(
            anchor="w"
        )
        self.content = tk.Frame(body, bg="#0d1524")
        self.content.pack(fill="both", expand=True, pady=(18, 0))
        self._render()

    def _section(self, title, status):
        frame = tk.Frame(self.content, bg="#101a2b", highlightbackground="#1d2a3b", highlightthickness=1)
        frame.pack(fill="x", pady=7)
        inner = tk.Frame(frame, bg="#101a2b")
        inner.pack(fill="x", padx=16, pady=14)
        tk.Label(inner, text=title, bg="#101a2b", fg="#f8fafc", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        tk.Label(inner, text=status, bg="#101a2b", fg="#94a3b8").pack(anchor="w", pady=(4, 10))
        return inner

    def _render(self):
        for child in self.content.winfo_children():
            child.destroy()
        status = self.security.mfa_status(self.panel.session.user_id)
        password = self._section("Пароль", "Защищён Argon2id • политика 12+ символов")
        ttk.Button(password, text="Изменить пароль", command=self.panel._change_password).pack(anchor="w")
        mfa_text = "● Включена • Authenticator App" if status["enabled"] else "○ Не настроена"
        mfa = self._section("Двухфакторная аутентификация", mfa_text)
        if status["enabled"]:
            ttk.Button(mfa, text="Отключить 2FA", command=self._disable_mfa).pack(anchor="w")
        else:
            ttk.Button(mfa, text="Настроить 2FA", style="Accent.TButton", command=self._setup_mfa).pack(anchor="w")
        recovery = self._section("Резервные коды", f"Доступно: {status['recovery_codes']}")
        if status["enabled"]:
            ttk.Button(recovery, text="Создать новые", command=self._regenerate).pack(anchor="w")
        sessions = [item for item in self.security.list_sessions(self.panel.session.user_id) if not item["revoked_at"]]
        session_frame = self._section("Активные сессии", f"Активно: {len(sessions)}")
        ttk.Button(session_frame, text="Завершить другие сессии", command=self._revoke_sessions).pack(anchor="w")

    def _reauth(self):
        if AuthorizationService.has_fresh_reauthentication(self.panel.session):
            return True
        dialog = ReauthDialog(self, self.security, self.panel.session)
        if dialog.session:
            self.panel.session = dialog.session
            return True
        return False

    def _setup_mfa(self):
        setup = MfaSetupDialog(self, self.security, self.panel.session)
        if setup.session:
            self.panel.session = setup.session
            self._render()

    def _regenerate(self):
        if not self._reauth():
            return
        try:
            codes = self.security.regenerate_recovery_codes(self.panel.session)
            RecoveryCodesDialog(self, codes)
            self._render()
        except PermissionDeniedError as error:
            messagebox.showerror("NEXUS", str(error), parent=self)

    def _disable_mfa(self):
        if not self._reauth():
            return
        if not messagebox.askyesno("NEXUS", "Отключить двухфакторную аутентификацию?", parent=self):
            return
        try:
            self.security.disable_mfa(self.panel.session)
            messagebox.showinfo("NEXUS", "2FA отключена. Требуется повторный вход.", parent=self)
            self.destroy()
            self.panel._logout()
        except PermissionDeniedError as error:
            messagebox.showerror("NEXUS", str(error), parent=self)

    def _revoke_sessions(self):
        self.security.revoke_other_sessions(self.panel.session)
        self._render()


class ManagementDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.panel = parent
        self.security = parent.security
        self.session = parent.session
        self.title("NEXUS — Пользователи, роли и аудит")
        self.geometry("980x650")
        self.minsize(820, 520)
        self.configure(bg="#070c15")
        self.transient(parent)
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=18, pady=18)
        if AuthorizationService.can(self.session, "users.view"):
            self.users_tab = ttk.Frame(tabs, style="Card.TFrame", padding=14)
            tabs.add(self.users_tab, text="Пользователи")
            self._build_users()
        if AuthorizationService.can(self.session, "roles.view"):
            self.roles_tab = ttk.Frame(tabs, style="Card.TFrame", padding=14)
            tabs.add(self.roles_tab, text="Роли")
            self._build_roles()
        if AuthorizationService.can(self.session, "audit.view"):
            self.audit_tab = ttk.Frame(tabs, style="Card.TFrame", padding=14)
            tabs.add(self.audit_tab, text="Журнал действий")
            self._build_audit()

    def _build_users(self):
        columns = ("username", "display", "role", "status", "mfa", "last")
        self.users_tree = ttk.Treeview(self.users_tab, columns=columns, show="headings", selectmode="browse")
        for key, title, width in zip(
            columns,
            ("Имя", "Отображаемое имя", "Роль", "Статус", "2FA", "Последний вход"),
            (120, 170, 150, 130, 70, 180),
            strict=True,
        ):
            self.users_tree.heading(key, text=title)
            self.users_tree.column(key, width=width, anchor="w")
        self.users_tree.pack(fill="both", expand=True)
        actions = ttk.Frame(self.users_tab, style="Card.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        if AuthorizationService.can(self.session, "users.create"):
            ttk.Button(actions, text="＋ Создать пользователя", style="Accent.TButton", command=self._create_user).pack(
                side="left"
            )
        if AuthorizationService.can(self.session, "users.edit"):
            ttk.Button(actions, text="Роль и доступ", command=self._edit_user_access).pack(side="left", padx=8)
        if AuthorizationService.can(self.session, "users.disable"):
            ttk.Button(actions, text="Включить / отключить", command=self._toggle_user).pack(side="left")
        if AuthorizationService.can(self.session, "users.security.reset_mfa"):
            ttk.Button(actions, text="Сбросить 2FA", command=self._reset_user_mfa).pack(side="left", padx=8)
        self._refresh_users()

    def _refresh_users(self):
        self.users_tree.delete(*self.users_tree.get_children())
        for user in self.security.list_users():
            self.users_tree.insert(
                "",
                "end",
                iid=str(user["id"]),
                values=(
                    user["username"],
                    user["display_name"],
                    user["role_name"],
                    (
                        "Отключён"
                        if not user["is_active"]
                        else "Смена пароля"
                        if user["must_change_password"]
                        else "Настройка 2FA"
                        if user["role_id"] in {"owner", "administrator", "technical-admin"} and not user["mfa_enabled"]
                        else "Активен"
                    ),
                    "✓" if user["mfa_enabled"] else "—",
                    user["last_login_at"] or "—",
                ),
            )

    def _create_user(self):
        dialog = tk.Toplevel(self)
        dialog.title("Новый пользователь")
        dialog.configure(bg="#0d1524")
        dialog.transient(self)
        dialog.grab_set()
        body = tk.Frame(dialog, bg="#0d1524")
        body.pack(padx=22, pady=20)
        username = AccessWindow._entry(body, "Имя пользователя")
        display = AccessWindow._entry(body, "Отображаемое имя")
        password = AccessWindow._entry(body, "Временный пароль — минимум 12 символов", "•")
        PasswordStrengthIndicator(body, password, self.security, username.get)
        roles = [
            role for role in self.security.list_roles() if role["id"] != "owner" or "*" in self.session.permissions
        ]
        tk.Label(body, text="Роль", bg="#0d1524", fg="#94a3b8", anchor="w").pack(fill="x")
        role_name = tk.StringVar(value=roles[0]["name"] if roles else "")
        role_box = ttk.Combobox(body, textvariable=role_name, values=[role["name"] for role in roles], state="readonly")
        role_box.pack(fill="x", pady=(5, 14))
        tk.Label(body, text="Доступ к проектам", bg="#0d1524", fg="#94a3b8", anchor="w").pack(fill="x")
        scopes = {}
        for project in self.panel.projects:
            variable = tk.BooleanVar(value=True)
            scopes[project.id] = variable
            tk.Checkbutton(
                body,
                text=project.name,
                variable=variable,
                bg="#0d1524",
                fg="#e8edf7",
                selectcolor="#101a2b",
                activebackground="#0d1524",
                activeforeground="white",
            ).pack(anchor="w")

        def save():
            try:
                role = next(item for item in roles if item["name"] == role_name.get())
                if role["id"] in {"owner", "administrator"} and not self.panel._ensure_reauthentication():
                    return
                self.security.create_user(
                    self.session,
                    username.get(),
                    display.get(),
                    password.get(),
                    role["id"],
                    [project_id for project_id, variable in scopes.items() if variable.get()],
                    must_change_password=True,
                )
                dialog.destroy()
                self._refresh_users()
            except (ValueError, PermissionDeniedError, sqlite3.IntegrityError) as error:
                messagebox.showerror("NEXUS", str(error), parent=dialog)

        ttk.Button(body, text="Создать пользователя", style="Accent.TButton", command=save).pack(fill="x", pady=(14, 0))

    def _toggle_user(self):
        selected = self.users_tree.selection()
        if not selected:
            return
        user_id = int(selected[0])
        if not self.panel._ensure_reauthentication():
            return
        user = next(item for item in self.security.list_users() if item["id"] == user_id)
        try:
            self.security.set_user_active(self.session, user_id, not bool(user["is_active"]))
            self._refresh_users()
        except (ValueError, PermissionDeniedError) as error:
            messagebox.showerror("NEXUS", str(error), parent=self)

    def _reset_user_mfa(self):
        selected = self.users_tree.selection()
        if not selected or not self.panel._ensure_reauthentication():
            return
        user_id = int(selected[0])
        user = next(item for item in self.security.list_users() if item["id"] == user_id)
        if not messagebox.askyesno(
            "NEXUS",
            f"Сбросить 2FA пользователя {user['display_name']}?\nПользователь должен будет настроить 2FA заново.",
            parent=self,
        ):
            return
        try:
            self.security.reset_user_mfa(self.panel.session, user_id)
            self._refresh_users()
        except PermissionDeniedError as error:
            messagebox.showerror("NEXUS", str(error), parent=self)

    def _edit_user_access(self):
        selected = self.users_tree.selection()
        if not selected:
            return
        user_id = int(selected[0])
        user = next(item for item in self.security.list_users() if item["id"] == user_id)
        dialog = tk.Toplevel(self)
        dialog.title("Роль и доступ пользователя")
        dialog.configure(bg="#0d1524")
        dialog.transient(self)
        dialog.grab_set()
        body = tk.Frame(dialog, bg="#0d1524")
        body.pack(padx=22, pady=20)
        tk.Label(
            body,
            text=f"{user['display_name']}  •  {user['username']}",
            bg="#0d1524",
            fg="#f8fafc",
            font=("Segoe UI Semibold", 12),
        ).pack(anchor="w", pady=(0, 14))
        roles = [
            role for role in self.security.list_roles() if role["id"] != "owner" or "*" in self.session.permissions
        ]
        role_by_id = {role["id"]: role for role in roles}
        current_role = role_by_id.get(user["role_id"], roles[0])
        role_name = tk.StringVar(value=current_role["name"])
        ttk.Combobox(body, textvariable=role_name, values=[role["name"] for role in roles], state="readonly").pack(
            fill="x", pady=(0, 14)
        )
        current_projects = set(json.loads(user["allowed_projects"]))
        scopes = {}
        for project in self.panel.projects:
            variable = tk.BooleanVar(value="*" in current_projects or project.id in current_projects)
            scopes[project.id] = variable
            tk.Checkbutton(
                body,
                text=project.name,
                variable=variable,
                bg="#0d1524",
                fg="#e8edf7",
                selectcolor="#101a2b",
                activebackground="#0d1524",
                activeforeground="white",
            ).pack(anchor="w")

        def save():
            try:
                role = next(item for item in roles if item["name"] == role_name.get())
                if not self.panel._ensure_reauthentication():
                    return
                self.security.update_user_access(
                    self.session,
                    user_id,
                    role["id"],
                    [project_id for project_id, variable in scopes.items() if variable.get()],
                )
                dialog.destroy()
                self._refresh_users()
            except (ValueError, PermissionDeniedError) as error:
                messagebox.showerror("NEXUS", str(error), parent=dialog)

        ttk.Button(body, text="Сохранить доступ", style="Accent.TButton", command=save).pack(fill="x", pady=(14, 0))

    def _build_roles(self):
        self.roles_tree = ttk.Treeview(self.roles_tab, columns=("name", "type", "permissions"), show="headings")
        for key, title, width in (("name", "Роль", 220), ("type", "Тип", 120), ("permissions", "Права", 500)):
            self.roles_tree.heading(key, text=title)
            self.roles_tree.column(key, width=width, anchor="w")
        self.roles_tree.pack(fill="both", expand=True)
        if AuthorizationService.can(self.session, "roles.manage"):
            ttk.Button(self.roles_tab, text="＋ Создать роль", command=self._create_role).pack(anchor="w", pady=(10, 0))
        self._refresh_roles()

    def _refresh_roles(self):
        self.roles_tree.delete(*self.roles_tree.get_children())
        for role in self.security.list_roles():
            permissions = "Все права" if "*" in role["permissions"] else ", ".join(role["permissions"])
            self.roles_tree.insert(
                "", "end", values=(role["name"], "Системная" if role["builtin"] else "Пользовательская", permissions)
            )

    def _create_role(self):
        dialog = tk.Toplevel(self)
        dialog.title("Новая роль")
        dialog.configure(bg="#0d1524")
        dialog.transient(self)
        dialog.grab_set()
        body = tk.Frame(dialog, bg="#0d1524")
        body.pack(padx=22, pady=20)
        role_id = AccessWindow._entry(body, "ID роли")
        name = AccessWindow._entry(body, "Название")
        tk.Label(body, text="Permissions", bg="#0d1524", fg="#94a3b8", anchor="w").pack(fill="x")
        choices = tk.Listbox(
            body,
            selectmode="multiple",
            bg="#09111e",
            fg="#e8edf7",
            selectbackground="#17466a",
            relief="flat",
            width=54,
            height=16,
        )
        for permission in PERMISSIONS:
            choices.insert("end", permission)
        choices.pack(fill="both", expand=True, pady=(5, 12))

        def save():
            try:
                selected = [PERMISSIONS[index] for index in choices.curselection()]
                self.security.create_role(self.session, role_id.get(), name.get(), selected)
                dialog.destroy()
                self._refresh_roles()
            except (ValueError, PermissionDeniedError, sqlite3.IntegrityError) as error:
                messagebox.showerror("NEXUS", str(error), parent=dialog)

        ttk.Button(body, text="Создать роль", style="Accent.TButton", command=save).pack(fill="x")

    def _build_audit(self):
        columns = ("time", "user", "action", "resource", "result")
        self.audit_tree = ttk.Treeview(self.audit_tab, columns=columns, show="headings")
        for key, title, width in zip(
            columns,
            ("Время", "Пользователь", "Действие", "Ресурс", "Результат"),
            (190, 130, 220, 230, 90),
            strict=True,
        ):
            self.audit_tree.heading(key, text=title)
            self.audit_tree.column(key, width=width, anchor="w")
        self.audit_tree.pack(fill="both", expand=True)
        ttk.Button(self.audit_tab, text="Обновить", command=self._refresh_audit).pack(anchor="w", pady=(10, 0))
        self._refresh_audit()

    def _refresh_audit(self):
        self.audit_tree.delete(*self.audit_tree.get_children())
        for entry in self.security.list_audit():
            self.audit_tree.insert(
                "",
                "end",
                values=(
                    entry["timestamp"],
                    entry["username"],
                    entry["action"],
                    entry["resource_id"] or "—",
                    "Успешно" if entry["success"] else "Отказ",
                ),
            )


class ControlCenter(tk.Tk):
    def __init__(self, security: SQLiteSecurityStore, session):
        super().__init__()
        self.security = security
        self.session = session
        self.logout_requested = False
        self.title("NEXUS Control Panel")
        apply_window_icon(self)
        self.geometry("1360x800")
        self.minsize(1080, 650)
        self.configure(bg="#080d17")
        self.catalog = ProjectCatalog(PROJECTS_FILE)
        self.projects = self.catalog.load()
        self.panel_config = self._load_panel_config()
        self.build_manager = BuildManager(
            APP_DIR / "build-management", "https://nexusmc-site.robloxksergg.workers.dev/api/launcher/builds"
        )
        self.events: queue.Queue = queue.Queue()
        self.controllers: dict[str, ServerController] = {}
        self.network_states: dict[str, str] = {}
        self.command_history: list[str] = []
        self.history_index = 0
        self.selected_key: str | None = None
        self.rendered_console_key: str | None = None
        self._style()
        self._build()
        self._refresh()
        self.after(100, self._poll)
        self.after(1000, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._last_user_activity = time.time()
        self._last_session_touch = 0.0
        self.bind_all("<KeyPress>", self._mark_activity, add="+")
        self.bind_all("<ButtonPress>", self._mark_activity, add="+")

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#070c15")
        style.configure("Card.TFrame", background="#0d1524")
        style.configure("Header.TFrame", background="#0a111d")
        style.configure("Footer.TFrame", background="#080e18")
        style.configure("TLabel", background="#080d17", foreground="#e8edf7", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#0d1422", foreground="#e8edf7", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#0a111d", font=("Segoe UI Semibold", 22), foreground="#f8fafc")
        style.configure(
            "ServerTitle.TLabel", background="#0d1524", font=("Segoe UI Semibold", 22), foreground="#f8fafc"
        )
        style.configure("Value.TLabel", background="#0d1524", font=("Segoe UI Semibold", 12), foreground="#f8fafc")
        style.configure("Muted.TLabel", background="#0d1524", foreground="#64748b")
        style.configure("Section.TLabel", background="#0d1524", foreground="#7185a3", font=("Segoe UI Semibold", 9))
        style.configure("TButton", padding=(12, 8), background="#141e30", foreground="#e8edf7", borderwidth=0)
        style.map("TButton", background=[("active", "#20304a"), ("disabled", "#111827")])
        style.configure("Accent.TButton", background="#147ca8", foreground="white", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#2563eb")])
        style.configure("Stop.TButton", background="#141e30", foreground="#cbd5e1")
        style.map("Stop.TButton", background=[("active", "#4a1e2a")], foreground=[("active", "#fecaca")])
        style.configure(
            "TNotebook",
            background="#0d1524",
            borderwidth=0,
            tabmargins=0,
            bordercolor="#0d1524",
            lightcolor="#0d1524",
            darkcolor="#0d1524",
            relief="flat",
        )
        style.configure(
            "TNotebook.Tab",
            background="#0d1524",
            foreground="#64748b",
            padding=(18, 11),
            borderwidth=0,
            bordercolor="#1d2a3b",
            lightcolor="#0d1524",
            darkcolor="#0d1524",
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#101a2b")],
            foreground=[("selected", "#f8fafc")],
            bordercolor=[("selected", "#22a9ce")],
            lightcolor=[("selected", "#101a2b")],
            darkcolor=[("selected", "#101a2b")],
        )

    def _build(self):
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)
        header = ttk.Frame(root, style="Header.TFrame", padding=(24, 14))
        header.pack(fill="x")
        branding = ttk.Frame(header, style="Header.TFrame")
        branding.pack(side="left")
        ttk.Label(branding, text="NEXUS Control Panel", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            branding,
            text="Управление инфраструктурой",
            background="#0a111d",
            foreground="#64748b",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        launcher = ttk.Frame(header, style="Header.TFrame")
        launcher.pack(side="right")
        self.launcher_state = tk.StringVar(value="○ Проверка")
        launcher_info = ttk.Frame(launcher, style="Header.TFrame")
        launcher_info.pack(side="left", padx=(0, 14))
        ttk.Label(launcher_info, text="NEXUS Launcher", background="#0a111d", foreground="#f8fafc").pack(anchor="e")
        ttk.Label(
            launcher_info,
            textvariable=self.launcher_state,
            background="#0a111d",
            foreground="#38bdf8",
            font=("Segoe UI", 9),
        ).pack(anchor="e")
        if self._can("launcher.view"):
            ttk.Button(launcher, text="Запустить", style="Accent.TButton", command=self._run_launcher).pack(side="left")
        if self._can("launcher.manage"):
            ttk.Button(launcher, text="⋯", width=3, command=self._choose_launcher).pack(side="left", padx=(8, 0))
        user_button = ttk.Button(
            launcher,
            text=f"{self.session.display_name}\n{self.session.role_name}  ▾",
            command=self._user_menu,
        )
        user_button.pack(side="left", padx=(14, 0))

        panes = tk.PanedWindow(root, orient="horizontal", bg="#1d2a3b", sashwidth=5, sashrelief="flat", bd=0)
        panes.pack(fill="both", expand=True, padx=18, pady=18)
        left = tk.Frame(panes, bg="#0a111d", width=370)
        right = ttk.Frame(panes, style="Card.TFrame", padding=(22, 18))
        panes.add(left, minsize=310, width=370, stretch="never")
        panes.add(right, minsize=620, stretch="always")

        sidebar_head = tk.Frame(left, bg="#0a111d")
        sidebar_head.pack(fill="x", padx=16, pady=(16, 10))
        tk.Label(sidebar_head, text="СЕРВЕРЫ", bg="#0a111d", fg="#7185a3", font=("Segoe UI Semibold", 9)).pack(
            side="left"
        )
        self.server_canvas = tk.Canvas(left, bg="#0a111d", highlightthickness=0, bd=0)
        self.server_canvas.pack(fill="both", expand=True, padx=10)
        self.server_list = tk.Frame(self.server_canvas, bg="#0a111d")
        self.server_window = self.server_canvas.create_window((0, 0), window=self.server_list, anchor="nw")
        self.server_list.bind(
            "<Configure>", lambda _event: self.server_canvas.configure(scrollregion=self.server_canvas.bbox("all"))
        )
        self.server_canvas.bind(
            "<Configure>", lambda event: self.server_canvas.itemconfigure(self.server_window, width=event.width)
        )
        actions = ttk.Frame(left, style="Header.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        if self._can("nexus_launcher.projects.create"):
            ttk.Button(actions, text="＋ Проект", command=self._add_project).pack(
                side="left", padx=(16, 5), pady=(0, 16)
            )
        if self._can("servers.create"):
            ttk.Button(actions, text="＋ Сервер", command=self._add_server).pack(side="left", pady=(0, 16))

        self._build_server_header(right)

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True, pady=(18, 0))
        self.overview = ttk.Frame(self.tabs, style="Card.TFrame", padding=20)
        self.console_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=12)
        self.logs_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=12)
        self.builds_tab = ttk.Frame(self.tabs, style="Card.TFrame", padding=12)
        self.tabs.add(self.overview, text="Обзор")
        if self._can("console.view"):
            self.tabs.add(self.console_tab, text="Консоль")
        if self._can("logs.view"):
            self.tabs.add(self.logs_tab, text="Логи")
        if self._can("builds.view"):
            self.tabs.add(self.builds_tab, text="Сборка")
        self._build_overview()
        self._build_console()
        self._build_logs()
        self._build_build_management()
        footer = ttk.Frame(root, style="Footer.TFrame", padding=(22, 10))
        footer.pack(fill="x")
        self.global_status = tk.StringVar(value="0 / 0 серверов запущено")
        self.status = tk.StringVar(value="Сохранено")
        ttk.Label(footer, textvariable=self.global_status, background="#080e18", foreground="#94a3b8").pack(side="left")
        ttk.Label(footer, textvariable=self.status, background="#080e18", foreground="#64748b").pack(
            side="left", expand=True
        )
        ttk.Label(
            footer,
            text=f"{self.session.display_name}  •  {self.session.role_name}",
            background="#080e18",
            foreground="#94a3b8",
        ).pack(side="right", padx=(0, 22))
        ttk.Label(footer, text="NEXUS Control Panel  •  v0.3.2", background="#080e18", foreground="#7185a3").pack(
            side="right"
        )
        self._update_launcher_status()

    def _build_server_header(self, parent):
        header = ttk.Frame(parent, style="Card.TFrame")
        header.pack(fill="x")
        title = ttk.Frame(header, style="Card.TFrame")
        title.pack(side="left")
        self.detail_name = tk.StringVar(value="Выберите сервер")
        self.detail_process = tk.StringVar(value="○ Остановлен")
        ttk.Label(title, textvariable=self.detail_name, style="ServerTitle.TLabel").pack(anchor="w")
        self.process_label = ttk.Label(
            title, textvariable=self.detail_process, background="#0d1524", foreground="#38bdf8"
        )
        self.process_label.pack(anchor="w", pady=(5, 0))
        controls = ttk.Frame(header, style="Card.TFrame")
        controls.pack(side="left", padx=(40, 0))
        self.power_button = ttk.Button(
            controls, text="▶ Запустить", style="Accent.TButton", command=self._toggle_server_power
        )
        if self._can("servers.start") or self._can("servers.stop"):
            self.power_button.pack(side="left")

    def _build_overview(self):
        ttk.Label(self.overview, text="ИНФОРМАЦИЯ", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )
        self.detail_values = {}
        for row, key in enumerate(("Minecraft", "Loader", "Адрес"), start=1):
            ttk.Label(self.overview, text=key, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=7)
            value = tk.StringVar(value="—")
            ttk.Label(self.overview, textvariable=value, style="Value.TLabel", wraplength=520).grid(
                row=row, column=1, columnspan=3, sticky="w", padx=(30, 0), pady=7
            )
            self.detail_values[key] = value
        ttk.Label(self.overview, text="RUNTIME", style="Section.TLabel").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(20, 10)
        )
        for row, key in enumerate(("PID", "Время работы", "CPU", "RAM", "Диск"), start=5):
            ttk.Label(self.overview, text=key, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=7)
            value = tk.StringVar(value="—")
            ttk.Label(self.overview, textvariable=value, style="Value.TLabel").grid(
                row=row, column=1, columnspan=3, sticky="w", padx=(30, 0), pady=7
            )
            self.detail_values[key] = value
        ttk.Label(self.overview, text="СБОРКА", style="Section.TLabel").grid(
            row=10, column=0, columnspan=4, sticky="w", pady=(20, 10)
        )
        for row, key in enumerate(("Версия сборки", "Серверные моды", "Состояние сборки"), start=11):
            ttk.Label(self.overview, text=key, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=7)
            value = tk.StringVar(value="—")
            ttk.Label(self.overview, textvariable=value, style="Value.TLabel").grid(
                row=row, column=1, columnspan=3, sticky="w", padx=(30, 0), pady=7
            )
            self.detail_values[key] = value
        ttk.Label(self.overview, text="STORAGE", style="Section.TLabel").grid(
            row=14, column=0, columnspan=4, sticky="w", pady=(20, 10)
        )
        ttk.Label(self.overview, text="Рабочая папка", style="Muted.TLabel").grid(row=15, column=0, sticky="nw", pady=7)
        folder = tk.StringVar(value="Не настроена")
        self.detail_values["Рабочая папка"] = folder
        ttk.Label(self.overview, textvariable=folder, style="Value.TLabel", wraplength=540).grid(
            row=15, column=1, columnspan=3, sticky="w", padx=(30, 0), pady=7
        )
        bottom = ttk.Frame(self.overview, style="Card.TFrame")
        bottom.grid(row=16, column=0, columnspan=4, sticky="w", pady=(22, 0))
        ttk.Button(bottom, text="↻ Проверить соединение", command=self._check_selected).pack(side="left")
        ttk.Button(bottom, text="Открыть папку", command=self._open_instance).pack(side="left", padx=8)
        if self._can("servers.edit"):
            ttk.Button(bottom, text="Выбрать папку", command=self._choose_working_directory).pack(side="left")
            ttk.Button(bottom, text="Настройки сервера", command=self._edit_server).pack(side="left", padx=(8, 0))

    def _build_console(self):
        self.console_text = tk.Text(
            self.console_tab,
            bg="#070b12",
            fg="#cbd5e1",
            insertbackground="white",
            font=("Cascadia Mono", 10),
            wrap="none",
            relief="flat",
        )
        self.console_text.pack(fill="both", expand=True)
        self.console_text.tag_configure("warn", foreground="#fbbf24")
        self.console_text.tag_configure("error", foreground="#f87171")
        self.console_text.tag_configure("command", foreground="#22d3ee")
        command_bar = ttk.Frame(self.console_tab, style="Card.TFrame")
        command_bar.pack(fill="x", pady=(10, 0))
        self.command_entry = ttk.Entry(command_bar)
        self.command_entry.pack(side="left", fill="x", expand=True)
        self.command_entry.bind("<Return>", lambda _event: self._send_command())
        self.command_entry.bind("<Up>", self._history_up)
        self.command_entry.bind("<Down>", self._history_down)
        ttk.Button(command_bar, text="↓ Последние строки", command=lambda: self.console_text.see("end")).pack(
            side="right", padx=6
        )
        ttk.Button(command_bar, text="Отправить", style="Accent.TButton", command=self._send_command).pack(side="right")

    def _build_logs(self):
        toolbar = ttk.Frame(self.logs_tab, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="Обновить", command=self._refresh_logs).pack(side="left")
        ttk.Button(toolbar, text="Открыть папку logs", command=self._open_logs).pack(side="left", padx=7)
        ttk.Button(toolbar, text="Открыть latest.log", command=self._open_latest_log).pack(side="left")
        ttk.Button(toolbar, text="Открыть crash-report", command=self._open_crash_report).pack(side="left", padx=7)
        self.logs_text = tk.Text(
            self.logs_tab, bg="#070b12", fg="#cbd5e1", font=("Cascadia Mono", 10), wrap="none", relief="flat"
        )
        self.logs_text.pack(fill="both", expand=True)

    def _build_build_management(self):
        notebook = ttk.Notebook(self.builds_tab)
        notebook.pack(fill="both", expand=True)
        self.build_meta_tab = ttk.Frame(notebook, style="Card.TFrame", padding=18)
        self.build_files_tab = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        self.build_publish_tab = ttk.Frame(notebook, style="Card.TFrame", padding=18)
        self.build_history_tab = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        notebook.add(self.build_meta_tab, text="Server / Client Build")
        notebook.add(self.build_files_tab, text="Files")
        notebook.add(self.build_publish_tab, text="Publish Update")
        notebook.add(self.build_history_tab, text="History")

        metadata = self.build_manager.metadata()
        self.build_meta_vars = {}
        fields = (
            ("pack_name", "Pack Name"),
            ("display_name", "Display Name"),
            ("season_name", "Season"),
            ("pack_version", "Pack Version"),
            ("minecraft_version", "Minecraft"),
            ("loader", "Loader"),
            ("loader_version", "Loader Version"),
            ("server_address", "Server Address"),
            ("minimum_launcher_version", "Minimum Launcher"),
        )
        for row, (key, label) in enumerate(fields):
            ttk.Label(self.build_meta_tab, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=5)
            var = tk.StringVar(value=getattr(metadata, key))
            self.build_meta_vars[key] = var
            ttk.Entry(self.build_meta_tab, textvariable=var, width=52).grid(
                row=row, column=1, sticky="ew", padx=(20, 0), pady=5
            )
        self.build_maintenance = tk.BooleanVar(value=metadata.maintenance)
        ttk.Checkbutton(self.build_meta_tab, text="Maintenance mode", variable=self.build_maintenance).grid(
            row=len(fields), column=1, sticky="w", pady=8
        )
        ttk.Button(
            self.build_meta_tab, text="Сохранить draft", style="Accent.TButton", command=self._save_build_metadata
        ).grid(row=len(fields) + 1, column=1, sticky="w", pady=12)
        self.build_meta_tab.columnconfigure(1, weight=1)

        toolbar = ttk.Frame(self.build_files_tab, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="＋ Upload", style="Accent.TButton", command=self._add_build_file).pack(side="left")
        ttk.Button(toolbar, text="Удалить из draft", command=self._remove_build_file).pack(side="left", padx=8)
        ttk.Button(toolbar, text="Проверить", command=self._validate_build).pack(side="left")
        self.build_files_tree = ttk.Treeview(
            self.build_files_tab, columns=("path", "scope", "mode", "size", "mod", "hash"), show="headings"
        )
        for key, title, width in (
            ("path", "Destination", 300),
            ("scope", "Scope", 80),
            ("mode", "Mode", 90),
            ("size", "Size", 90),
            ("mod", "Mod", 130),
            ("hash", "SHA-256", 220),
        ):
            self.build_files_tree.heading(key, text=title)
            self.build_files_tree.column(key, width=width, anchor="w")
        self.build_files_tree.pack(fill="both", expand=True)

        ttk.Label(self.build_publish_tab, text="Release notes", style="Section.TLabel").pack(anchor="w")
        self.build_release_notes = tk.Text(
            self.build_publish_tab, height=9, bg="#070b12", fg="#cbd5e1", insertbackground="white", relief="flat"
        )
        self.build_release_notes.pack(fill="x", pady=10)
        ttk.Button(
            self.build_publish_tab, text="Publish Update", style="Accent.TButton", command=self._publish_build
        ).pack(anchor="w")
        self.build_publish_status = tk.StringVar(value="DRAFT — изменения не опубликованы")
        ttk.Label(self.build_publish_tab, textvariable=self.build_publish_status, style="Muted.TLabel").pack(
            anchor="w", pady=10
        )

        self.build_history_tree = ttk.Treeview(
            self.build_history_tab, columns=("version", "author", "time", "files", "notes"), show="headings"
        )
        for key, title, width in (
            ("version", "Version", 110),
            ("author", "Author", 130),
            ("time", "Time", 140),
            ("files", "Files", 70),
            ("notes", "Notes", 350),
        ):
            self.build_history_tree.heading(key, text=title)
            self.build_history_tree.column(key, width=width, anchor="w")
        self.build_history_tree.pack(fill="both", expand=True)
        ttk.Button(self.build_history_tab, text="Rollback / Republish", command=self._rollback_build).pack(
            anchor="w", pady=8
        )
        self._refresh_build_management()

    def _save_build_metadata(self):
        if not self._require("builds.publish"):
            return
        current = self.build_manager.metadata()
        values = {key: var.get().strip() for key, var in self.build_meta_vars.items()}
        values.update(
            description=current.description,
            logo=current.logo,
            background=current.background,
            maintenance=self.build_maintenance.get(),
        )
        self.build_manager.save_metadata(BuildMetadata(**values), self.session.username)
        self.build_publish_status.set("DRAFT — metadata сохранены")

    def _add_build_file(self):
        if not self._require("builds.publish"):
            return
        filename = filedialog.askopenfilename(parent=self)
        if not filename:
            return
        destination = simpledialog.askstring(
            "Destination", "Путь, например mods/StaffCore.jar", initialvalue=f"mods/{Path(filename).name}", parent=self
        )
        scope = simpledialog.askstring("Scope", "SERVER, CLIENT или BOTH", initialvalue="BOTH", parent=self)
        mode = simpledialog.askstring("Mode", "REQUIRED, OPTIONAL или PRESERVE", initialvalue="REQUIRED", parent=self)
        if not destination or not scope or not mode:
            return
        optional = {}
        if mode.strip().upper() == "OPTIONAL":
            optional["display_name"] = (
                simpledialog.askstring("Optional mod", "Display Name", initialvalue=Path(filename).stem, parent=self)
                or Path(filename).stem
            )
            optional["description"] = simpledialog.askstring("Optional mod", "Description", parent=self) or ""
            optional["category"] = (
                simpledialog.askstring(
                    "Optional mod",
                    "Category: graphics/performance/interface/quality_of_life/gameplay/other",
                    initialvalue="other",
                    parent=self,
                )
                or "other"
            )
            optional["performance_impact"] = (
                simpledialog.askstring("Optional mod", "Performance impact", initialvalue="medium", parent=self) or ""
            )
            optional["default_enabled"] = messagebox.askyesno("Optional mod", "Включать по умолчанию?", parent=self)
            optional["recommended"] = messagebox.askyesno("Optional mod", "Пометить как recommended?", parent=self)
        try:
            self.build_manager.add_file(Path(filename), destination, scope, mode, self.session.username, **optional)
        except Exception as error:
            messagebox.showerror("Build", str(error), parent=self)
        self._refresh_build_management()

    def _remove_build_file(self):
        if not self._require("builds.publish"):
            return
        selected = self.build_files_tree.selection()
        if selected:
            self.build_manager.remove_file(self.build_files_tree.item(selected[0], "values")[0], self.session.username)
            self._refresh_build_management()

    def _validate_build(self):
        errors = self.build_manager.validate()
        messagebox.showinfo("Build validation", "\n".join(errors) if errors else "Validation passed", parent=self)

    def _publish_build(self):
        if not self._require("builds.publish") or not self._ensure_reauthentication():
            return
        notes = self.build_release_notes.get("1.0", "end").strip()
        try:
            path = self.build_manager.publish(notes, self.session.username)
            self.build_publish_status.set(f"PUBLISHED • {path.parent.name}")
        except Exception as error:
            messagebox.showerror("Publish failed", str(error), parent=self)
        self._refresh_build_management()

    def _rollback_build(self):
        if not self._require("builds.publish") or not self._ensure_reauthentication():
            return
        selected = self.build_history_tree.selection()
        if selected:
            version = self.build_history_tree.item(selected[0], "values")[0]
            self.build_manager.rollback(version, self.session.username)
            self.build_publish_status.set(f"PUBLISHED rollback • {version}")

    def _refresh_build_management(self):
        if not hasattr(self, "build_files_tree"):
            return
        self.build_files_tree.delete(*self.build_files_tree.get_children())
        for item in self.build_manager.files():
            self.build_files_tree.insert(
                "",
                "end",
                values=(
                    item.path,
                    item.scope,
                    item.mode,
                    f"{item.size / 1048576:.1f} MB",
                    f"{item.mod_id} {item.mod_version}".strip(),
                    item.sha256,
                ),
            )
        self.build_history_tree.delete(*self.build_history_tree.get_children())
        for item in self.build_manager.history():
            self.build_history_tree.insert(
                "",
                "end",
                values=(
                    item.get("metadata", {}).get("pack_version", ""),
                    item.get("author", ""),
                    item.get("publishedAt", ""),
                    item.get("filesChanged", 0),
                    item.get("notes", ""),
                ),
            )

    def _rows(self):
        for pi, project in enumerate(self.projects):
            for si, server in enumerate(project.servers):
                if self._can("servers.view", project.id, server.id):
                    yield pi, si, project, server

    def _can(self, permission, project_id=None, server_id=None):
        return AuthorizationService.can(self.session, permission, project_id, server_id)

    def _require(self, permission, project=None, server=None):
        project_id = project.id if project else None
        server_id = server.id if server else None
        try:
            AuthorizationService.require(self.session, permission, project_id, server_id)
            return True
        except PermissionDeniedError as error:
            self.security.audit(
                self.session,
                "nexus_launcher.security.permission_denied",
                "server" if server else "project" if project else "application",
                f"{project_id}/{server_id}" if server else project_id,
                False,
                {"permission": permission},
            )
            messagebox.showerror("NEXUS Control Panel", str(error), parent=self)
            return False

    def _ensure_reauthentication(self):
        if AuthorizationService.has_fresh_reauthentication(self.session):
            return True
        dialog = ReauthDialog(self, self.security, self.session)
        if dialog.session:
            self.session = dialog.session
            return True
        return False

    def _mark_activity(self, _event=None):
        self._last_user_activity = time.time()

    @staticmethod
    def _key(project: Project, server: ServerProfile) -> str:
        return f"{project.id}/{server.id}"

    def _controller(self, project: Project, server: ServerProfile) -> ServerController:
        key = self._key(project, server)
        if key not in self.controllers:
            controller_type = (
                PterodactylServerController if server.management_type == "pterodactyl" else LocalServerController
            )
            self.controllers[key] = controller_type(
                server, lambda kind, value, server_key=key: self.events.put((server_key, kind, value)),
                authorization=lambda permission, actor=self.session, project_id=project.id, server_id=server.id:
                    self.security.operation_authorization(actor, permission, project_id, server_id)
            )
        return self.controllers[key]

    def _refresh(self):
        available = [self._key(project, server) for _pi, _si, project, server in self._rows()]
        if self.selected_key not in available:
            self.selected_key = available[0] if available else None
        for child in self.server_list.winfo_children():
            child.destroy()
        for pi, project in enumerate(self.projects):
            if not self._can("nexus_launcher.projects.view", project.id):
                continue
            visible_servers = [
                (si, server)
                for si, server in enumerate(project.servers)
                if self._can("servers.view", project.id, server.id)
            ]
            if not visible_servers and project.servers:
                continue
            project_title = tk.Label(
                self.server_list,
                text=project.name.upper(),
                bg="#0a111d",
                fg="#64748b",
                font=("Segoe UI Semibold", 9),
                anchor="w",
            )
            project_title.pack(fill="x", padx=8, pady=(12, 6))
            if not visible_servers:
                tk.Label(
                    self.server_list,
                    text="В проекте нет серверов",
                    bg="#0a111d",
                    fg="#64748b",
                    font=("Segoe UI", 9),
                    anchor="w",
                ).pack(fill="x", padx=12, pady=(0, 8))
            for si, server in visible_servers:
                self._build_server_card(pi, si, project, server)
        if not self.projects:
            empty = tk.Frame(self.server_list, bg="#0a111d")
            empty.pack(fill="x", padx=12, pady=30)
            tk.Label(empty, text="Нет проектов", bg="#0a111d", fg="#f8fafc", font=("Segoe UI Semibold", 13)).pack()
            tk.Label(
                empty,
                text="Создайте первый проект, чтобы начать\nуправление серверами.",
                bg="#0a111d",
                fg="#64748b",
                justify="center",
            ).pack(pady=8)
        running = sum(controller.state.status == "running" for controller in self.controllers.values())
        errors = sum(controller.state.status == "error" for controller in self.controllers.values())
        suffix = f"  •  {errors} требует внимания" if errors else ""
        self.global_status.set(f"{running} / {len(available)} серверов запущено{suffix}")
        self._show_selection()

    def _build_server_card(self, pi, si, project, server):
        key = self._key(project, server)
        selected = key == self.selected_key
        background = "#10243a" if selected else "#0d1524"
        border = "#22a9ce" if selected else "#1d2a3b"
        card = tk.Frame(
            self.server_list,
            bg=background,
            highlightbackground=border,
            highlightcolor=border,
            highlightthickness=1,
            cursor="hand2",
        )
        card.pack(fill="x", padx=6, pady=5)
        body = tk.Frame(card, bg=background)
        body.pack(fill="x", padx=13, pady=11)
        state = self._controller(project, server).state.status
        dot_color = {"running": "#4ade80", "error": "#f87171", "starting": "#38bdf8", "stopping": "#fbbf24"}.get(
            state, "#64748b"
        )
        tk.Label(body, text="●", bg=background, fg=dot_color, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        tk.Label(body, text=server.name, bg=background, fg="#f8fafc", font=("Segoe UI Semibold", 11), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(7, 0)
        )
        menu_button = tk.Label(body, text="⋯", bg=background, fg="#94a3b8", font=("Segoe UI", 15), cursor="hand2")
        if self._can("servers.edit", project.id, server.id) or self._can("servers.delete", project.id, server.id):
            menu_button.grid(row=0, column=2, sticky="e")
        body.columnconfigure(1, weight=1)
        tk.Label(
            body,
            text=f"{server.minecraft_version}  •  {server.loader.title()}",
            bg=background,
            fg="#94a3b8",
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=1, columnspan=2, sticky="w", padx=(7, 0), pady=(3, 8))
        process = self._status_text(state).replace("○ ", "").replace("● ", "").replace("◌ ", "")
        network = self.network_states.get(key, "Не проверена")
        tk.Label(body, text=f"Процесс  {process}", bg=background, fg="#7185a3", font=("Segoe UI", 9)).grid(
            row=2, column=1, sticky="w", padx=(7, 0)
        )
        network_color = (
            "#4ade80" if network.startswith("Онлайн") else ("#f87171" if network == "Недоступна" else "#64748b")
        )
        tk.Label(body, text=f"●  {network}", bg=background, fg=network_color, font=("Segoe UI", 9)).grid(
            row=2, column=2, sticky="e"
        )
        for widget in (card, body, *body.winfo_children()):
            if widget is menu_button:
                continue
            widget.bind("<Button-1>", lambda _event, row=(pi, si): self._select_server_card(*row))
            widget.bind("<Double-1>", lambda _event, row=(pi, si): self._edit_card(*row))
            widget.bind("<Enter>", lambda _event, frame=card, active=selected: self._card_hover(frame, active, True))
            widget.bind("<Leave>", lambda _event, frame=card, active=selected: self._card_hover(frame, active, False))
        menu_button.bind("<Button-1>", lambda event, row=(pi, si): self._server_menu(event, *row))

    @staticmethod
    def _card_hover(card, selected, entered):
        card.configure(highlightbackground="#22a9ce" if selected or entered else "#1d2a3b")

    def _select_server_card(self, pi, si):
        self.selected_key = self._key(self.projects[pi], self.projects[pi].servers[si])
        self._refresh()

    def _edit_card(self, pi, si):
        self.selected_key = self._key(self.projects[pi], self.projects[pi].servers[si])
        if self._can("servers.edit", self.projects[pi].id, self.projects[pi].servers[si].id):
            self._edit_server()

    def _server_menu(self, event, pi, si):
        self.selected_key = self._key(self.projects[pi], self.projects[pi].servers[si])
        menu = tk.Menu(
            self, tearoff=False, bg="#101a2b", fg="#f8fafc", activebackground="#1d3555", activeforeground="white"
        )
        project, server = self.projects[pi], self.projects[pi].servers[si]
        if self._can("servers.edit", project.id, server.id):
            menu.add_command(label="Редактировать", command=self._edit_server)
        if self._can("servers.delete", project.id, server.id):
            menu.add_separator()
            menu.add_command(label="Удалить", command=self._delete_server)
        menu.tk_popup(event.x_root, event.y_root)

    def _selection(self, notify=True):
        if not self.selected_key:
            if notify:
                messagebox.showinfo("NEXUS Control Panel", "Выберите сервер")
            return None
        for pi, si, project, server in self._rows():
            if self._key(project, server) == self.selected_key:
                return pi, si, project, server
        return None

    @staticmethod
    def _status_text(status):
        return {
            "stopped": "○ Остановлен",
            "starting": "◌ Запускается",
            "running": "● Работает",
            "stopping": "◌ Останавливается",
            "error": "● Ошибка",
        }.get(status, status)

    def _show_selection(self):
        selected = self._selection(False)
        if not selected:
            return
        _pi, _si, project, server = selected
        controller = self._controller(project, server)
        state = controller.state
        self.detail_name.set(server.name)
        detail = self._status_text(state.status)
        if state.last_error:
            detail += f" — {state.last_error}"
        self.detail_process.set(detail)
        self.process_label.configure(
            foreground={"running": "#4ade80", "error": "#f87171", "starting": "#38bdf8", "stopping": "#fbbf24"}.get(
                state.status, "#94a3b8"
            )
        )
        self.detail_values["Minecraft"].set(server.minecraft_version)
        self.detail_values["Loader"].set(server.loader.title())
        self.detail_values["PID"].set(str(state.pid) if state.pid else "—")
        self.detail_values["Время работы"].set(format_uptime(state.uptime) if state.started_at else "—")
        self.detail_values["CPU"].set(f"{state.cpu_percent:.1f}%" if state.status == "running" else "—")
        memory = f"{state.memory_bytes / 1024**3:.2f} / {state.memory_limit_bytes / 1024**3:.0f} ГБ"
        self.detail_values["RAM"].set(memory if state.memory_limit_bytes else "—")
        self.detail_values["Диск"].set(f"{state.disk_bytes / 1024**3:.2f} ГБ" if state.disk_bytes else "—")
        self.detail_values["Версия сборки"].set(state.pack_version or "Проверяется…")
        mods = f"{state.installed_mods} / {state.expected_mods}" if state.expected_mods else "Проверяется…"
        self.detail_values["Серверные моды"].set(mods)
        if state.expected_mods:
            if state.missing_mods == 0 and state.extra_mods == 0:
                pack_status = "Синхронизирована"
            else:
                pack_status = f"Не хватает: {state.missing_mods}  •  Лишних: {state.extra_mods}"
        else:
            pack_status = "Ожидание проверки"
        self.detail_values["Состояние сборки"].set(pack_status)
        self.detail_values["Адрес"].set(server.address)
        self.detail_values["Рабочая папка"].set(server.working_directory or "Не настроена")
        if state.status == "starting":
            self.power_button.configure(text="Запуск…", state="disabled", style="Accent.TButton")
        elif state.status == "running":
            allowed = self._can("servers.stop", project.id, server.id)
            self.power_button.configure(
                text="■ Остановить", state="normal" if allowed else "disabled", style="Stop.TButton"
            )
        elif state.status == "stopping":
            self.power_button.configure(text="Остановка…", state="disabled", style="Stop.TButton")
        else:
            allowed = self._can("servers.start", project.id, server.id)
            self.power_button.configure(
                text="▶ Запустить", state="normal" if allowed else "disabled", style="Accent.TButton"
            )
        key = self._key(project, server)
        if self.rendered_console_key != key:
            self._render_console(controller)
            self.rendered_console_key = key

    def _render_console(self, controller):
        self.console_text.delete("1.0", "end")
        for line in controller.console:
            self._append_console_line(line)
        if controller.console:
            self.console_text.see("end")

    def _append_console_line(self, line):
        upper = str(line).upper()
        tag = "error" if "ERROR" in upper or "EXCEPTION" in upper else ("warn" if "WARN" in upper else "")
        self.console_text.insert("end", str(line) + "\n", tag)

    def _start_server(self):
        selected = self._selection()
        if selected:
            _pi, _si, project, server = selected
            if not self._require("servers.start", project, server):
                return
            success = self._controller(project, server).start()
            self.security.audit(self.session, "server.start", "server", self._key(project, server), success, {})

    def _toggle_server_power(self):
        selected = self._selection()
        if not selected:
            return
        _pi, _si, project, server = selected
        controller = self._controller(project, server)
        if controller.state.status in {"starting", "stopping"}:
            return
        if controller.state.status == "running":
            if not self._require("servers.stop", project, server):
                return
            controller.state.status = "stopping"
            self._show_selection()
            self.update_idletasks()
            controller.stop()
            self.security.audit(self.session, "server.stop", "server", self._key(project, server), True, {})
        else:
            if not self._require("servers.start", project, server):
                return
            controller.state.status = "starting"
            self._show_selection()
            self.update_idletasks()
            success = controller.start()
            self.security.audit(self.session, "server.start", "server", self._key(project, server), success, {})

    def _stop_server(self):
        selected = self._selection()
        if selected:
            if not self._require("servers.stop", selected[2], selected[3]):
                return
            self._controller(selected[2], selected[3]).stop()
            self.security.audit(self.session, "server.stop", "server", self._key(selected[2], selected[3]), True, {})

    def _restart_server(self):
        selected = self._selection()
        if selected:
            if not self._require("servers.restart", selected[2], selected[3]):
                return
            self._controller(selected[2], selected[3]).restart()
            self.security.audit(self.session, "server.restart", "server", self._key(selected[2], selected[3]), True, {})

    def _send_command(self):
        selected = self._selection()
        command = self.command_entry.get().strip()
        if selected and command and not self._require("servers.command", selected[2], selected[3]):
            return
        if selected and command and self._controller(selected[2], selected[3]).send_command(command):
            self.console_text.insert("end", f"> {command}\n", "command")
            self.console_text.see("end")
            self.command_history.append(command)
            self.command_history = self.command_history[-100:]
            self.history_index = len(self.command_history)
            self.command_entry.delete(0, "end")
            self.security.audit(
                self.session,
                "server.command",
                "server",
                self._key(selected[2], selected[3]),
                True,
                {"command": command},
            )
        elif command:
            self.status.set("Команда не отправлена: сервер не работает")

    def _history_up(self, _event):
        if self.command_history:
            self.history_index = max(0, self.history_index - 1)
            self.command_entry.delete(0, "end")
            self.command_entry.insert(0, self.command_history[self.history_index])
        return "break"

    def _history_down(self, _event):
        if self.command_history:
            self.history_index = min(len(self.command_history), self.history_index + 1)
            self.command_entry.delete(0, "end")
            if self.history_index < len(self.command_history):
                self.command_entry.insert(0, self.command_history[self.history_index])
        return "break"

    def _refresh_logs(self):
        selected = self._selection()
        if selected:
            if not self._require("logs.view", selected[2], selected[3]):
                return
            text = self._controller(selected[2], selected[3]).latest_log()
            self.logs_text.delete("1.0", "end")
            self.logs_text.insert("1.0", text)
            self.logs_text.see("end")

    def _open_logs(self):
        selected = self._selection()
        if selected:
            if not self._require("logs.view", selected[2], selected[3]):
                return
            directory = Path(selected[3].working_directory) / "logs"
            self._open(directory)

    def _open_latest_log(self):
        selected = self._selection()
        if selected:
            if not self._require("logs.view", selected[2], selected[3]):
                return
            path = Path(selected[3].working_directory) / "logs" / "latest.log"
            if path.is_file():
                os.startfile(path)
            else:
                messagebox.showinfo("NEXUS Control Panel", "latest.log пока не создан")

    def _open_crash_report(self):
        selected = self._selection()
        if selected:
            if not self._require("logs.view", selected[2], selected[3]):
                return
            directory = Path(selected[3].working_directory) / "crash-reports"
            reports = sorted(directory.glob("*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
            if reports:
                os.startfile(reports[0])
            else:
                messagebox.showinfo("NEXUS Control Panel", "Crash reports не найдены")

    def _choose_working_directory(self):
        selected = self._selection()
        if not selected:
            return
        pi, si, project, server = selected
        if not self._require("servers.edit", project, server):
            return
        controller = self._controller(project, server)
        if controller.state.status in {"starting", "running", "stopping"}:
            messagebox.showwarning("NEXUS", "Остановите сервер перед изменением папки")
            return
        directory = filedialog.askdirectory(initialdir=server.working_directory or None)
        if not directory:
            return
        servers = list(project.servers)
        updated = replace(server, working_directory=directory)
        servers[si] = updated
        self.projects[pi] = replace(project, servers=tuple(servers))
        self.controllers.pop(self._key(project, server), None)
        self.selected_key = self._key(self.projects[pi], updated)
        self._save()

    def _save(self):
        self.status.set("Сохранение...")
        self.update_idletasks()
        try:
            self.catalog.save(self.projects)
            self._refresh()
            self.status.set("Сохранено")
        except OSError as error:
            self.status.set("Ошибка сохранения")
            messagebox.showerror("NEXUS Control Panel", str(error), parent=self)

    def _add_project(self):
        if not self._require("nexus_launcher.projects.create"):
            return
        dialog = tk.Toplevel(self)
        dialog.title("Новый проект")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack()
        project_id, name = tk.StringVar(), tk.StringVar()
        for row, (label, variable) in enumerate((("ID", project_id), ("Название", name))):
            ttk.Label(frame, text=label).grid(row=row, column=0, padx=(0, 10), pady=5)
            ttk.Entry(frame, textvariable=variable, width=35).grid(row=row, column=1, pady=5)

        def save():
            if not project_id.get().strip() or not name.get().strip():
                return
            if any(item.id == project_id.get().strip() for item in self.projects):
                messagebox.showerror("NEXUS", "Такой ID уже существует", parent=dialog)
                return
            self.projects.append(Project(project_id.get().strip(), name.get().strip(), ()))
            self._save()
            self.security.audit(
                self.session, "project.create", "project", project_id.get().strip(), True, {"name": name.get().strip()}
            )
            dialog.destroy()

        ttk.Button(frame, text="Создать", command=save).grid(row=2, column=0, columnspan=2, pady=(12, 0))

    def _add_server(self):
        if not self.projects:
            messagebox.showinfo("NEXUS", "Сначала создайте проект")
            return
        selected = self._selection(False)
        project_index = selected[0] if selected else 0
        project = self.projects[project_index]
        if not self._require("servers.create", project):
            return
        dialog = ServerDialog(self)
        if not dialog.result:
            return
        if any(item.id == dialog.result.id for item in project.servers):
            messagebox.showerror("NEXUS", "Сервер с таким ID уже есть")
            return
        self.projects[project_index] = replace(project, servers=project.servers + (dialog.result,))
        self._save()
        self.security.audit(self.session, "server.create", "server", self._key(project, dialog.result), True, {})

    def _edit_server(self):
        selected = self._selection()
        if not selected:
            return
        pi, si, project, server = selected
        if not self._require("servers.edit", project, server):
            return
        controller = self._controller(project, server)
        if controller.state.status in {"starting", "running", "stopping"}:
            messagebox.showwarning("NEXUS", "Остановите сервер перед изменением настроек управления")
            return
        dialog = ServerDialog(self, server)
        if not dialog.result:
            return
        servers = list(project.servers)
        servers[si] = dialog.result
        self.projects[pi] = replace(project, servers=tuple(servers))
        self.controllers.pop(self._key(project, server), None)
        self._save()
        self.security.audit(self.session, "server.edit", "server", self._key(project, dialog.result), True, {})

    def _delete_server(self):
        selected = self._selection()
        if not selected:
            return
        pi, si, project, server = selected
        if not self._require("servers.delete", project, server):
            return
        if not self._ensure_reauthentication():
            return
        controller = self._controller(project, server)
        if controller.state.status in {"starting", "running", "stopping"}:
            messagebox.showwarning("NEXUS", "Сначала остановите сервер")
            return
        if not messagebox.askyesno(
            "NEXUS", f"Удалить сервер «{server.name}» из списка?\n\nФайлы сервера останутся на диске."
        ):
            return
        servers = list(project.servers)
        servers.pop(si)
        self.projects[pi] = replace(project, servers=tuple(servers))
        self.controllers.pop(self._key(project, server), None)
        self._save()
        self.security.audit(self.session, "server.delete", "server", self._key(project, server), True, {})

    def _check_selected(self):
        selected = self._selection()
        if selected:
            _pi, _si, project, server = selected
            if not self._require("servers.view", project, server):
                return
            key = self._key(project, server)
            self.network_states[key] = "Проверка…"
            self._refresh()
            threading.Thread(target=self._ping_worker, args=(key, server.address), daemon=True).start()

    def _ping_worker(self, key, address):
        try:
            players = ping(address).get("players", {})
            text = f"Онлайн {players.get('online', 0)}/{players.get('max', '?')}"
        except Exception:
            text = "Недоступна"
        self.events.put((key, "network", text))

    def _open_instance(self):
        selected = self._selection()
        if selected:
            if not self._require("servers.view", selected[2], selected[3]):
                return
            path = selected[3].working_directory or (APP_DIR / "instances" / selected[2].id / selected[3].id)
            self._open(path)

    @staticmethod
    def _open(path):
        Path(path).mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def _load_panel_config(self):
        try:
            return json.loads(PANEL_CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_panel_config(self):
        PANEL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        PANEL_CONFIG_FILE.write_text(json.dumps(self.panel_config, ensure_ascii=False, indent=2), encoding="utf-8")

    def _choose_launcher(self):
        if not self._require("launcher.manage"):
            return
        selected = filedialog.askopenfilename(title="Выберите NEXUS Launcher.exe", filetypes=(("Executable", "*.exe"),))
        if selected:
            self.panel_config["launcher_executable"] = selected
            self._save_panel_config()
            self.status.set("Launcher path saved")
            self._update_launcher_status()

    def _launcher_candidates(self):
        configured = self.panel_config.get("launcher_executable")
        if configured:
            yield Path(configured)
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        yield base / "NexusLauncher.exe"
        yield base / "dist" / "NexusLauncher.exe"
        yield Path(__file__).resolve().parents[1] / "dist" / "NexusLauncher.exe"
        yield base / "NEXUS Launcher.exe"
        yield base / "dist" / "NEXUS Launcher.exe"
        yield Path(__file__).resolve().parents[1] / "dist" / "NEXUS Launcher.exe"

    def _update_launcher_status(self):
        found = next((path for path in self._launcher_candidates() if path.is_file()), None)
        self.launcher_state.set("● Готов" if found else "● Не найден")

    def _user_menu(self):
        menu = tk.Menu(
            self,
            tearoff=False,
            bg="#101a2b",
            fg="#f8fafc",
            activebackground="#1d3555",
            activeforeground="white",
        )
        if any(self._can(permission) for permission in ("users.view", "roles.view", "audit.view")):
            menu.add_command(label="Пользователи, роли и журнал", command=lambda: ManagementDialog(self))
            menu.add_separator()
        menu.add_command(
            label="Безопасность аккаунта",
            command=lambda: SecuritySettingsDialog(self),
        )
        menu.add_command(label="Выйти из аккаунта", command=self._logout)
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _change_password(self):
        dialog = PasswordChangeDialog(self, self.security, self.session)
        if dialog.session:
            self.session = dialog.session
            self.status.set("Пароль изменён")

    def _logout(self):
        if any(controller.process and controller.process.poll() is None for controller in self.controllers.values()):
            messagebox.showwarning("NEXUS", "Остановите управляемые серверы перед выходом из аккаунта", parent=self)
            return
        self.security.logout(self.session)
        self.logout_requested = True
        self.destroy()

    def _run_launcher(self):
        if not self._require("launcher.view"):
            return
        executable = next((path for path in self._launcher_candidates() if path.is_file()), None)
        if not executable:
            if messagebox.askyesno("NEXUS Control Panel", "NEXUS Launcher.exe не найден. Выбрать файл вручную?"):
                self._choose_launcher()
            return
        clean_environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("_PYI_")}
        from nexus_launcher.process_utils import hidden_process_kwargs

        subprocess.Popen([str(executable)], cwd=executable.parent, shell=False, env=clean_environment,
                         **hidden_process_kwargs())
        self.status.set("Launcher started")
        self._update_launcher_status()

    def _poll(self):
        changed = False
        while not self.events.empty():
            key, kind, value = self.events.get_nowait()
            if kind == "network":
                self.network_states[key] = str(value)
                changed = True
            elif kind == "console":
                selected = self._selection(False)
                if selected and self._key(selected[2], selected[3]) == key:
                    at_bottom = float(self.console_text.yview()[1]) >= 0.995
                    self._append_console_line(value)
                    line_count = int(self.console_text.index("end-1c").split(".")[0])
                    if line_count > 7500:
                        self.console_text.delete("1.0", f"{line_count - 7500}.0")
                    if at_bottom:
                        self.console_text.see("end")
            elif kind == "error":
                self.status.set(str(value))
            elif kind == "state":
                changed = True
        if changed:
            self._refresh()
        self.after(100, self._poll)

    def _tick(self):
        now = time.time()
        if now - self._last_user_activity > 45 * 60 or not self.security.validate_session(self.session, touch=False):
            messagebox.showwarning("NEXUS", "Сессия заблокирована. Выполните вход повторно.", parent=self)
            self.security.logout(self.session)
            self.logout_requested = True
            self.destroy()
            return
        if self._last_user_activity > self._last_session_touch:
            self.security.validate_session(self.session, touch=True)
            self._last_session_touch = self._last_user_activity
        selected = self._selection(False)
        if selected:
            controller = self._controller(selected[2], selected[3])
            last_refresh = getattr(controller, "_panel_last_refresh", 0.0)
            if isinstance(controller, PterodactylServerController) and now - last_refresh >= 10:
                controller._panel_last_refresh = now
                threading.Thread(target=controller.refresh, daemon=True).start()
        self._show_selection()
        self.after(1000, self._tick)

    def _close(self):
        running = [
            controller
            for controller in self.controllers.values()
            if controller.process and controller.process.poll() is None
        ]
        if not running:
            self.destroy()
            return
        answer = messagebox.askyesnocancel(
            "NEXUS Control Panel",
            f"Сейчас работают серверы: {len(running)}.\n\n"
            "Да — остановить серверы и выйти.\n"
            "Нет — оставить серверы работать и выйти.\n"
            "Отмена — вернуться в панель.",
        )
        if answer is None:
            return
        if answer:
            for controller in running:
                controller.stop()
            self.status.set("Останавливаю серверы…")
            self.after(250, self._wait_close)
        else:
            self.destroy()

    def _wait_close(self):
        if any(controller.process and controller.process.poll() is None for controller in self.controllers.values()):
            self.after(250, self._wait_close)
        else:
            self.destroy()


def run_app():
    security = SQLiteSecurityStore(SECURITY_DB_FILE)
    while True:
        access = AccessWindow(security)
        access.mainloop()
        if not access.session:
            return
        panel = ControlCenter(security, access.session)
        panel.mainloop()
        if not panel.logout_requested:
            return


if __name__ == "__main__":
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    run_app()
