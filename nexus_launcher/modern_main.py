# ruff: noqa: E501 -- QSS selectors are intentionally kept intact for readability.

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import webbrowser
from pathlib import Path

import nexus_launcher.build_channel as build_channel

# An inherited/user-supplied environment variable must never turn a production
# binary into a staging-trusting binary. Only private_main may set build identity.
if not build_channel.STAGING_BUILD:
    os.environ.pop("NEXUS_ENVIRONMENT", None)

from nexus_launcher.curseforge_importer import CurseForgeImporter
from nexus_launcher.instance_ui import InstancePage
from nexus_launcher.launcher_core import MinecraftLauncher
from nexus_launcher.nexus_account import AccountError, NexusAccountClient, NexusProfile
from nexus_launcher.pack_options import ensure_visual_defaults
from nexus_launcher.platform_support import app_data_dir, find_java_21, open_in_file_manager
from nexus_launcher.process_utils import hidden_process_kwargs
from nexus_launcher.projects import ProjectCatalog, ServerProfile
from PySide6.QtCore import QEasingCurve, QObject, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplashScreen,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from nexus_launcher.runtime_settings import validate_java, validate_storage
from nexus_launcher.self_update import CURRENT_VERSION, try_startup_update
from nexus_launcher.server_status import ping as ping_server
from nexus_launcher.servers_dat import ensure_server
from nexus_launcher.updater import ModpackUpdater
from nexus_launcher.user_instances import InstanceService

APP_DIR = app_data_dir()
CONFIG_FILE = APP_DIR / "launcher.json"
PROJECTS_FILE = APP_DIR / "projects.json"
WINDOWS_APP_ID = "com.nexus.launcher"

# Private UI spacing grid. All layout geometry below is based on these tokens.
SPACE_4 = 4
SPACE_8 = 8
SPACE_12 = 12
SPACE_16 = 16
SPACE_20 = 20
SPACE_24 = 24
SPACE_32 = 32
NAV_HEIGHT = 48
NAV_ICON_BOX = 28
MENU_ITEM_HEIGHT = 52
MENU_ICON_BOX = 28


def resource(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / name


_SPRITE_PIXMAP = None
_SPRITE_ICONS = {}
_NAV_SPRITE_PIXMAP = None
_NAV_SPRITE_ICONS = {}
_NAV_ICON_NAMES = ("home", "worlds", "news", "mods", "settings", "profile")


def nexus_button_icon(index: int) -> QIcon:
    """Return a normalized private action icon."""
    if index in _SPRITE_ICONS:
        return _SPRITE_ICONS[index]
    if index < 0 or index > 8:
        return QIcon()
    icon = QIcon(str(resource(f"nexus-action-{index}.png")))
    _SPRITE_ICONS[index] = icon
    return icon


def nexus_nav_icon(index: int) -> QIcon:
    """Return a visually normalized private navigation icon."""
    if index in _NAV_SPRITE_ICONS:
        return _NAV_SPRITE_ICONS[index]
    if index < 0 or index >= len(_NAV_ICON_NAMES):
        return QIcon()
    icon = QIcon(str(resource(f"nexus-nav-{_NAV_ICON_NAMES[index]}.png")))
    _NAV_SPRITE_ICONS[index] = icon
    return icon


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def detect_java_label(preferred: str = "") -> str:
    java = preferred or find_java_21()
    if not java:
        return "Java не найдена"
    try:
        result = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=3, **hidden_process_kwargs())
        first_line = (result.stderr or result.stdout).splitlines()[0]
        match = re.search(r'"([^" ]+)', first_line)
        return f"Java {match.group(1)} ✓" if match else "Java найдена"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "Java найдена"


class Bridge(QObject):
    status = Signal(str)
    progress = Signal(int, int)
    finished = Signal(int)
    game_exited = Signal(int)
    failed = Signal(str)
    server_checked = Signal(str, bool, int, int)
    account_ready = Signal(object)
    account_failed = Signal(str)
    repair_done = Signal(str)
    build_access_ready = Signal(object)
    updater_progress = Signal(object)


from nexus_launcher.themed_dialog import NexusDialog


