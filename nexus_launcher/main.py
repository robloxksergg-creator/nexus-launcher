from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from nexus_launcher.launcher_core import MinecraftLauncher
from nexus_launcher.projects import ProjectCatalog
from nexus_launcher.server_status import ping as ping_server
from nexus_launcher.updater import ModpackUpdater

APP_DIR = Path(os.getenv("APPDATA", Path.home())) / ".nexus-launcher"
CONFIG_FILE = APP_DIR / "launcher.json"
PROJECTS_FILE = APP_DIR / "projects.json"
DEFAULT_MANIFEST = "https://89.106.89.198:25509/client/v2.json"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NEXUS Launcher")
        self.geometry("900x560")
        self.minsize(760, 500)
        self.configure(bg="#090d18")
        self.events: queue.Queue = queue.Queue()
        self.config_data = self._load_config()
        self.projects = ProjectCatalog(PROJECTS_FILE).load()
        self._style()
        self._build()
        self.after(100, self._poll)
        threading.Thread(target=self._load_versions, daemon=True).start()

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#090d18")
        style.configure("Card.TFrame", background="#11182a")
        style.configure("TLabel", background="#11182a", foreground="#e8edf7", font=("Segoe UI", 11))
        style.configure("Title.TLabel", background="#090d18", foreground="#ffffff", font=("Segoe UI Semibold", 27))
        style.configure("Muted.TLabel", background="#090d18", foreground="#7e8ca8", font=("Segoe UI", 10))
        style.configure("TEntry", fieldbackground="#0b1120", foreground="#ffffff", insertcolor="#ffffff", padding=9)
        style.configure("TCombobox", fieldbackground="#0b1120", foreground="#ffffff", padding=8)
        style.configure(
            "Accent.TButton",
            background="#6d5dfc",
            foreground="white",
            font=("Segoe UI Semibold", 13),
            padding=(24, 13),
            borderwidth=0,
        )
        style.map("Accent.TButton", background=[("active", "#8377ff"), ("disabled", "#34384c")])
        style.configure("Horizontal.TProgressbar", background="#6d5dfc", troughcolor="#222a3f", borderwidth=0)

    def _build(self):
        header = ttk.Frame(self, padding=(42, 28, 42, 15))
        header.pack(fill="x")
        ttk.Label(header, text="NEXUS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Твой сервер. Твоя сборка. Один клик до игры.", style="Muted.TLabel").pack(anchor="w")

        content = ttk.Frame(self, style="Card.TFrame", padding=32)
        content.pack(fill="both", expand=True, padx=42, pady=(5, 18))
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        self.username = tk.StringVar(value=self.config_data.get("username", ""))
        self.version = tk.StringVar(value=self.config_data.get("version", "1.21.1"))
        self.memory = tk.IntVar(value=self.config_data.get("memory", 4096))
        self.server = tk.StringVar(value=self.config_data.get("server", "play.flux-productions.com"))
        self.manifest_url = tk.StringVar(value=self.config_data.get("manifest_url", DEFAULT_MANIFEST))
        self.auto_update = tk.BooleanVar(value=self.config_data.get("auto_update", True))
        self.status = tk.StringVar(value="Подготавливаю список версий…")

        self.project = tk.StringVar(value=self.config_data.get("project", self.projects[0].id))
        self.server_profile = tk.StringVar(value=self.config_data.get("server_profile", ""))
        project_box = ttk.Combobox(content, state="readonly", values=[item.name for item in self.projects])
        selected = next((index for index, item in enumerate(self.projects) if item.id == self.project.get()), 0)
        project_box.current(selected)
        project_box.bind("<<ComboboxSelected>>", lambda _event: self._select_project(project_box.current()))
        self._field(content, "ПРОЕКТ", project_box, 0, 0)
        self.server_box = ttk.Combobox(content, state="readonly")
        self.server_box.bind("<<ComboboxSelected>>", lambda _event: self._select_server(self.server_box.current()))
        self._field(content, "СЕРВЕР / РЕЖИМ", self.server_box, 0, 1)
        self._field(content, "НИК ИГРОКА", ttk.Entry(content, textvariable=self.username), 1, 0)
        self.version_box = ttk.Combobox(content, textvariable=self.version, state="readonly")
        self.version_box["values"] = (self.version.get(),)
        self._field(content, "ВЕРСИЯ", self.version_box, 1, 1)

        memory_frame = ttk.Frame(content, style="Card.TFrame")
        ttk.Label(memory_frame, textvariable=self.memory).pack(side="right")
        ttk.Scale(memory_frame, from_=2048, to=12288, variable=self.memory).pack(fill="x", expand=True, padx=(0, 10))
        self._field(content, "ОПЕРАТИВНАЯ ПАМЯТЬ, МБ", memory_frame, 2, 0)
        self._select_project(selected, preserve_server=True)

        ttk.Label(content, textvariable=self.status, foreground="#8f9db8").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(20, 8)
        )
        self.progress = ttk.Progressbar(content, mode="determinate")
        self.progress.grid(row=7, column=0, columnspan=2, sticky="ew")
        options = ttk.Frame(content, style="Card.TFrame")
        options.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Checkbutton(options, text="Автоматически обновлять сборку перед запуском", variable=self.auto_update).pack(
            side="left"
        )
        ttk.Button(options, text="Проверить сервер", command=self._check_server).pack(side="right")
        ttk.Button(options, text="Папка игры", command=self._open_game_dir).pack(side="right", padx=8)
        self.play = ttk.Button(content, text="ИГРАТЬ", style="Accent.TButton", command=self._play)
        self.play.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(20, 0))

        ttk.Label(self, text=f"Файлы игры: {APP_DIR / 'game'}", style="Muted.TLabel").pack(
            anchor="w", padx=44, pady=(0, 20)
        )

    def _field(self, parent, label, widget, row, column):
        padding = (0, 14) if column == 0 else (14, 0)
        ttk.Label(parent, text=label, foreground="#8f9db8", font=("Segoe UI Semibold", 9)).grid(
            row=row * 2, column=column, sticky="w", padx=padding, pady=(4, 7)
        )
        widget.grid(row=row * 2 + 1, column=column, sticky="ew", padx=padding, pady=(0, 20))

    def _load_config(self):
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_config(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(
                {
                    "username": self.username.get(),
                    "version": self.version.get(),
                    "memory": int(self.memory.get()),
                    "server": self.server.get(),
                    "manifest_url": self.manifest_url.get(),
                    "auto_update": self.auto_update.get(),
                    "project": self.project.get(),
                    "server_profile": self.server_profile.get(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _selected_project(self):
        return next((item for item in self.projects if item.id == self.project.get()), self.projects[0])

    def _selected_server(self):
        project = self._selected_project()
        return next((item for item in project.servers if item.id == self.server_profile.get()), project.servers[0])

    def _select_project(self, index, preserve_server=False):
        selected = self.projects[index]
        self.project.set(selected.id)
        self.server_box["values"] = [item.name for item in selected.servers]
        server_index = 0
        if preserve_server:
            server_index = next(
                (i for i, item in enumerate(selected.servers) if item.id == self.server_profile.get()), 0
            )
        self.server_box.current(server_index)
        self._select_server(server_index)
        self.status.set(f"Выбран проект {selected.name}")

    def _select_server(self, index):
        selected = self._selected_project().servers[index]
        self.server_profile.set(selected.id)
        self.server.set(selected.address)
        self.manifest_url.set(selected.manifest_url)
        self.version.set(selected.minecraft_version)
        self.status.set(f"{selected.name}: Minecraft {selected.minecraft_version} • {selected.loader}")

    def _instance_dir(self):
        return APP_DIR / "instances" / self.project.get() / self.server_profile.get()

    def _launcher(self, game_dir=None):
        return MinecraftLauncher(
            game_dir or self._instance_dir(),
            lambda text: self.events.put(("status", text)),
            lambda done, total: self.events.put(("progress", done, total)),
        )

    def _load_versions(self):
        try:
            versions = self._launcher().available_versions()
            preferred = "1.21.1"
            if preferred in versions:
                versions.remove(preferred)
                versions.insert(0, preferred)
            self.events.put(("versions", versions))
        except Exception as error:
            self.events.put(("status", f"Нет сети: {error}"))

    def _play(self):
        self._save_config()
        self.play.configure(state="disabled")
        launch_options = {
            "version": self.version.get(),
            "username": self.username.get().strip(),
            "memory": int(self.memory.get()),
            "server": self.server.get().strip(),
            "manifest": self.manifest_url.get().strip(),
            "auto_update": self.auto_update.get(),
            "loader": self._selected_server().loader,
            "loader_version": self._selected_server().loader_version,
            "instance_dir": self._instance_dir(),
        }
        threading.Thread(target=self._launch_worker, args=(launch_options,), daemon=True).start()

    def _open_game_dir(self):
        path = self._instance_dir()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def _check_server(self):
        address = self.server.get().strip() or self.config_data.get("server", "") or "play.flux-productions.com"
        self.status.set("Проверяю сервер…")
        threading.Thread(target=self._server_worker, args=(address,), daemon=True).start()

    def _server_worker(self, address):
        try:
            result = ping_server(address)
            players = result.get("players", {})
            self.events.put(
                ("status", f"Сервер онлайн • {players.get('online', 0)} / {players.get('max', '?')} игроков")
            )
        except Exception as error:
            self.events.put(("status", f"Сервер недоступен: {error}"))

    def _launch_worker(self, options):
        try:
            server_address = options["server"]
            if options["auto_update"] and options["manifest"]:
                self.events.put(("status", "Проверяю обновление сборки…"))
                updater = ModpackUpdater(
                    options["instance_dir"],
                    lambda text: self.events.put(("status", text)),
                    lambda done, total: self.events.put(("bytes_progress", done, total)),
                )
                try:
                    release = updater.update_if_needed(options["manifest"])
                    if release and release.minecraft_server and not server_address:
                        server_address = release.minecraft_server
                        self.events.put(("server", server_address))
                except Exception as update_error:
                    self.events.put(
                        ("status", f"Сервер обновлений недоступен, запускаю локальную сборку: {update_error}")
                    )
            process = self._launcher(options["instance_dir"]).launch(
                options["version"],
                options["username"],
                options["memory"],
                server_address,
                options["loader"],
                options["loader_version"],
            )
            self.events.put(("launched", process.pid))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _poll(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "status":
                self.status.set(event[1])
            elif kind == "progress":
                done, total = event[1:]
                self.progress.configure(maximum=max(total, 1), value=done)
                self.status.set(f"Загрузка файлов: {done} / {total}")
            elif kind == "bytes_progress":
                done, total = event[1:]
                self.progress.configure(maximum=max(total, 1), value=done)
                self.status.set(f"Обновление сборки: {done / 1048576:.1f} / {total / 1048576:.1f} МБ")
            elif kind == "server":
                self.server.set(event[1])
            elif kind == "versions":
                self.version_box["values"] = event[1]
                if self.version.get() not in event[1]:
                    self.version.set(event[1][0])
                self.status.set("Готов к запуску")
            elif kind == "launched":
                self.status.set(f"Minecraft запущен (PID {event[1]})")
                self.play.configure(state="normal")
            elif kind == "error":
                self.play.configure(state="normal")
                self.status.set("Ошибка запуска")
                messagebox.showerror("NEXUS Launcher", event[1])
        self.after(100, self._poll)


if __name__ == "__main__":
    App().mainloop()