class LoginDialog(NexusDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Вход в NEXUS")
        self.setMinimumSize(460, 490)
        self.resize(480, 510)
        self.setObjectName("settingsDialog")
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 26)
        root.setSpacing(14)
        title = QLabel("Единый аккаунт NEXUS")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        hint = QLabel("Используйте ник или почту и пароль с сайта NEXUS.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.identifier = QLineEdit()
        self.identifier.setPlaceholderText("Ник или электронная почта")
        root.addWidget(self.identifier)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        from nexus_launcher.password_visibility import PasswordVisibilityButton
        self.password_visibility = PasswordVisibilityButton(self.password)
        self.password.setPlaceholderText("Пароль")
        self.password.returnPressed.connect(self.accept)
        root.addWidget(self.password)
        self.mfa_code = QLineEdit()
        self.mfa_code.setPlaceholderText("Код 2FA, если защита включена")
        self.mfa_code.setAccessibleName("Код второго фактора")
        self.mfa_code.setMaxLength(35)
        self.mfa_code.setEchoMode(QLineEdit.Password)
        self.mfa_code.returnPressed.connect(self.accept)
        root.addWidget(self.mfa_code)
        self.mfa_recovery = QCheckBox("Использовать резервный код")
        self.mfa_recovery.toggled.connect(lambda checked: self.mfa_code.clear())
        root.addWidget(self.mfa_recovery)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        self.error.setWordWrap(True)
        root.addWidget(self.error)
        root.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        login = QPushButton("Войти")
        login.setObjectName("primary")
        login.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(login)
        root.addLayout(buttons)

    def second_factor(self):
        value = self.mfa_code.text().strip()
        self.mfa_code.clear()
        return ('', value) if self.mfa_recovery.isChecked() else (value, '')

    def credentials(self):
        return self.identifier.text().strip(), self.password.text()


class SettingsDialog(NexusDialog):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.setWindowTitle("Параметры игры")
        self.setFixedSize(620, 680)
        self.setObjectName("settingsDialog")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(8)
        title = QLabel("Параметры запуска")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        root.addWidget(QLabel("Оперативная память"))
        row = QHBoxLayout()
        self.memory = QSlider(Qt.Horizontal)
        self.memory.setRange(2048, 16384)
        self.memory.setSingleStep(512)
        self.memory.setValue(int(config.get("memory", 4096)))
        self.memory_text = QLabel(f"{self.memory.value()} МБ")
        self.memory_text.setObjectName("valueBadge")
        self.memory.valueChanged.connect(lambda value: self.memory_text.setText(f"{value} МБ"))
        row.addWidget(self.memory)
        row.addWidget(self.memory_text)
        root.addLayout(row)
        hint = QLabel("Рекомендуется 4096–8192 МБ для больших сборок")
        hint.setObjectName("muted")
        root.addWidget(hint)
        root.addWidget(QLabel("Размер окна"))
        sizes = QHBoxLayout()
        self.width = QLineEdit(str(config.get("width", "авто")))
        self.height = QLineEdit(str(config.get("height", "авто")))
        sizes.addWidget(self.width)
        sizes.addWidget(QLabel("×"))
        sizes.addWidget(self.height)
        root.addLayout(sizes)
        self.fullscreen = QCheckBox("Полноэкранный режим")
        self.fullscreen.setChecked(bool(config.get("fullscreen", False)))
        root.addWidget(self.fullscreen)
        self.auto_join = QCheckBox("Автоматический вход на сервер")
        self.auto_join.setChecked(bool(config.get("auto_join", True)))
        root.addWidget(self.auto_join)
        root.addWidget(QLabel("Дополнительные аргументы JVM"))
        self.jvm = QLineEdit(config.get("jvm_args", ""))
        self.jvm.setPlaceholderText("Если не знаете, оставьте пустым")
        root.addWidget(self.jvm)
        self.java_path = QLineEdit(config.get("java_path", ""))
        self.java_path.setPlaceholderText("Автоматический выбор Java по требованиям сборки")
        self.install_root = QLineEdit(config.get("install_root", ""))
        self.install_root.setPlaceholderText(str(APP_DIR))
        for label, field, browse in (
            ("Java — путь к java.exe/java", self.java_path, self._browse_java),
            ("Папка сборок", self.install_root, self._browse_install_root),
        ):
            root.addWidget(QLabel(label))
            path_row = QHBoxLayout()
            path_row.addWidget(field)
            button = QPushButton("Обзор…")
            button.clicked.connect(browse)
            path_row.addWidget(button)
            root.addLayout(path_row)
        note = QLabel(
            "В папке создаются instances и user-instances. Смена папки — после перезапуска лаунчера. Старые сборки не переносятся. Очистите поле для значения по умолчанию."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        apply = QPushButton("Применить")
        apply.setObjectName("primary")
        apply.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        root.addLayout(buttons)

    def values(self):
        return {
            "java_path": self.java_path.text().strip(),
            "install_root": self.install_root.text().strip(),
            "memory": self.memory.value(),
            "width": self.width.text(),
            "height": self.height.text(),
            "fullscreen": self.fullscreen.isChecked(),
            "auto_join": self.auto_join.isChecked(),
            "jvm_args": self.jvm.text(),
        }

    def _browse_java(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Выберите Java 21", self.java_path.text(), "Java (java.exe javaw.exe java);;Все файлы (*)"
        )
        if filename:
            self.java_path.setText(filename)

    def _browse_install_root(self):
        directory = QFileDialog.getExistingDirectory(self, "Папка сборок", self.install_root.text() or str(APP_DIR))
        if directory:
            self.install_root.setText(directory)

    def accept(self):
        java = self.java_path.text().strip()
        folder = self.install_root.text().strip()
        if java and Path(java).name.lower() == "javaw.exe":
            java = str(Path(java).with_name("java.exe"))
            self.java_path.setText(java)
        if java and (not Path(java).is_absolute() or not Path(java).is_file()):
            QMessageBox.warning(self, "Java", "Выберите существующий исполняемый файл Java по полному пути.")
            return
        if folder and (not Path(folder).is_absolute() or (Path(folder).exists() and not Path(folder).is_dir())):
            QMessageBox.warning(self, "Папка сборок", "Укажите полный путь к папке, а не к файлу.")
            return
        try:
            if java:
                self.java_path.setText(validate_java(java))
            validate_storage(folder or str(APP_DIR))
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Настройки путей", str(error))
            return
        super().accept()


class OptionalModsDialog(NexusDialog):
    def __init__(self, parent, optional_catalog=None, optional_selections=None):
        super().__init__(parent)
        self.setWindowTitle("Опциональные моды")
        self.setFixedSize(620, 620)
        self.setObjectName("settingsDialog")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Опциональные моды")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        description = QLabel(
            "Выберите дополнительные моды для текущего мира. Изменения применятся при следующем запуске."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        root.addWidget(description)

        self.optional_toggles = {}
        optional_catalog = optional_catalog or []
        optional_selections = optional_selections or {}
        if not optional_catalog:
            empty = QLabel("Для этой сборки опциональные моды пока не опубликованы.")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            root.addWidget(empty)
        for item in optional_catalog:
            mod_id = str(item.get("id", "")).lower()
            toggle = QCheckBox(str(item.get("name", mod_id)))
            toggle.setChecked(bool(optional_selections.get(mod_id, item.get("defaultEnabled", False))))
            self.optional_toggles[mod_id] = toggle
            root.addWidget(toggle)
            size = int(item.get("downloadSize", 0)) / 1048576
            details = QLabel(
                f"{item.get('description', '')}\nКатегория: {item.get('category', 'other')}  •  "
                f"Нагрузка: {item.get('performanceImpact', '—')}  •  {size:.1f} МБ"
            )
            details.setObjectName("muted")
            details.setWordWrap(True)
            root.addWidget(details)
        root.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Отмена")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        apply_button = QPushButton("Применить")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(apply_button)
        root.addLayout(buttons)

    def values(self):
        return {key: toggle.isChecked() for key, toggle in self.optional_toggles.items()}


class ServerCard(QPushButton):
    def __init__(self, server: ServerProfile, accent: str, image: QPixmap):
        super().__init__()
        self.server = server
        self.accent = QColor(accent)
        self.cover = image
        self.hovered = False
        self.selected = False
        self.online = None
        self.access_mode = "OPEN"
        self.access_allowed = True
        self.hover_expansion = False
        self.compact_height = 250
        self.expanded_height_limit = 360
        self.height_animation = QVariantAnimation(self)
        self.height_animation.setDuration(220)
        self.height_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.height_animation.valueChanged.connect(self._apply_animated_height)
        self.setMinimumSize(410, 250)
        self.setMaximumSize(520, 300)
        self.setSizePolicy(self.sizePolicy().Policy.Expanding, self.sizePolicy().Policy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;border:0;")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)
        self.card_shadow = shadow

    def configure_hover_expansion(self, compact_height=190, expanded_height_limit=360):
        """Expand in the layout on hover and reveal the complete cover artwork."""
        self.hover_expansion = True
        self.compact_height = int(compact_height)
        self.expanded_height_limit = int(expanded_height_limit)
        self.setFixedHeight(self.compact_height)

    def _expanded_height(self):
        if self.cover.isNull() or self.cover.width() <= 0:
            return min(self.expanded_height_limit, self.compact_height + 100)
        # Match the card to the source aspect ratio so KeepAspectRatio reveals
        # the entire banner instead of cropping its top and bottom.
        available_width = max(1, self.width() - 6)
        aspect_height = round(available_width * self.cover.height() / self.cover.width()) + 6
        return max(self.compact_height + 70, min(self.expanded_height_limit, aspect_height))

    def _animate_height(self, target):
        if not self.hover_expansion:
            return
        self.height_animation.stop()
        self.height_animation.setStartValue(self.height())
        self.height_animation.setEndValue(int(target))
        self.height_animation.start()

    def _apply_animated_height(self, value):
        self.setFixedHeight(int(value))
        self.updateGeometry()

    def enterEvent(self, event):
        self.hovered = True
        self._animate_height(self._expanded_height())
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self._animate_height(self.compact_height)
        self.update()
        super().leaveEvent(event)

    def set_selected(self, selected):
        self.selected = selected
        self.card_shadow.setBlurRadius(34 if selected else 28)
        self.card_shadow.setOffset(0, 8 if selected else 10)
        self.card_shadow.setColor(QColor(37, 134, 255, 58) if selected else QColor(0, 0, 0, 120))
        self.update()

    def set_online(self, online):
        self.online = online
        self.update()

    def set_access(self, mode, allowed):
        self.access_mode = str(mode or "OPEN").upper()
        self.access_allowed = bool(allowed)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.setClipPath(path)
        if not self.cover.isNull():
            scale_mode = (
                Qt.KeepAspectRatio
                if self.hover_expansion and self.height() > self.compact_height + 8
                else Qt.KeepAspectRatioByExpanding
            )
            scaled = self.cover.scaled(self.size(), scale_mode, Qt.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        gradient = QLinearGradient(0, 45, 0, self.height())
        gradient.setColorAt(0, QColor(5, 10, 20, 12))
        gradient.setColorAt(0.55, QColor(8, 13, 24, 80))
        gradient.setColorAt(1, QColor(6, 10, 19, 245))
        painter.fillRect(self.rect(), gradient)
        painter.setClipping(False)
        active = self.selected or self.hovered
        active_border = QColor(34, 211, 238, 140) if self.selected else QColor(34, 211, 238, 184)
        painter.setPen(QPen(active_border if active else QColor("#34425d"), 1))
        painter.drawRoundedRect(rect, 16, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(16, 25, 39, 225))
        painter.drawRoundedRect(QRectF(self.width() - 103, 16, 82, 29), 10, 10)
        painter.setPen(QColor("#d8eaff"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(self.width() - 103, 16, 82, 29), Qt.AlignCenter, server_badge(self.server))
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 16, QFont.Bold))
        painter.drawText(22, self.height() - 48, self.server.name)
        coming_soon = self.server.visibility == "coming_soon"
        restricted = self.access_mode in {"MAINTENANCE", "CLOSED"}
        status_text = (
            ("Техработы" if self.access_mode == "MAINTENANCE" else "Закрыта")
            if restricted
            else (
                "Скоро"
                if coming_soon
                else ("Проверка…" if self.online is None else ("Онлайн" if self.online else "Недоступен"))
            )
        )
        painter.setPen(
            QColor("#fbbf24")
            if coming_soon or restricted
            else (QColor("#22c55e") if self.online else QColor("#94a3b8"))
        )
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(22, self.height() - 24, f"●  {status_text}     {self.server.loader.upper()}")


class PrivateBackground(QWidget):
    """Private preview canvas; keeps the public launcher layout untouched."""

    def __init__(self, artwork: QPixmap):
        super().__init__()
        self.artwork = artwork

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self.artwork.isNull():
            scaled = self.artwork.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        painter.fillRect(self.rect(), QColor(3, 9, 20, 198))


def server_badge(server: ServerProfile) -> str:
    return server.minecraft_version


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.drag_position = None
        self.setFixedHeight(76)
        self.setObjectName("topbar")
        bar = QHBoxLayout(self)
        bar.setContentsMargins(24, 0, 14, 0)
        bar.setSpacing(12)
        menu = QPushButton("▦")
        menu.setObjectName("squareButton")
        menu.setFixedSize(42, 42)
        menu.clicked.connect(window.show_catalog)
        bar.addWidget(menu)
        brand = QLabel("NEXUS")
        brand.setObjectName("brand")
        bar.addWidget(brand)
        bar.addStretch()
        window.profile = QPushButton("◆  Войти")
        window.profile.setObjectName("profileButton")
        window.profile.clicked.connect(window._profile_menu)
        bar.addWidget(window.profile)
        controls = (
            ("", 7, "Свернуть", window.showMinimized),
            ("", 1, "Развернуть", window._toggle_max),
            ("", 6, "Закрыть", window.close),
        )
        for text, icon_index, tooltip, action in controls:
            button = QPushButton(text)
            button.setObjectName("windowButton")
            button.setProperty("closeControl", icon_index == 6)
            button.setFixedSize(44, 44)
            button.setIcon(nexus_button_icon(icon_index))
            button.setIconSize(QSize(30, 30))
            button.setToolTip(tooltip)
            button.clicked.connect(action)
            bar.addWidget(button)
            if icon_index == 1:
                window.maximize_button = button

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_position is not None and event.buttons() & Qt.LeftButton and not self.window.isMaximized():
            self.window.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, _event):
        self.drag_position = None

    def mouseDoubleClickEvent(self, _event):
        self.window._toggle_max()


class NavButton(QPushButton):
    """Single grid-aligned component for every private sidebar entry."""

    def __init__(self, text, icon, active=False):
        super().__init__(text)
        self.active = active
        self.setIcon(icon)
        self.setFixedHeight(NAV_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("background:transparent;border:0;padding:0;")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        hovered = self.underMouse()
        if self.active:
            fill = QLinearGradient(0, 0, self.width(), 0)
            fill.setColorAt(0, QColor(16, 95, 176, 155))
            fill.setColorAt(1, QColor(26, 120, 225, 55))
            painter.setBrush(fill)
            painter.setPen(QPen(QColor("#267bd1"), 1))
        elif hovered:
            painter.setBrush(QColor(25, 91, 158, 72))
            painter.setPen(QPen(QColor(38, 96, 153, 150), 1))
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(Qt.transparent, 1))
        painter.drawRoundedRect(rect, SPACE_8, SPACE_8)

        icon_rect = QRectF(SPACE_20, (NAV_HEIGHT - NAV_ICON_BOX) / 2, NAV_ICON_BOX, NAV_ICON_BOX)
        self.icon().paint(painter, icon_rect.toRect(), Qt.AlignCenter)
        text_x = SPACE_20 + NAV_ICON_BOX + SPACE_12
        painter.setPen(QColor("#ffffff") if self.active or hovered else QColor("#afbdd0"))
        font = QFont("Segoe UI", 11)
        font.setWeight(QFont.DemiBold if self.active else QFont.Normal)
        painter.setFont(font)
        painter.drawText(
            QRectF(text_x, 0, self.width() - text_x - SPACE_16, NAV_HEIGHT), Qt.AlignLeft | Qt.AlignVCenter, self.text()
        )


class ProfileTopButton(QPushButton):
    """Grid-aligned account trigger in the private title bar."""

    def __init__(self, text):
        super().__init__(text)
        self.setFixedSize(200, 48)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("background:transparent;border:0;padding:0;")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setBrush(QColor(15, 29, 49, 230) if self.underMouse() else QColor(10, 18, 31, 218))
        painter.setPen(QPen(QColor("#3b628b") if self.underMouse() else QColor("#314967"), 1))
        painter.drawRoundedRect(rect, SPACE_12, SPACE_12)
        icon_rect = QRectF(SPACE_12, SPACE_8, SPACE_32, SPACE_32)
        self.icon().paint(painter, icon_rect.toRect(), Qt.AlignCenter)
        painter.setPen(QColor("#f2f7fd"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(52, 0, 116, 48), Qt.AlignLeft | Qt.AlignVCenter, self.text())
        painter.setPen(QColor("#8ea2bb"))
        painter.setFont(QFont("Segoe UI", 13))
        painter.drawText(QRectF(172, 0, 16, 48), Qt.AlignCenter, "⌄")


class ProfileMenuItem(QPushButton):
    """Shared 52 px row used by every profile dropdown action."""

    def __init__(self, text, icon, prominent=False):
        super().__init__(text)
        self.prominent = prominent
        self.setIcon(icon)
        self.setFixedHeight(MENU_ITEM_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("background:transparent;border:0;padding:0;")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        hovered = self.underMouse()
        if self.prominent or hovered:
            painter.setBrush(QColor(19, 43, 75, 220) if self.prominent else QColor(27, 63, 105, 155))
            painter.setPen(QPen(QColor("#315b86") if self.prominent else QColor(49, 91, 134, 175), 1))
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(Qt.transparent, 1))
        painter.drawRoundedRect(rect, 10, 10)
        icon_rect = QRectF(SPACE_16, (MENU_ITEM_HEIGHT - MENU_ICON_BOX) / 2, MENU_ICON_BOX, MENU_ICON_BOX)
        self.icon().paint(painter, icon_rect.toRect(), Qt.AlignCenter)
        text_x = SPACE_16 + MENU_ICON_BOX + SPACE_12
        painter.setPen(QColor("#f4f8fd") if self.prominent or hovered else QColor("#dce6f3"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(
            QRectF(text_x, 0, self.width() - text_x - SPACE_16, MENU_ITEM_HEIGHT),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.text(),
        )


class ProfileMenuDivider(QWidget):
    """One-pixel divider with an exact 8 px margin on both sides."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(17)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#213b59"), 1))
        painter.drawLine(0, SPACE_8, self.width(), SPACE_8)


class PrivateTitleBar(TitleBar):
    def __init__(self, window):
        QFrame.__init__(self)
        self.window = window
        self.drag_position = None
        self.setFixedHeight(82)
        self.setObjectName("privateTitlebar")
        bar = QHBoxLayout(self)
        bar.setContentsMargins(28, 12, 12, 8)
        bar.addStretch()
        window.profile = ProfileTopButton("Войти")
        window.profile.setIcon(nexus_nav_icon(5))
        window.profile.setObjectName("profileButton")
        window.profile.clicked.connect(window._profile_menu)
        bar.addWidget(window.profile)
        for text, action in (("—", window.showMinimized), ("□", window._toggle_max), ("×", window.close)):
            button = QPushButton(text)
            button.setObjectName("windowButton")
            button.setProperty("closeControl", text == "×")
            button.setFixedSize(44, 44)
            button.clicked.connect(action)
            bar.addWidget(button)
            if text == "□":
                window.maximize_button = button
                button.setToolTip("Развернуть")


class ProfilePopup(QFrame):
    """Large account popover used by the private launcher preview."""

    def __init__(self, launcher):
        super().__init__(launcher, Qt.Popup | Qt.FramelessWindowHint)
        self.launcher = launcher
        self.setObjectName("profilePopup")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(440)
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_16, SPACE_16, SPACE_16, SPACE_16)
        root.setSpacing(0)

        account = QFrame()
        account.setObjectName("profilePopupAccount")
        account.setFixedHeight(96)
        account_layout = QHBoxLayout(account)
        account_layout.setContentsMargins(SPACE_16, SPACE_16, SPACE_16, SPACE_16)
        account_layout.setSpacing(SPACE_12)
        avatar = QLabel()
        avatar.setObjectName("profilePopupAvatar")
        avatar.setFixedSize(56, 56)
        avatar.setAlignment(Qt.AlignCenter)
        if not launcher.profile.icon().isNull():
            avatar.setPixmap(launcher.profile.icon().pixmap(40, 40))
        else:
            avatar.setPixmap(nexus_nav_icon(5).pixmap(40, 40))
        account_layout.addWidget(avatar)
        identity = QVBoxLayout()
        identity.setSpacing(SPACE_4)
        profile = launcher.account_profile
        name = profile.minecraft_nick if profile else "Войдите в NEXUS"
        title = QLabel(f"Профиль: {name}")
        title.setObjectName("profilePopupTitle")
        identity.addWidget(title)
        email = QLabel(profile.email if profile else "Войдите в аккаунт NEXUS")
        email.setObjectName("profilePopupEmail")
        identity.addWidget(email)
        account_layout.addLayout(identity, 1)
        root.addWidget(account)
        root.addWidget(self._divider())

        if profile:
            root.addWidget(
                self._action("Открыть профиль", nexus_nav_icon(5), launcher._open_web_profile, prominent=True)
            )
            root.addWidget(self._action("Выйти из аккаунта", nexus_button_icon(3), launcher._logout_account))
        else:
            root.addWidget(
                self._action("Войти в аккаунт NEXUS", nexus_nav_icon(5), launcher._login_account, prominent=True)
            )

        root.addWidget(self._divider())
        root.addWidget(self._action("Настройки", nexus_nav_icon(4), launcher._settings))
        root.addWidget(self._action("Проверить файлы сборки", nexus_button_icon(8), launcher._repair_pack))
        root.addWidget(self._divider())
        root.addWidget(self._action("Папка игры", nexus_button_icon(1), launcher._open_folder))

        self.setStyleSheet("""
            QFrame#profilePopup { background:transparent; border:0; }
            QFrame#profilePopupAccount { background:rgba(9,26,48,205); border:1px solid #294d74; border-radius:13px; }
            QLabel#profilePopupAvatar { background:rgba(9,24,44,230); border:1px solid #315b86; border-radius:12px; }
            QLabel#profilePopupTitle { color:#f3f7fd; font-size:18px; font-weight:600; }
            QLabel#profilePopupEmail { color:#8294ad; font-size:14px; }
        """)

    def paintEvent(self, event):
        # A Qt.Popup is a separate native window. On Windows a stylesheet-only
        # translucent background can be skipped by the compositor, leaving the
        # menu controls floating over the launcher. Paint the shell explicitly.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shell = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor(49, 91, 134, 235), 1.4))
        painter.setBrush(QColor(4, 13, 27, 252))
        painter.drawRoundedRect(shell, 16, 16)
        painter.end()

    def _action(self, text, icon, callback, prominent=False):
        button = ProfileMenuItem(text, icon, prominent)
        button.clicked.connect(lambda: self._run(callback))
        return button

    def _divider(self):
        return ProfileMenuDivider()

    def _run(self, callback):
        self.close()
        callback()


class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setWindowTitle("NEXUS Launcher")
        self.setWindowIcon(QIcon(str(resource("icon.png"))))
        # The redesigned launcher graduated from private preview in 0.9.14.
        # Keep an opt-out for diagnostics instead of requiring a private-only
        # entry point to enable the production interface.
        self.private_ui = os.environ.get("NEXUS_PRIVATE_UI", "1") != "0"
        self._configure_window_for_screen()
        self.config = load_config()
        # Keep a stable root until restart, including background import workers.
        self._storage_root = Path(self.config.get("install_root") or APP_DIR).resolve()
        self.account_client = NexusAccountClient()
        self.account_profile: NexusProfile | None = None
        self.game_process = None
        self._launch_lock = threading.Lock()
        self.stop_requested = False
        self._launch_server = None
        self.projects = ProjectCatalog(PROJECTS_FILE).load()
        self.instance_service = InstanceService(self._storage_root / "user-instances")
        self.current_user_instance_id = ""
        self.current_server = next((server for project in self.projects for server in project.servers), None)
        self.bridge = Bridge()
        self.bridge.status.connect(self._set_status)
        self.bridge.progress.connect(self._progress)
        self.bridge.finished.connect(self._launched)
        self.bridge.game_exited.connect(self._game_exited)
        self.bridge.failed.connect(self._failed)
        self.bridge.server_checked.connect(self._server_checked)
        self.bridge.account_ready.connect(self._account_ready)
        self.bridge.account_failed.connect(self._account_failed)
        self.bridge.repair_done.connect(self._repair_done)
        self.bridge.build_access_ready.connect(self._build_access_ready)
        self.server_cards = {}
        self.server_states = {}
        self.build_access = {
            "main": {
                "mode": "MAINTENANCE",
                "allowed": False,
                "message": "GEARMORPH временно доступен только технической администрации.",
            },
        }
        self._build()
        self._style()
        self.show_catalog()
        self._check_servers()
        threading.Thread(target=self._restore_account_worker, daemon=True).start()
        threading.Thread(target=self._refresh_build_access_worker, daemon=True).start()

    def _configure_window_for_screen(self):
        """Fit the launcher to the logical desktop, including Windows DPI scaling."""
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        available_width = available.width() if available else 1500
        available_height = available.height() if available else 900
        self.compact_ui = os.environ.get("NEXUS_COMPACT_UI") == "1" or available_width < 1280 or available_height < 760
        preferred_width = 1500 if self.private_ui else 1200
        preferred_height = 900 if self.private_ui else 760
        width = min(preferred_width, max(900, available_width - 24))
        height = min(preferred_height, max(560, available_height - 24))
        self.setMinimumSize(min(920, width), min(560, height))
        self.resize(width, height)
        if available:
            self.move(
                available.x() + max(0, (available_width - width) // 2),
                available.y() + max(0, (available_height - height) // 2),
            )

    def _private_style(self):
        self.setStyleSheet("""
            QMainWindow { background:#030914; }
            QWidget { background:transparent; color:#eef6ff; font-family:'Segoe UI'; font-size:14px; }
            QFrame#privateSidebar { background:rgba(3,8,18,238); border-right:1px solid rgba(30,49,74,220); }
            QFrame#privateTitlebar { background:rgba(3,8,18,118); }
            QLabel#privateLogo { color:#f5f9ff; font-family:'Georgia'; font-size:31px; font-weight:700; letter-spacing:4px; }
            QLabel#privateLogoSub { color:#7894b8; font-size:10px; letter-spacing:5px; }
            QLabel#privateWelcome { color:#a8b6c9; font-size:18px; }
            QLabel#privateHero { color:white; font-family:'Georgia'; font-size:48px; font-weight:600; letter-spacing:4px; }
            QLabel#privateSection { color:#7894b8; font-size:10px; font-weight:700; letter-spacing:3px; }
            QLabel#muted { color:#8495ae; }
            QPushButton { background:#0d1726; border:1px solid #1e314a; border-radius:10px; padding:10px 16px; color:#edf5ff; outline:none; }
            QPushButton:hover { background:#182a43; border-color:#398ee9; }
            QPushButton:focus { outline:none; }
            QPushButton:disabled { background:#101827; border-color:#233249; color:#66778e; }
            QPushButton#communityButton { background:rgba(10,22,38,175); border:1px solid #1e314a; border-radius:8px; padding:6px; color:#8da0b8; font-size:11px; }
            QPushButton#communityButton:hover { color:#f4f7fc; border-color:#2586ff; background:rgba(22,139,210,45); }
            QPushButton#windowButton { padding:0; background:transparent; border:0; font-size:18px; }
            QPushButton#windowButton:hover { background:rgba(47,93,151,100); }
            QPushButton#windowButton[closeControl="true"]:hover { background:rgba(239,68,68,130); }
            QFrame#detailsPanel { background:rgba(5,12,24,224); border:1px solid rgba(78,126,181,105); border-radius:18px; }
            QFrame#metaBox { background:rgba(11,25,44,205); border:1px solid rgba(65,112,168,90); border-radius:12px; }
            QPushButton#playLarge { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #087fb8,stop:.55 #176ed4,stop:1 #264fd4); border:1px solid #3ea6ff; border-radius:11px; font-size:16px; font-weight:750; letter-spacing:1px; color:white; padding:0 16px; }
            QPushButton#playLarge:hover { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0a93d2,stop:.55 #2384ed,stop:1 #3764ec); }
            QPushButton#secondaryButton { background:rgba(6,14,26,205); border:1px solid rgba(79,120,169,110); border-radius:11px; color:#d7e2f0; font-size:15px; font-weight:650; letter-spacing:1px; padding:0 16px; }
            QPushButton#secondaryButton:hover { background:rgba(20,42,70,220); border-color:#398ee9; color:#ffffff; }
            QFrame#launcherFooter { background:rgba(3,9,19,218); border:1px solid rgba(57,94,137,75); border-radius:12px; }
            QScrollArea { border:0; background:transparent; }
            QScrollBar:vertical { background:rgba(5,12,23,180); width:9px; margin:2px; border:0; border-radius:4px; }
            QScrollBar::handle:vertical { background:#294a70; min-height:48px; border-radius:4px; }
            QScrollBar::handle:vertical:hover { background:#3479bd; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; background:transparent; border:0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
            QProgressBar { background:#17263b; border:0; border-radius:4px; height:8px; }
            QProgressBar::chunk { background:#2196f3; border-radius:4px; }
            QLineEdit,QComboBox { background:#101c2d; border:1px solid #354f70; border-radius:8px; padding:10px; }
            QDialog#settingsDialog { background:#07101e; }
        """)

    def _build_private(self):
        canvas = PrivateBackground(QPixmap(str(resource("nexus-private-background.png"))))
        self.setCentralWidget(canvas)
        root = QHBoxLayout(canvas)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._private_sidebar())
        main = QVBoxLayout()
        main.setSpacing(0)
        main.addWidget(PrivateTitleBar(self))
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        self.catalog = self._private_catalog_page()
        self.detail = None
        self.pages.addWidget(self.catalog)
        self.instances_page = InstancePage(self.instance_service, self)
        self.instances_page.launch_requested.connect(self._launch_user_instance)
        self.pages.addWidget(self.instances_page)
        root.addLayout(main, 1)
        self.play = self.catalog_play
        self.progress = self.catalog_progress
        self.status = self.catalog_status

    def _private_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("privateSidebar")
        sidebar.setFixedWidth(210 if self.compact_ui else 250)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(SPACE_20, SPACE_32, SPACE_20, SPACE_24)
        layout.setSpacing(SPACE_8)
        logo = QLabel("◇  NEXUS")
        logo.setObjectName("privateLogo")
        layout.addWidget(logo)
        logo_sub = QLabel("L A U N C H E R")
        logo_sub.setObjectName("privateLogoSub")
        logo_sub.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(logo_sub)
        layout.addSpacing(SPACE_32)
        items = [
            ("Главная", 0, "active", self.show_catalog),
            ("Миры", 1, "", self.show_catalog),
            ("Сборки", 3, "", self.show_instances),
            ("Новости", 2, "", lambda: self._private_notice("Новости")),
            ("Моды", 3, "", lambda: self._private_notice("Моды")),
            ("Настройки", 4, "", self._settings),
            ("Профиль", 5, "", self._profile_menu),
        ]
        for text, icon_index, state, action in items:
            button = NavButton(text, nexus_nav_icon(icon_index), active=bool(state))
            button.clicked.connect(action)
            layout.addWidget(button)
        layout.addStretch()
        community = QLabel("СООБЩЕСТВО")
        community.setObjectName("privateSection")
        layout.addWidget(community)
        links = QHBoxLayout()
        links.setSpacing(7)
        for label in ("Discord", "TG", "VK"):
            button = QPushButton(label)
            button.setObjectName("communityButton")
            button.setFixedHeight(34)
            button.setToolTip(label)
            links.addWidget(button)
        layout.addLayout(links)
        return sidebar

    def _private_notice(self, section):
        QMessageBox.information(self, "NEXUS Launcher", f"Раздел «{section}» пока готовится для приватной версии.")

    def _private_server_details_panel(self):
        panel = QFrame()
        panel.setObjectName("detailsPanel")
        box = QVBoxLayout(panel)
        panel.setMinimumHeight(408 if self.compact_ui else 536)
        box.setContentsMargins(
            20 if self.compact_ui else 28,
            18 if self.compact_ui else 26,
            20 if self.compact_ui else 28,
            18 if self.compact_ui else 24,
        )
        box.setSpacing(7 if self.compact_ui else 12)
        eyebrow = QLabel("ВЫБРАННЫЙ МИР")
        eyebrow.setObjectName("privateSection")
        box.addWidget(eyebrow)
        self.details_title = QLabel()
        self.details_title.setWordWrap(True)
        self.details_title.setStyleSheet(
            f"font-family:'Georgia';font-size:{24 if self.compact_ui else 29}px;font-weight:650;color:#f4f7fc;"
        )
        box.addWidget(self.details_title)
        self.details_status = QLabel("●  ПРОВЕРКА СЕРВЕРА")
        self.details_status.setWordWrap(True)
        self.details_status.setStyleSheet("color:#8da0b8;font-size:11px;font-weight:650;letter-spacing:1px;")
        box.addWidget(self.details_status)
        metadata = QGridLayout()
        metadata.setSpacing(7 if self.compact_ui else 10)
        version_box, self.details_version = self._metadata_item("ВЕРСИЯ MINECRAFT")
        loader_box, self.details_loader = self._metadata_item("ЗАГРУЗЧИК")
        players_box, self.details_players = self._metadata_item("ИГРОКИ ОНЛАЙН")
        client_box, self.catalog_status = self._metadata_item("КЛИЕНТ")
        self.catalog_status.setText("Готов к запуску")
        self.catalog_status.setWordWrap(True)
        metadata.addWidget(version_box, 0, 0)
        metadata.addWidget(loader_box, 0, 1)
        metadata.addWidget(players_box, 1, 0)
        metadata.addWidget(client_box, 1, 1)
        box.addLayout(metadata)
        self.details_players_label = QLabel("")
        self.details_players_label.hide()
        self.catalog_progress = QProgressBar()
        self.catalog_progress.setTextVisible(False)
        self.catalog_progress.hide()
        box.addWidget(self.catalog_progress)
        box.addStretch(1)
        self.catalog_play = QPushButton("ИГРАТЬ")
        self.catalog_play.setObjectName("playLarge")
        self.catalog_play.setFixedHeight(44 if self.compact_ui else 52)
        self.catalog_play.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.catalog_play.setIcon(nexus_button_icon(4))
        self.catalog_play.setIconSize(QSize(28, 28))
        self.catalog_play.clicked.connect(self._play)
        box.addWidget(self.catalog_play)
        settings = QPushButton("Параметры запуска")
        settings.setObjectName("secondaryButton")
        settings.setFixedHeight(44 if self.compact_ui else 52)
        settings.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        settings.setIcon(nexus_nav_icon(4))
        settings.setIconSize(QSize(28, 28))
        settings.clicked.connect(self._settings)
        box.addWidget(settings)
        optional_mods = QPushButton("Опциональные моды")
        optional_mods.setObjectName("secondaryButton")
        optional_mods.setFixedHeight(44 if self.compact_ui else 52)
        optional_mods.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        optional_mods.setIcon(nexus_nav_icon(3))
        optional_mods.setIconSize(QSize(28, 28))
        optional_mods.clicked.connect(self._optional_mods)
        box.addWidget(optional_mods)
        return panel

    def _private_catalog_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        side_margin = 22 if self.compact_ui else 38
        layout.setContentsMargins(side_margin, 8 if self.compact_ui else 12, side_margin, 10 if self.compact_ui else 18)
        layout.setSpacing(6 if self.compact_ui else 9)
        welcome = QLabel("Добро пожаловать в")
        welcome.setObjectName("privateWelcome")
        layout.addWidget(welcome)
        hero = QLabel("NEXUS")
        hero.setObjectName("privateHero")
        layout.addWidget(hero)
        subtitle = QLabel("Твой путь. Твои миры. Твоя легенда.")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        content = QHBoxLayout()
        content.setSpacing(12 if self.compact_ui else 18)
        layout.addLayout(content, 1)
        left = QVBoxLayout()
        left.setSpacing(10)
        content.addLayout(left, 5)
        section = QLabel("✧  ДОСТУПНЫЕ МИРЫ")
        section.setObjectName("privateSection")
        left.addWidget(section)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        cards = QVBoxLayout(host)
        cards.setContentsMargins(0, 4, 6, 8)
        cards.setSpacing(12)
        cards.setAlignment(Qt.AlignTop)
        accents = ["#176ed4", "#1f8ddd", "#365fca", "#1785a8"]
        index = 0
        for project in self.projects:
            for server in project.servers:
                cover = QPixmap(str(resource(server.artwork or "nexus-hero.png")))
                card = ServerCard(server, accents[index % len(accents)], cover)
                card.setMinimumWidth(280 if self.compact_ui else 360)
                card.setMaximumWidth(640)
                card.configure_hover_expansion(compact_height=190, expanded_height_limit=360)
                card.clicked.connect(lambda _=False, item=server: self.select_server(item))
                cards.addWidget(card)
                self.server_cards[server.id] = card
                index += 1
        scroll.setWidget(host)
        left.addWidget(scroll, 1)
        self.details_panel = self._private_server_details_panel()
        self.details_panel.setMinimumWidth(330 if self.compact_ui else 400)
        self.details_panel.setMaximumWidth(480 if self.compact_ui else 560)
        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        details_scroll.setFrameShape(QFrame.NoFrame)
        details_scroll.setWidget(self.details_panel)
        details_scroll.setMinimumWidth(340 if self.compact_ui else 410)
        details_scroll.setMaximumWidth(490 if self.compact_ui else 570)
        content.addWidget(details_scroll, 4)
        footer = QFrame()
        footer.setObjectName("launcherFooter")
        footer.setFixedHeight(50 if self.compact_ui else 62)
        footer_layout = QGridLayout(footer)
        footer_layout.setContentsMargins(20, 0, 16, 0)
        footer_left = QLabel(f"NEXUS LAUNCHER\nv{CURRENT_VERSION}  •  PUBLIC TEST")
        footer_layout.addWidget(footer_left, 0, 0)
        self.footer_java = QLabel(detect_java_label(self.config.get("java_path", "")))
        self.footer_java.setObjectName("muted")
        self.footer_java.setAlignment(Qt.AlignCenter)
        footer_layout.addWidget(self.footer_java, 0, 1)
        self.footer_build = QLabel("Сборка: не проверена")
        self.footer_build.setObjectName("muted")
        self.footer_build.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        footer_layout.addWidget(self.footer_build, 0, 2)
        for column in range(3):
            footer_layout.setColumnStretch(column, 1)
        layout.addWidget(footer)
        if self.current_server:
            self.select_server(self.current_server)
        return page

    def _style(self):
        if self.private_ui:
            self._private_style()
            return
        self.setStyleSheet("""
            QMainWindow { background:#080d17; }
            QWidget { background:transparent; color:#f4f7fb; font-family:'Segoe UI'; font-size:14px; }
            QLabel#brand { font-size:28px; font-weight:800; letter-spacing:2px; color:white; }
            QLabel#heroTitle { font-size:52px; font-weight:700; color:white; }
            QLabel#dialogTitle { font-size:24px; font-weight:700; }
            QLabel#muted { color:#8d9ab2; } QLabel#valueBadge { background:#202a3c; border-radius:8px; padding:8px 12px; }
            QFrame#topbar { background:#101622; border-bottom:1px solid #1b2638; }
            QWidget#catalogPage { background:#080d17; }
            QWidget#catalogBody { background:transparent; }
            QFrame#launcherFooter { background:#080d17; border-top:1px solid #1b2737; border-radius:0; }
            QPushButton { background:#20283a; border:1px solid #35405a; border-radius:9px; padding:10px 16px; color:#edf3ff; }
            QPushButton:hover { background:#2a354c; } QPushButton#primary { background:#2196f3; border:0; font-weight:700; font-size:16px; padding:13px 26px; }
            QPushButton#playLarge { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0891b2,stop:.55 #2563eb,stop:1 #6d28d9); border:0; border-radius:12px; font-size:17px; font-weight:800; letter-spacing:1px; color:white; }
            QPushButton#playLarge:hover { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0aa0c2,stop:.55 #2d6df2,stop:1 #7833e8); }
            QPushButton#playLarge:pressed { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #087f9c,stop:.55 #2258cc,stop:1 #5e22bd); }
            QPushButton#secondaryButton { background:rgba(255,255,255,0.01); border:1px solid rgba(100,120,150,0.4); border-radius:10px; color:#cbd5e1; }
            QPushButton#secondaryButton:hover { background:rgba(255,255,255,0.025); border-color:rgba(120,145,180,0.6); }
            QFrame#detailsPanel { background:#0d1422; border:1px solid #1d2a3b; border-radius:18px; }
            QFrame#metaBox { background:#0b1220; border:1px solid #1c293a; border-radius:12px; }
            QPushButton#primary:hover { background:#42a8f5; } QPushButton#icon { font-size:20px; border:0; background:#1a2130; }
            QPushButton#squareButton { font-size:19px; padding:0; background:#1b2332; border:1px solid #2b3549; }
            QPushButton#profileButton { padding:10px 15px; background:#171e2b; border:1px solid #29354a; }
            QPushButton#profileButton:hover { background:rgba(255,255,255,0.035); border-color:rgba(100,120,150,0.55); }
            QPushButton#windowButton { padding:0; background:transparent; border:0; font-size:18px; } QPushButton#windowButton:hover { background:#273248; }
            QPushButton#windowButton[closeControl="true"]:hover { background:rgba(239,68,68,0.14); }
            QLineEdit,QComboBox { background:#171e2b; border:1px solid #35405a; border-radius:8px; padding:10px; }
            QProgressBar { background:#20283a; border:0; border-radius:4px; height:8px; } QProgressBar::chunk { background:#2196f3; border-radius:4px; }
            QDialog#settingsDialog { background:#111827; } QScrollArea { border:0; }
        """)

    def _build(self):
        if self.private_ui:
            self._build_private()
            return
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(TitleBar(self))
        self.pages = QStackedWidget()
        root.addWidget(self.pages)
        self.catalog = self._catalog_page()
        self.detail = None
        self.pages.addWidget(self.catalog)
        # The catalog now owns the only active launch controls. The old hero
        # page is intentionally not instantiated, so its artwork cannot leak
        # outside the stacked layout during resize/repaint.
        self.play = self.catalog_play
        self.progress = self.catalog_progress
        self.status = self.catalog_status

    def _catalog_page(self):
        page = QWidget()
        page.setObjectName("catalogPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(48, 36, 48, 0)
        page_layout.setSpacing(14)
        title = QLabel("Выберите мир")
        title.setStyleSheet("font-size:34px;font-weight:700;")
        page_layout.addWidget(title)
        subtitle = QLabel("Каждый мир — отдельная версия, сборка и приключение")
        subtitle.setObjectName("muted")
        page_layout.addWidget(subtitle)
        content = QHBoxLayout()
        content.setSpacing(40)
        page_layout.addLayout(content, 1)
        left = QVBoxLayout()
        left.setSpacing(14)
        content.addLayout(left, 5)
        section = QLabel("ДОСТУПНЫЕ МИРЫ")
        section.setStyleSheet("color:#7185a3;font-size:10px;font-weight:600;letter-spacing:2px;margin-top:18px;")
        left.addWidget(section)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;")
        grid_host = QWidget()
        grid_host.setObjectName("catalogBody")
        grid = QVBoxLayout(grid_host)
        grid.setContentsMargins(0, 8, 8, 16)
        grid.setSpacing(20)
        grid.setAlignment(Qt.AlignTop)
        accents = ["#143b68", "#39245e", "#5a273e", "#174a45", "#4c3b1e"]
        index = 0
        for project in self.projects:
            for server in project.servers:
                cover = QPixmap(str(resource(server.artwork or "nexus-hero.png")))
                card = ServerCard(server, accents[index % len(accents)], cover)
                card.clicked.connect(lambda _=False, item=server: self.select_server(item))
                grid.addWidget(card)
                self.server_cards[server.id] = card
                index += 1
        if not index:
            empty = QLabel(
                "Нет доступных миров\n\nСейчас нет доступных серверов. Попробуйте проверить обновления позже."
            )
            empty.setObjectName("muted")
            grid.addWidget(empty)
        scroll.setWidget(grid_host)
        left.addWidget(scroll, 1)
        self.details_panel = self._server_details_panel()
        content.addWidget(self.details_panel, 4, Qt.AlignTop)
        footer = QFrame()
        footer.setObjectName("launcherFooter")
        footer.setFixedHeight(52)
        footer_layout = QGridLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_left = QLabel(f"NEXUS Launcher  •  v{CURRENT_VERSION}")
        footer_left.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        footer_layout.addWidget(footer_left, 0, 0)
        self.footer_java = QLabel(detect_java_label(self.config.get("java_path", "")))
        self.footer_java.setObjectName("muted")
        self.footer_java.setAlignment(Qt.AlignCenter)
        footer_layout.addWidget(self.footer_java, 0, 1)
        self.footer_build = QLabel("Сборка: не проверена")
        self.footer_build.setObjectName("muted")
        self.footer_build.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        footer_layout.addWidget(self.footer_build, 0, 2)
        for column in range(3):
            footer_layout.setColumnStretch(column, 1)
        page_layout.addWidget(footer)
        if self.current_server:
            self.select_server(self.current_server)
        else:
            self.details_title.setText("Нет доступных миров")
            self.details_status.setText("СЕРВЕРЫ НЕ НАСТРОЕНЫ")
            self.catalog_play.setEnabled(False)
        return page

    def _server_details_panel(self):
        panel = QFrame()
        panel.setObjectName("detailsPanel")
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(472)
        box = QVBoxLayout(panel)
        box.setContentsMargins(30, 26, 30, 24)
        box.setSpacing(12)
        eyebrow = QLabel("ВЫБРАННЫЙ МИР")
        eyebrow.setStyleSheet("color:#64748b;font-size:11px;font-weight:700;letter-spacing:2px;")
        box.addWidget(eyebrow)
        self.details_title = QLabel()
        self.details_title.setStyleSheet("font-size:28px;font-weight:750;")
        box.addWidget(self.details_title)
        self.details_status = QLabel("●  ПРОВЕРКА СЕРВЕРА")
        self.details_status.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;")
        box.addWidget(self.details_status)
        metadata = QHBoxLayout()
        metadata.setSpacing(12)
        version_box, self.details_version = self._metadata_item("MINECRAFT")
        loader_box, self.details_loader = self._metadata_item("ЗАГРУЗЧИК")
        metadata.addWidget(version_box)
        metadata.addWidget(loader_box)
        box.addLayout(metadata)
        self.details_players_label = QLabel("Игроки")
        self.details_players_label.setObjectName("muted")
        box.addWidget(self.details_players_label)
        self.details_players = QLabel("—")
        self.details_players.setStyleSheet("font-size:20px;font-weight:700;")
        box.addWidget(self.details_players)
        self.catalog_status = QLabel("Клиент готов")
        self.catalog_status.setObjectName("muted")
        self.catalog_status.setWordWrap(True)
        box.addWidget(self.catalog_status)
        self.catalog_progress = QProgressBar()
        self.catalog_progress.setTextVisible(False)
        self.catalog_progress.hide()
        box.addWidget(self.catalog_progress)
        actions = QVBoxLayout()
        actions.setSpacing(10)
        actions.setContentsMargins(0, 0, 0, 0)
        self.catalog_play = QPushButton("▶  ИГРАТЬ")
        self.catalog_play.setObjectName("playLarge")
        self.catalog_play.setFixedHeight(58)
        self.catalog_play.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        play_shadow = QGraphicsDropShadowEffect(self.catalog_play)
        play_shadow.setBlurRadius(24)
        play_shadow.setOffset(0, 8)
        play_shadow.setColor(QColor(37, 99, 235, 36))
        self.catalog_play.setGraphicsEffect(play_shadow)
        self.catalog_play.clicked.connect(self._play)
        actions.addWidget(self.catalog_play)
        settings = QPushButton("Параметры запуска")
        settings.setObjectName("secondaryButton")
        settings.setFixedHeight(42)
        settings.clicked.connect(self._settings)
        actions.addWidget(settings)
        box.addLayout(actions)
        return panel

    def _metadata_item(self, title):
        frame = QFrame()
        frame.setObjectName("metaBox")
        frame.setMinimumHeight(64 if getattr(self, "compact_ui", False) else 82)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            12 if getattr(self, "compact_ui", False) else 16,
            9 if getattr(self, "compact_ui", False) else 14,
            12 if getattr(self, "compact_ui", False) else 16,
            9 if getattr(self, "compact_ui", False) else 14,
        )
        layout.setSpacing(3 if getattr(self, "compact_ui", False) else 5)
        label = QLabel(title)
        label.setStyleSheet("color:#7185a3;font-size:10px;font-weight:600;letter-spacing:2px;")
        value = QLabel()
        value.setStyleSheet("color:#f8fafc;font-size:15px;font-weight:600;")
        value.setMinimumHeight(22)
        layout.addWidget(label)
        layout.addWidget(value)
        return frame, value

    def _detail_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        self.hero = QLabel()
        self.hero.setMinimumHeight(500)
        self.hero.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hero_path = resource("nexus-hero.png")
        pix = QPixmap(str(hero_path))
        self.hero.setPixmap(pix)
        self.hero.setScaledContents(True)
        overlay = QVBoxLayout(self.hero)
        overlay.setContentsMargins(72, 70, 72, 42)
        overlay.addStretch()
        self.hero_title = QLabel("NexusMC")
        self.hero_title.setObjectName("heroTitle")
        self.hero_title.setStyleSheet("background:transparent;")
        overlay.addWidget(self.hero_title)
        self.hero_meta = QLabel("Minecraft 1.21.1  •  NeoForge")
        self.hero_meta.setStyleSheet("background:transparent;color:#a9c9ea;font-size:16px;")
        overlay.addWidget(self.hero_meta)
        self.hero_desc = QLabel(
            "Исследуй новый мир, строй города и играй вместе с друзьями.\nОбновления устанавливаются автоматически."
        )
        self.hero_desc.setStyleSheet("background:transparent;font-size:17px;")
        overlay.addWidget(self.hero_desc)
        actions = QHBoxLayout()
        self.play = QPushButton("▶  ИГРАТЬ")
        self.play.setObjectName("primary")
        self.play.clicked.connect(self._play)
        actions.addWidget(self.play)
        settings = QPushButton("⚙  Параметры")
        settings.clicked.connect(self._settings)
        actions.addWidget(settings)
        actions.addStretch()
        overlay.addLayout(actions)
        overlay.addStretch()
        outer.addWidget(self.hero, 1)
        statusbar = QFrame()
        statusbar.setFixedHeight(100)
        line = QVBoxLayout(statusbar)
        line.setContentsMargins(45, 14, 45, 16)
        self.status = QLabel("Готов к запуску")
        self.status.setObjectName("muted")
        line.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        line.addWidget(self.progress)
        outer.addWidget(statusbar)
        return page

    def show_catalog(self):
        self.pages.setCurrentWidget(self.catalog)

    def show_instances(self):
        self.instances_page.refresh(self.current_user_instance_id)
        self.pages.setCurrentWidget(self.instances_page)

    def _launch_user_instance(self, instance_id, launch_mode="normal"):
        if self.game_process and self.game_process.poll() is None:
            self._stop_game()
            return
        if self._launch_lock.locked():
            return
        if launch_mode not in {"normal", "test"}:
            raise ValueError("Неизвестный режим запуска")
        if launch_mode == "normal":
            self.current_user_instance_id = instance_id
        self._start_launch_worker(self._launch_user_instance_worker, (instance_id, launch_mode))

    def _start_launch_worker(self, target, args=()):
        if not self._launch_lock.acquire(blocking=False):
            return False

        def guarded():
            try:
                target(*args)
            finally:
                self._launch_lock.release()

        try:
            threading.Thread(target=guarded, daemon=True).start()
        except BaseException:
            self._launch_lock.release()
            raise
        return True

    def _launch_user_instance_worker(self, instance_id, launch_mode="normal"):
        try:
            if not self.account_profile:
                raise PermissionError("Войдите в зарегистрированный аккаунт NEXUS перед запуском.")
            if not self.account_profile.minecraft_nick:
                raise PermissionError("Завершите Minecraft-профиль на сайте NEXUS перед запуском игры.")
            from nexus_launcher.launch_identity import ticket_supplier
            profile = self.account_profile
            issue_ticket = ticket_supplier(profile, self.account_client,
                                           lambda: self.account_profile, lambda: self.account_client)
            instance = self.instance_service.load(instance_id)
            folder = self.instance_service.path_for(instance_id)
            core = MinecraftLauncher(folder, self.bridge.status.emit, self.bridge.progress.emit)
            process = core.launch(
                instance.minecraft_version,
                profile.minecraft_nick,
                instance.memory_mb,
                "",
                instance.loader,
                instance.loader_version,
                java_path=instance.java_path or self.config.get("java_path", ""),
                java_required_major=instance.java_major,
                min_memory_mb=instance.min_memory_mb,
                jvm_args=instance.jvm_args,
                ticket_supplier=issue_ticket,
                resolution_width=instance.resolution_width,
                resolution_height=instance.resolution_height,
            )
            import time
            from nexus_launcher.user_instances import utc_now
            started = time.monotonic()
            if launch_mode == "test": instance.last_test_launch = utc_now()
            else: instance.last_launch = utc_now()
            self.instance_service.save(instance)
            self.game_process = process
            self.bridge.finished.emit(process.pid)
            return_code = process.wait()
            instance = self.instance_service.load(instance_id)
            if launch_mode == "test":
                instance.last_test_exit_code = return_code
                instance.last_test_duration = round(time.monotonic() - started, 1)
            else:
                instance.last_exit_code = return_code
                instance.last_game_duration = round(time.monotonic() - started, 1)
            self.instance_service.save(instance)
            log_handle = getattr(process, "_nexus_log_handle", None)
            if log_handle:
                log_handle.close()
            self.bridge.game_exited.emit(return_code)
        except Exception as error:
            self.bridge.failed.emit(str(error))

    def _toggle_max(self):
        if self.windowState() & Qt.WindowMaximized:
            self.setWindowState(self.windowState() & ~Qt.WindowMaximized)
            self.showNormal()
            if not self.private_ui:
                self.maximize_button.setText("□")
            self.maximize_button.setToolTip("Развернуть")
        else:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
            self.showMaximized()
            if not self.private_ui:
                self.maximize_button.setText("❐")
            self.maximize_button.setToolTip("Восстановить")

    def show_server(self, server):
        self.select_server(server)
        self.show_catalog()

    def select_server(self, server):
        if server is None:
            return
        self.current_server = server
        for card in self.server_cards.values():
            card.set_selected(card.server is server)
        if hasattr(self, "details_title"):
            self.details_title.setText(server.name)
            self.details_version.setText(server.minecraft_version)
            loader_names = {"neoforge": "NeoForge", "fabric": "Fabric", "vanilla": "Vanilla"}
            self.details_loader.setText(loader_names.get(server.loader, server.loader.title()))
            online = self.server_states.get(server.id)
            access = self.build_access.get(server.id, {})
            mode = str(access.get("mode", "OPEN")).upper()
            allowed = bool(access.get("allowed", mode == "OPEN"))
            if mode in {"MAINTENANCE", "CLOSED"}:
                label = "ТЕХНИЧЕСКИЕ РАБОТЫ" if mode == "MAINTENANCE" else "СБОРКА ЗАКРЫТА"
                self.details_status.setText(f"●  {label}" + (" • ДОСТУП РАЗРЕШЁН" if allowed else ""))
                self.details_status.setStyleSheet("color:#fbbf24;font-size:11px;font-weight:600;letter-spacing:1px;")
                self.details_players.setText("—")
            elif server.visibility == "coming_soon":
                self.details_status.setText("●  СБОРКА ГОТОВИТСЯ")
                self.details_status.setStyleSheet("color:#fbbf24;font-size:11px;font-weight:600;letter-spacing:1px;")
                self.details_players.setText("—")
                self.catalog_play.setEnabled(False)
                self.catalog_play.setText("СКОРО")
                if self.private_ui:
                    self.catalog_play.setIcon(nexus_button_icon(7))
            elif online:
                ok, current, maximum = online
                self.details_status.setText("●  СЕРВЕР РАБОТАЕТ" if ok else "●  СЕРВЕР НЕДОСТУПЕН")
                self.details_status.setStyleSheet(
                    f"color:{'#4ade80' if ok else '#f87171'};font-size:11px;font-weight:600;letter-spacing:1px;"
                )
                self.details_players.setText(f"{current} / {maximum}" if ok and maximum else "—")
            else:
                self.details_status.setText("●  ПРОВЕРКА СЕРВЕРА")
                self.details_status.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;")
                self.details_players.setText("—")
            if server.visibility != "coming_soon" and allowed:
                self.catalog_play.setEnabled(True)
                self.catalog_play.setText("ИГРАТЬ" if self.private_ui else "▶  ИГРАТЬ")
                if self.private_ui:
                    self.catalog_play.setIcon(nexus_button_icon(4))
                if mode in {"MAINTENANCE", "CLOSED"}:
                    self.catalog_status.setText("Административный доступ разрешён")
            elif not allowed:
                self.catalog_play.setEnabled(False)
                self.catalog_play.setText("ДОСТУП ЗАКРЫТ")
                if self.private_ui:
                    self.catalog_play.setIcon(nexus_button_icon(6))
                self.catalog_status.setText(str(access.get("message") or "Сборка временно недоступна."))
            installed = ModpackUpdater(self._instance_dir()).installed_version
            self.footer_build.setText(f"Сборка {installed}" if installed else "Сборка: не установлена")

    def _check_servers(self):
        for project in self.projects:
            for server in project.servers:
                if server.visibility == "coming_soon" or not server.address:
                    continue
                threading.Thread(target=self._server_check_worker, args=(server,), daemon=True).start()

    def _server_check_worker(self, server):
        try:
            result = ping_server(server.address)
            players = result.get("players", {})
            self.bridge.server_checked.emit(server.id, True, int(players.get("online", 0)), int(players.get("max", 0)))
        except Exception:
            self.bridge.server_checked.emit(server.id, False, 0, 0)

    def _server_checked(self, server_id, ok, current, maximum):
        self.server_states[server_id] = (ok, current, maximum)
        card = self.server_cards.get(server_id)
        if card:
            card.set_online(ok)
        if self.current_server.id == server_id:
            self.select_server(self.current_server)

    def _profile_menu(self):
        if self.private_ui:
            popup = ProfilePopup(self)
            popup.adjustSize()
            anchor = self.profile.mapToGlobal(self.profile.rect().bottomRight())
            popup.move(anchor.x() - popup.width(), anchor.y() + 8)
            self._profile_popup = popup
            popup.show()
            return
        menu = QMenu(self)
        if self.account_profile:
            menu.addAction(f"Профиль: {self.account_profile.minecraft_nick}")
            menu.addAction(self.account_profile.email)
            menu.addSeparator()
            menu.addAction("Обновить профиль", self._refresh_account)
            menu.addAction("Выйти из аккаунта", self._logout_account)
        else:
            menu.addAction("Войти в аккаунт NEXUS", self._login_account)
        menu.addSeparator()
        menu.addAction("Настройки", self._settings)
        menu.addAction("Проверить файлы сборки", self._repair_pack)
        menu.addAction("Папка игры", self._open_folder)
        menu.exec(self.profile.mapToGlobal(self.profile.rect().bottomLeft()))

    def _open_web_profile(self):
        webbrowser.open("https://nexusmc.flux-productions.com/profile")

    def _login_account(self):
        dialog = LoginDialog(self)
        if not dialog.exec():
            return
        identifier, password = dialog.credentials()
        totp_code, recovery_code = dialog.second_factor()
        dialog.password.clear()
        if not identifier or not password:
            QMessageBox.warning(self, "NEXUS Launcher", "Введите ник или почту и пароль.")
            return
        self.profile.setEnabled(False)
        self.profile.setText("◆  Вход…")
        threading.Thread(target=self._login_account_worker, args=(identifier, password, totp_code, recovery_code), daemon=True).start()

    def _login_account_worker(self, identifier, password, totp_code='', recovery_code=''):
        try:
            self.bridge.account_ready.emit(self.account_client.login(identifier, password, totp_code=totp_code, recovery_code=recovery_code))
        except AccountError as error:
            self.bridge.account_failed.emit(str(error))

    def _restore_account_worker(self):
        try:
            profile = self.account_client.restore()
            self.bridge.account_ready.emit(profile)
        except AccountError as error:
            self.bridge.account_failed.emit(str(error))

    def _refresh_build_access_worker(self):
        try:
            self.bridge.build_access_ready.emit(self.account_client.build_access())
        except AccountError:
            # A network failure must not overwrite the last known policy.
            pass

    def _build_access_ready(self, access):
        if not isinstance(access, dict):
            return
        self.build_access = access
        for server_id, card in self.server_cards.items():
            state = access.get(server_id, {})
            card.set_access(state.get("mode", "OPEN"), state.get("allowed", True))
        if self.current_server:
            self.select_server(self.current_server)

    def _refresh_account(self):
        self.profile.setEnabled(False)
        threading.Thread(target=self._restore_account_worker, daemon=True).start()

    def _logout_account(self):
        self.account_client.logout()
        self.account_profile = None
        self.config.pop("username", None)
        self._save_config()
        self.profile.setIcon(QIcon())
        self.profile.setText("◆  Войти")
        threading.Thread(target=self._refresh_build_access_worker, daemon=True).start()

    def _account_ready(self, profile):
        if profile is None:
            self.profile.setEnabled(True)
            if not self.account_profile:
                self.profile.setIcon(QIcon())
                self.profile.setText("◆  Войти")
            return
        self.account_profile = profile
        self.config["username"] = profile.minecraft_nick
        self._save_config()
        self.profile.setEnabled(True)
        self.profile.setText(profile.minecraft_nick)
        if profile.skin_png:
            skin = QPixmap()
            if skin.loadFromData(profile.skin_png):
                head = skin.copy(8, 8, 8, 8).scaled(28, 28, Qt.KeepAspectRatio, Qt.FastTransformation)
                self.profile.setIcon(QIcon(head))
                self.profile.setIconSize(head.size())
        threading.Thread(target=self._refresh_build_access_worker, daemon=True).start()

    def _account_failed(self, message):
        self.profile.setEnabled(True)
        self.profile.setText("◆  Войти" if not self.account_profile else self.account_profile.minecraft_nick)
        QMessageBox.warning(self, "Вход в NEXUS", message)

    def _settings(self):
        if self._launch_lock.locked() or (self.game_process and self.game_process.poll() is None):
            QMessageBox.information(
                self, "Параметры игры", "Дождитесь завершения запуска и закройте Minecraft перед изменением параметров."
            )
            return
        dialog = SettingsDialog(self, self.config)
        if dialog.exec():
            values = dialog.values()
            self.config.update(values)
            self._save_config()
            self.footer_java.setText(detect_java_label(self.config.get("java_path", "")))

    def _optional_mods(self):
        updater = ModpackUpdater(self._instance_dir(), lambda _message: None)
        dialog = OptionalModsDialog(self, updater.optional_catalog(), updater.optional_selections())
        if not dialog.exec():
            return
        for mod_id, enabled in dialog.values().items():
            try:
                updater.set_optional_enabled(mod_id, enabled)
            except ValueError as error:
                QMessageBox.warning(self, "Опциональные моды", str(error))
                return

    def _repair_pack(self):
        server = self.current_server
        if not server or not server.manifest_url:
            QMessageBox.information(self, "NEXUS Launcher", "Для этого мира восстановление сборки не настроено.")
            return
        if self.game_process and self.game_process.poll() is None:
            QMessageBox.warning(self, "NEXUS Launcher", "Minecraft сейчас запущен. Закройте игру для проверки файлов.")
            return
        if self._launch_lock.locked():
            QMessageBox.information(self, "NEXUS Launcher", "Другая установка или проверка уже выполняется.")
            return
        self.play.setEnabled(False)
        self.progress.show()
        self.status.setText("Проверка файлов сборки…")
        self._start_launch_worker(self._repair_worker, (server,))

    def _repair_worker(self, server):
        try:
            folder = self._instance_dir_for(server) if hasattr(self, "_instance_dir_for") else self._instance_dir()
            log_path = folder / ".nexus-launcher" / "logs" / "launcher-updater.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)

            def repair_log(message: str) -> None:
                self.bridge.status.emit(message)
                with log_path.open("a", encoding="utf-8") as output:
                    output.write(message + "\n")

            result = ModpackUpdater(folder, repair_log, self.bridge.progress.emit, self.bridge.updater_progress.emit, instance_id=server.id).repair(server.manifest_url)
            downloaded = self._format_size(result.downloaded) if hasattr(self, "_format_size") else f"{result.downloaded} Б"
            self.bridge.repair_done.emit(
                f"Проверка завершена · проверено: {result.checked} · исправлено: {result.repaired} · загружено: {downloaded}"
            )
        except Exception as error:
            self.bridge.repair_done.emit(f"Ошибка восстановления: {error}")

    def _repair_done(self, message: str):
        self.play.setEnabled(True)
        self.progress.hide()
        self.status.setText(message)
        if message.startswith("Ошибка"):
            QMessageBox.warning(self, "Восстановление сборки", message)

    def _save_config(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")

    def _instance_dir(self):
        if self.current_server.instance_id:
            target = self._storage_root / "instances" / self.current_server.instance_id
            legacy = self._storage_root / "instances" / "nexusmc" / self.current_server.id
            if not target.exists() and legacy.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy), target)
            return target
        for project in self.projects:
            if self.current_server in project.servers:
                return self._storage_root / "instances" / project.id / self.current_server.id
        return self._storage_root / "instances" / "default" / self.current_server.id

    def _sync_skin_for_instance(self, folder: Path) -> None:
        """Expose the NEXUS profile skin to CustomSkinLoader inside Minecraft."""
        profile = self.account_profile
        if not profile or not profile.skin_png:
            return
        loader_dir = folder / "CustomSkinLoader"
        skin_dir = loader_dir / "LocalSkin" / "skins"
        skin_dir.mkdir(parents=True, exist_ok=True)
        target = skin_dir / f"{profile.minecraft_nick}.png"
        temporary = target.with_suffix(".png.part")
        temporary.write_bytes(profile.skin_png)
        os.replace(temporary, target)

        # NEXUS is authoritative for launcher accounts.  CustomSkinLoader's
        # generated defaults query Mojang and third-party services before the
        # local file, so a public account with the same nickname can otherwise
        # override the skin uploaded on the NEXUS website.
        config_path = loader_dir / "CustomSkinLoader.json"
        config: dict = {}
        if config_path.is_file():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config = loaded
            except (OSError, ValueError):
                config = {}
        local_loader = {
            "name": "NEXUS LocalSkin",
            "type": "Legacy",
            "checkPNG": True,
            "skin": "LocalSkin/skins/{USERNAME}.png",
            "model": profile.skin_model,
            "cape": "LocalSkin/capes/{USERNAME}.png",
            "elytra": "LocalSkin/elytras/{USERNAME}.png",
        }
        network_loader = {
            "name": "NEXUS Network Skins",
            "type": "Legacy",
            "checkPNG": True,
            "skin": "https://nexusmc-site.robloxksergg.workers.dev/api/minecraft/skin/{USERNAME}.png",
            "model": profile.skin_model,
        }
        old_loaders = config.get("loadlist", [])
        if not isinstance(old_loaders, list):
            old_loaders = []
        config["loadlist"] = [
            local_loader,
            network_loader,
            *(
                item
                for item in old_loaders
                if isinstance(item, dict)
                and item.get("name") not in {"LocalSkin", "NEXUS LocalSkin", "NEXUS Network Skins"}
            ),
        ]
        config.setdefault("version", "15.0.1")
        config.setdefault("buildNumber", 40)
        config["forceDisableCache"] = True
        config["enableLocalProfileCache"] = False
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        caches = loader_dir / "caches"
        if caches.is_dir():
            shutil.rmtree(caches, ignore_errors=True)

    def _open_folder(self):
        path = self._instance_dir()
        path.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(path)

    def _play(self):
        if self._launch_lock.locked() and not self.game_process:
            return
        if self.game_process and self.game_process.poll() is None:
            self._stop_game()
            return
        if not self.current_server:
            QMessageBox.information(self, "NEXUS Launcher", "Нет доступного сервера для запуска.")
            return
        if not self.account_profile:
            QMessageBox.warning(self, "Вход в NEXUS", "Сначала войдите в зарегистрированный аккаунт с Minecraft-ником.")
            self._login_account()
            return
        if self.current_server.visibility == "coming_soon":
            QMessageBox.information(self, "NEXUS Launcher", "Сборка ещё готовится к выпуску.")
            return
        access = self.build_access.get(self.current_server.id, {})
        if access and not bool(access.get("allowed", False)):
            QMessageBox.warning(self, "Доступ к сборке", str(access.get("message") or "Сборка временно недоступна."))
            return
        self.stop_requested = False
        self.play.setEnabled(False)
        self.progress.show()
        self.status.setText("Подготовка запуска…")
        if hasattr(self, "catalog_play"):
            self.catalog_play.setEnabled(False)
            self.catalog_play.setText("ЗАПУСК…")
            if self.private_ui:
                self.catalog_play.setIcon(nexus_button_icon(0))
            self.catalog_progress.show()
            self.catalog_status.setText("Подготовка запуска…")
        self._launch_server = self.current_server
        self._start_launch_worker(self._launch_worker)

    def _launch_worker(self):
        try:
            if not self.account_profile:
                raise PermissionError("Вход без зарегистрированного аккаунта NEXUS запрещён.")
            if not self.account_profile.minecraft_nick:
                raise PermissionError("Завершите Minecraft-профиль на сайте NEXUS перед запуском игры.")
            from nexus_launcher.launch_identity import ticket_supplier
            profile = self.account_profile
            issue_ticket = ticket_supplier(profile, self.account_client,
                                           lambda: self.account_profile, lambda: self.account_client)
            server = getattr(self, "_launch_server", None) or self.current_server
            live_access = self.account_client.build_access().get(server.id, {})
            if live_access and not bool(live_access.get("allowed", False)):
                raise PermissionError(str(live_access.get("message") or "Сборка временно недоступна."))
            folder = self._instance_dir_for(server) if hasattr(self, "_instance_dir_for") else self._instance_dir()
            release = None
            launcher_log = folder / ".nexus-launcher" / "logs" / "launcher-updater.log"
            launcher_log.parent.mkdir(parents=True, exist_ok=True)

            def launch_log(message: str) -> None:
                self.bridge.status.emit(message)
                with launcher_log.open("a", encoding="utf-8") as output:
                    output.write(message + "\n")

            launch_log(
                f"{server.name} profile: Minecraft {server.minecraft_version}, {server.loader} {server.loader_version}"
            )
            if server.local_pack_path:
                archive = Path(server.local_pack_path)
                if not archive.is_absolute():
                    archive = resource(server.local_pack_path)
                if not archive.is_file():
                    raise FileNotFoundError(f"Архив сборки не найден: {archive}")
                importer = CurseForgeImporter(
                    folder,
                    server.pack_id or f"{server.id}-pack",
                    launch_log,
                    self.bridge.progress.emit,
                )
                importer.repair_installed()
                already_installed = importer.is_installed(archive) if server.manifest_url else importer.verify()
                if not already_installed:
                    importer.install(archive)
                if not server.manifest_url:
                    importer.quarantine_extra_mods()
            if server.manifest_url:
                updater = ModpackUpdater(folder, launch_log, self.bridge.progress.emit, self.bridge.updater_progress.emit, instance_id=server.id)
                try:
                    release = updater.update_if_needed(server.manifest_url)
                    if release:
                        if release.minecraft and release.minecraft != server.minecraft_version:
                            raise ValueError(
                                f"Manifest требует Minecraft {release.minecraft}, профиль — {server.minecraft_version}"
                            )
                        if release.loader and release.loader != server.loader:
                            raise ValueError(f"Manifest требует {release.loader}, профиль — {server.loader}")
                        if release.maintenance:
                            raise RuntimeError("Сервер на технических работах")
                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                    with launcher_log.open("a", encoding="utf-8") as output:
                        output.write(f"Manifest unavailable: {type(error).__name__}: {error}\n")
                    if not updater.can_launch_offline():
                        raise RuntimeError(
                            "Не удалось подключиться к серверу обновлений, а локальная сборка не прошла проверку"
                        ) from error
                    self.bridge.status.emit("Сервер обновлений недоступен — запускаю последнюю проверенную сборку")
            self._sync_skin_for_instance(folder)
            ensure_visual_defaults(folder)
            minecraft_server = release.minecraft_server if release and release.minecraft_server else server.address
            if minecraft_server:
                ensure_server(folder / "servers.dat", f"{server.name} • NEXUS", minecraft_server)
            core = MinecraftLauncher(folder, launch_log, self.bridge.progress.emit)
            minecraft_version = release.minecraft if release and release.minecraft else server.minecraft_version
            loader = release.loader if release and release.loader else server.loader
            loader_version = release.loader_version if release and release.loader_version else server.loader_version
            process = core.launch(
                minecraft_version,
                profile.minecraft_nick,
                int(self.config.get("memory", 4096)),
                (minecraft_server) if self.config.get("auto_join", True) else "",
                loader,
                loader_version,
                java_path=self.config.get("java_path", ""),
                java_required_major=server.java_major,
                ticket_supplier=issue_ticket,
            )
            self.game_process = process
            self.bridge.finished.emit(process.pid)
            return_code = process.wait()
            launch_log(f"Minecraft завершён с кодом {return_code}")
            log_handle = getattr(process, "_nexus_log_handle", None)
            if log_handle:
                log_handle.close()
            self.bridge.game_exited.emit(return_code)
        except Exception as error:
            self.bridge.failed.emit(str(error))

    def _set_status(self, text):
        self.status.setText(text)
        if hasattr(self, "catalog_status"):
            self.catalog_status.setText(text)

    def _progress(self, done, total):
        for progress in (self.progress, getattr(self, "catalog_progress", None)):
            if progress:
                progress.setMaximum(max(total, 1))
                progress.setValue(done)

    def _reset_play(self):
        self.game_process = None
        self.stop_requested = False
        access = self.build_access.get(self.current_server.id, {}) if self.current_server else {}
        allowed = not access or bool(access.get("allowed", False))
        self.play.setEnabled(allowed)
        self.progress.hide()
        if hasattr(self, "catalog_play"):
            self.catalog_play.setEnabled(allowed)
            self.catalog_play.setText(("ИГРАТЬ" if self.private_ui else "▶  ИГРАТЬ") if allowed else "ДОСТУП ЗАКРЫТ")
            if self.private_ui:
                self.catalog_play.setIcon(nexus_button_icon(4 if allowed else 6))
            self.catalog_progress.hide()

    def _launched(self, pid):
        self._set_status(f"Игра запущена • PID {pid}")
        self.play.setEnabled(True)
        self.play.setText("■  ОСТАНОВИТЬ")
        if hasattr(self, "catalog_play"):
            self.catalog_play.setEnabled(True)
            self.catalog_play.setText("■  ОСТАНОВИТЬ")
            if self.private_ui:
                self.catalog_play.setText("ОСТАНОВИТЬ")
                self.catalog_play.setIcon(nexus_button_icon(7))
            self.catalog_progress.hide()

    def _stop_game(self):
        process = self.game_process
        if not process or process.poll() is not None:
            self._reset_play()
            return
        self.stop_requested = True
        self.play.setEnabled(False)
        if hasattr(self, "catalog_play"):
            self.catalog_play.setEnabled(False)
            self.catalog_play.setText("ОСТАНОВКА…")
            if self.private_ui:
                self.catalog_play.setIcon(nexus_button_icon(0))
        self._set_status("Останавливаю Minecraft…")
        threading.Thread(target=self._stop_game_worker, args=(process,), daemon=True).start()

    def _stop_game_worker(self, process):
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                    **hidden_process_kwargs(),
                )
            else:
                process.terminate()
                process.wait(timeout=10)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    def _game_exited(self, return_code):
        stopped_by_user = self.stop_requested
        self._reset_play()
        if stopped_by_user:
            self._set_status("Minecraft остановлен пользователем")
        elif return_code == 0:
            self._set_status("Готов к запуску")
        else:
            self._set_status(f"Minecraft завершился с ошибкой • код {return_code}")
            QMessageBox.critical(
                self,
                "NEXUS Launcher",
                "Minecraft завершился с ошибкой.\n"
                f"Лог: {self._instance_dir() / '.nexus-launcher' / 'logs' / 'minecraft-launch.log'}",
            )

    def _failed(self, text):
        self._reset_play()
        QMessageBox.critical(self, "NEXUS Launcher", text)


def main():
    if "--apply-update" in sys.argv:
        from nexus_launcher.launcher_update_job import apply_update
        from nexus_launcher.safe_paths import checked_path

        operation = Path(sys.argv[sys.argv.index("--apply-update") + 1]).absolute()
        update_root = app_data_dir() / "updates"
        relative = operation.relative_to(update_root.absolute()).as_posix()
        operation = checked_path(update_root, relative)
        if operation.parent != update_root.absolute():
            raise ValueError("Неверная папка операции обновления")
        apply_update(operation)
        return 0
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName("NEXUS Launcher")
    app.setApplicationDisplayName("NEXUS Launcher")
    app.setDesktopFileName(WINDOWS_APP_ID)
    app.setWindowIcon(QIcon(str(resource("icon.png"))))
    if "--smoke-test" in sys.argv:
        # Packaging check only: no account, network, update or game workers.
        pixmap = QPixmap(str(resource("icon.png")))
        if pixmap.isNull():
            return 2
        preview = QLabel("NEXUS packaging smoke test")
        preview.setPixmap(pixmap)
        preview.show()
        app.processEvents()
        preview.close()
        return 0
    if getattr(sys, "frozen", False) and sys.platform == "win32" and "--update-health" not in sys.argv:
        from nexus_launcher.launcher_update_job import resume_interrupted_update

        try:
            if resume_interrupted_update(Path(sys.executable)):
                return 0
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.critical(None, "Восстановление NEXUS", str(error))
            return 1
    splash_pixmap = QPixmap(520, 210)
    splash_pixmap.fill(QColor("#0b1220"))
    splash = QSplashScreen(splash_pixmap)
    splash.setWindowFlag(Qt.FramelessWindowHint)
    splash.show()

    def update_progress(text, done, total):
        suffix = f"  {int(done * 100 / total)}%" if total else ""
        splash.showMessage(f"NEXUS\n\n{text}{suffix}", Qt.AlignCenter, QColor("#f4f7fb"))
        app.processEvents()

    if not os.environ.get("NEXUS_DISABLE_SELF_UPDATE") and try_startup_update(update_progress):
        sys.exit(0)
    splash.close()
    window = Launcher()
    window.show()
    if "--update-health" in sys.argv:
        from nexus_launcher.safe_paths import checked_path

        marker = Path(sys.argv[sys.argv.index("--update-health") + 1]).absolute()
        update_root = app_data_dir() / "updates"
        relative = marker.relative_to(update_root.absolute()).as_posix()
        if marker.name != "healthy":
            raise ValueError("Неверный marker обновления")
        checked_path(update_root, relative).write_text("ready")
    import nexus_launcher.self_update as self_update

    if self_update.startup_release and self_update.startup_release.envelope:
        from nexus_launcher.update_dialog import UpdateDialog

        dialog = UpdateDialog(window, self_update.startup_release)
        if dialog.exec() == QDialog.Accepted:
            return 0
    elif self_update.startup_release:
        answer = QMessageBox.question(
            window,
            "Обновление NEXUS Launcher",
            f"Доступна версия {self_update.startup_release.version}.\n"
            "Установка выполняется вручную. Открыть официальный сайт?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            webbrowser.open(self_update.DOWNLOAD_PAGE)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
