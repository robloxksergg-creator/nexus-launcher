from __future__ import annotations

from pathlib import Path
import os
import weakref
from urllib.parse import urlparse
from shiboken6 import isValid

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .models import WorldPresentation, WorldView


class FocusVisibleTracker(QObject):
    """Qt equivalent of :focus-visible, scoped to one launcher window."""

    _KEYBOARD_REASONS = {
        Qt.TabFocusReason,
        Qt.BacktabFocusReason,
        Qt.ShortcutFocusReason,
    }

    def __init__(self, root: QWidget):
        super().__init__(root)
        self.root = root
        self._tracked = weakref.WeakSet()

    def track_tree(self, root):
        for widget in (root, *root.findChildren(QWidget)):
            if isValid(widget) and widget not in self._tracked:
                self._tracked.add(widget)
                widget.installEventFilter(self)

    def stop(self):
        for widget in tuple(self._tracked):
            if isValid(widget):
                widget.removeEventFilter(self)
        self._tracked.clear()

    def _belongs_to_root(self, widget: QWidget) -> bool:
        current = widget
        while current is not None:
            if not isValid(current):
                return False
            if current is self.root:
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _set_visible(widget: QWidget, visible: bool) -> None:
        if widget.property("focusVisible") is visible:
            return
        widget.setProperty("focusVisible", visible)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def eventFilter(self, watched, event):
        # DeferredDelete/child/style events can arrive during C++ destruction.
        # Never traverse widget parents for events unrelated to focus visibility.
        kind = event.type()
        if kind == QEvent.ChildPolished:
            child = event.child()
            if isValid(child) and isinstance(child, QWidget):
                self.track_tree(child)
            return False
        if kind not in {QEvent.FocusIn, QEvent.FocusOut, QEvent.MouseButtonPress, QEvent.TouchBegin}:
            return False
        if not isValid(watched) or not isValid(self.root):
            return False
        if isinstance(watched, QWidget) and watched in self._tracked:
            if kind == QEvent.FocusIn:
                self._set_visible(watched, event.reason() in self._KEYBOARD_REASONS)
            else:
                self._set_visible(watched, False)
        return False


def cropped(source: QPixmap, size: QSize) -> QPixmap:
    if source.isNull() or size.width() <= 0 or size.height() <= 0:
        return source
    scaled = source.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - size.width()) // 2)
    y = max(0, (scaled.height() - size.height()) // 2)
    return scaled.copy(x, y, size.width(), size.height())


class CoverLabel(QLabel):
    def __init__(self, path: str = "", parent=None):
        super().__init__(parent)
        self._source = QPixmap(path) if path else QPixmap()
        self._zoom = 1.0
        self.setMinimumSize(1, 1)
        self.setAlignment(Qt.AlignCenter)

    def set_path(self, path: str) -> None:
        self._source = QPixmap(path) if path else QPixmap()
        self._refresh()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(1.0, min(float(zoom), 1.04))
        self._refresh()

    def has_image(self) -> bool:
        return not self._source.isNull()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        if not self._source.isNull():
            target = QSize(max(1, round(self.width() * self._zoom)), max(1, round(self.height() * self._zoom)))
            enlarged = cropped(self._source, target)
            x = max(0, (enlarged.width() - self.width()) // 2)
            y = max(0, (enlarged.height() - self.height()) // 2)
            self.setPixmap(enlarged.copy(x, y, self.width(), self.height()))
        else:
            self.clear()


class HeroMedia(QWidget):
    """One active poster/video surface; release() ceases media I/O."""

    video_ready = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#08111c;")
        self.presentation: WorldPresentation | None = None
        self.poster = CoverLabel(parent=self)
        self.video = QVideoWidget(self)
        self.video.setAspectRatioMode(Qt.KeepAspectRatioByExpanding)
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.poster)
        self.stack.addWidget(self.video)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QMediaPlayer.Infinite)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._media_error)
        self.video_opacity = QGraphicsOpacityEffect(self.video)
        self.video.setGraphicsEffect(self.video_opacity)
        self.video_opacity.setOpacity(0.0)
        self.fade = QPropertyAnimation(self.video_opacity, b"opacity", self)
        self.fade.setDuration(420)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.reduced_motion = False
        self.autoplay_enabled = True
        self.user_paused = False
        self.stack.setCurrentWidget(self.poster)

    def set_presentation(self, presentation: WorldPresentation, autoplay: bool = True) -> None:
        self.release()
        self.presentation = presentation.validate()
        self.autoplay_enabled = bool(autoplay)
        self.user_paused = False
        poster = presentation.image if presentation.type == "image" else presentation.poster
        if not poster:
            poster = presentation.fallback_image
        self.poster.set_path(self._local_path(poster))
        if not self.poster.has_image() and presentation.fallback_image and presentation.fallback_image != poster:
            self.poster.set_path(self._local_path(presentation.fallback_image))
        self.video_opacity.setOpacity(0.0)
        self.stack.setCurrentWidget(self.poster)
        if presentation.type != "video":
            self.video_ready.emit(False)
            return
        self.player.setVideoOutput(self.video)
        self.player.setSource(self._url(presentation.video))
        if autoplay:
            self.player.play()

    def release(self) -> None:
        self.fade.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.stack.setCurrentWidget(self.poster)
        self.video_ready.emit(False)

    def pause(self, by_user: bool = False) -> None:
        if by_user:
            self.user_paused = True
        self.player.pause()

    def resume(self, automatic: bool = False) -> None:
        if automatic and (self.user_paused or not self.autoplay_enabled):
            return
        if self.presentation and self.presentation.type == "video" and not self.player.source().isEmpty():
            if not automatic:
                self.user_paused = False
            self.player.play()

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.pause(by_user=True)
        else:
            self.resume(automatic=False)

    def set_muted(self, muted: bool) -> None:
        self.audio.setMuted(muted)

    def set_reduced_motion(self, reduced: bool) -> None:
        self.reduced_motion = bool(reduced)

    def _media_status(self, status) -> None:
        if status in {QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia} and self.player.hasVideo():
            self.stack.setCurrentWidget(self.video)
            self.fade.stop()
            if self.reduced_motion:
                self.video_opacity.setOpacity(1.0)
            else:
                self.fade.setStartValue(0.0)
                self.fade.setEndValue(1.0)
                self.fade.start()
            self.video_ready.emit(True)
        elif status == QMediaPlayer.InvalidMedia:
            self._media_error()

    def _media_error(self, *_args) -> None:
        self.stack.setCurrentWidget(self.poster)
        if self.presentation and not self.poster.has_image() and self.presentation.fallback_image:
            self.poster.set_path(self._local_path(self.presentation.fallback_image))
        self.video_ready.emit(False)

    @staticmethod
    def _local_path(value: str) -> str:
        parsed = urlparse(value)
        return value if parsed.scheme else str(Path(value))

    @staticmethod
    def _url(value: str) -> QUrl:
        parsed = urlparse(value)
        return QUrl(value) if parsed.scheme in {"https", "http", "file"} else QUrl.fromLocalFile(str(Path(value)))


class RailButton(QToolButton):
    def __init__(self, text: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(tooltip)
        self.setProperty("dataActive", False)
        self.setProperty("ariaCurrent", "false")
        self.tooltip_title = tooltip.splitlines()[0]
        self.tooltip_status = "\n".join(tooltip.splitlines()[1:])
        self.update_available = False
        self.tooltip_text = tooltip
        self.setAccessibleName(self.tooltip_title)
        self.setFixedSize(48, 48)
        self.setCursor(Qt.PointingHandCursor)
        self.status_dot = QLabel(self)
        self.status_dot.setObjectName("railStatusDot")
        self.status_dot.setProperty("state", "unavailable")
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.hide()
        self.status_dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.update_badge = QLabel("", self)
        self.update_badge.setObjectName("railUpdateBadge")
        self.update_badge.setFixedSize(10, 10)
        self.update_badge.hide()
        self.update_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.progress_badge = QLabel("", self)
        self.progress_badge.setObjectName("railProgressBadge")
        self.progress_badge.setAlignment(Qt.AlignCenter)
        self.progress_badge.setFixedSize(25, 16)
        self.progress_badge.hide()
        self.progress_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.notification_badge = QLabel("", self)
        self.notification_badge.setObjectName("railNotificationBadge")
        self.notification_badge.setFixedSize(8, 8)
        self.notification_badge.hide()
        self.notification_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.tooltip_timer = QTimer(self)
        self.tooltip_timer.setSingleShot(True)
        self.tooltip_timer.setInterval(275)
        self.tooltip_timer.timeout.connect(self._show_tooltip)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.status_dot.move(4, self.height() - 14)
        self.update_badge.move(self.width() - 13, 4)
        self.progress_badge.move(self.width() - 27, self.height() - 18)
        self.notification_badge.move(self.width() - 11, 5)

    def enterEvent(self, event):
        self.tooltip_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.tooltip_timer.stop()
        QToolTip.hideText()
        super().leaveEvent(event)

    def _show_tooltip(self):
        if self.underMouse():
            QToolTip.showText(self.mapToGlobal(QPoint(self.width() + 10, 7)), self.tooltip_text, self)

    def set_tooltip(self, text: str) -> None:
        parts = text.splitlines()
        self.tooltip_title = parts[0]
        self.tooltip_status = "\n".join(parts[1:])
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        lines = [self.tooltip_title]
        if self.tooltip_status:
            lines.append(self.tooltip_status)
        if self.update_available:
            lines.append("● Доступно обновление")
        self.tooltip_text = "\n".join(lines)
        self.setAccessibleName(self.tooltip_title)

    def set_status(self, state: str) -> None:
        self.status_dot.show()
        self.status_dot.setProperty("state", state)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

    def set_update_available(self, available: bool) -> None:
        self.update_available = bool(available)
        self.update_badge.setVisible(self.update_available)
        self._refresh_tooltip()

    def set_download_progress(self, percent: int | None) -> None:
        if percent is None:
            self.progress_badge.hide()
            return
        self.progress_badge.setText(str(max(0, min(99, int(percent)))))
        self.progress_badge.show()

    def set_notification(self, visible: bool) -> None:
        self.notification_badge.setVisible(bool(visible))

    def set_active(self, active: bool) -> None:
        self.setProperty("dataActive", bool(active))
        self.setProperty("ariaCurrent", "page" if active else "false")
        self.setAccessibleDescription("Текущий раздел" if active else "")
        self.style().unpolish(self)
        self.style().polish(self)


class WorldRail(QFrame):
    support_requested = Signal()
    home_requested = Signal()
    worlds_requested = Signal()
    library_requested = Signal()
    studio_requested = Signal()
    news_requested = Signal()
    downloads_requested = Signal()
    settings_requested = Signal()
    add_requested = Signal()
    world_requested = Signal(object)
    world_menu_requested = Signal(object, object)

    def __init__(self, worlds: list[WorldView], pinned: list[str], icons: dict | None = None, parent=None):
        super().__init__(parent)
        icons = icons or {}
        self.setObjectName("worldRail")
        self.setFixedWidth(76)
        self.buttons: dict[str, RailButton] = {}
        self.section_buttons: dict[str, RailButton] = {}
        self.selectedWorldId = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(13, 14, 13, 12)
        root.setSpacing(9)
        nexus = RailButton("◇", "NEXUS — Главная")
        nexus.setObjectName("nexusRailButton")
        nexus.clicked.connect(self.home_requested)
        if icons.get("home"):
            nexus.setText("")
            nexus.setIcon(icons["home"])
            nexus.setIconSize(QSize(25, 25))
        root.addWidget(nexus)
        self.section_buttons["home"] = nexus
        worlds_button = RailButton("⌕", "Каталог миров")
        worlds_button.clicked.connect(self.worlds_requested)
        if icons.get("worlds"):
            worlds_button.setText("")
            worlds_button.setIcon(icons["worlds"])
            worlds_button.setIconSize(QSize(25, 25))
        root.addWidget(worlds_button)
        self.section_buttons["worlds"] = worlds_button
        separator = QFrame()
        separator.setObjectName("railSeparator")
        separator.setFixedHeight(1)
        root.addWidget(separator)
        for world in worlds:
            if world.id not in pinned:
                continue
            button = RailButton(world.short_name, world.title)
            button.clicked.connect(lambda _checked=False, item=world: self.world_requested.emit(item))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda point, item=world, control=button: self.world_menu_requested.emit(item, control.mapToGlobal(point))
            )
            root.addWidget(button)
            self.buttons[world.id] = button
        add = RailButton("+", "Добавить в NEXUS")
        add.clicked.connect(self.add_requested)
        root.addWidget(add)
        root.addStretch()
        for route, text, tip, signal in (
            ("library", "▦", "Мои сборки", self.library_requested),
            ("studio", "S", "Nexus Studio", self.studio_requested),
            ("downloads", "↓", "Загрузки", self.downloads_requested),
            ("news", "N", "Новости", self.news_requested),
            ("support", "?", "Поддержка", self.support_requested),
            ("settings", "⚙", "Настройки", self.settings_requested),
        ):
            button = RailButton(text, tip)
            if icons.get(route):
                button.setText("")
                button.setIcon(icons[route])
                button.setIconSize(QSize(25, 25))
            button.clicked.connect(signal)
            root.addWidget(button)
            self.section_buttons[route] = button

    def select_world(self, world_id: str) -> None:
        self.select_route("world" if world_id else "", world_id)

    def select_route(self, route: str, world_id: str = "") -> None:
        self.selectedWorldId = world_id if route == "world" else ""
        self.setProperty("selectedWorldId", self.selectedWorldId)
        for identifier, button in self.buttons.items():
            button.set_active(route == "world" and identifier == world_id)
        for identifier, button in self.section_buttons.items():
            button.set_active(identifier == route)

    def set_status(self, world_id: str, state: str, current: int = 0, maximum: int = 0) -> None:
        button = self.buttons.get(world_id)
        if not button:
            return
        labels = {"online": "Онлайн", "offline": "Офлайн", "unavailable": "Статус недоступен", "maintenance": "Технические работы", "development": "В разработке", "closed": "Доступ закрыт"}
        label = labels.get(state, labels["unavailable"])
        players = f" · {current}/{maximum}" if state == "online" and maximum else ""
        button.set_tooltip(f"{button.accessibleName()}\n● {label}{players}")
        button.set_status(state)
        button.setProperty("worldStatus", state)
        button.style().unpolish(button)
        button.style().polish(button)

    def set_update_available(self, world_id: str, available: bool) -> None:
        button = self.buttons.get(world_id)
        if button:
            button.set_update_available(available)

    def set_download_progress(self, world_id: str, done: int, total: int) -> None:
        button = self.buttons.get(world_id)
        if button:
            button.set_download_progress(None if total <= 0 else int(done * 100 / total))


class TitleBar(QFrame):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.drag_origin: QPoint | None = None
        self.setObjectName("platformTitleBar")
        self.setFixedHeight(58)
        row = QHBoxLayout(self)
        row.setContentsMargins(22, 0, 10, 0)
        self.context = QLabel("NEXUS / DISCOVER")
        self.context.setObjectName("titleContext")
        row.addWidget(self.context)
        row.addStretch()
        self.profile = QPushButton("Войти")
        self.profile.setObjectName("accountButton")
        self.profile.clicked.connect(window._profile_menu)
        row.addWidget(self.profile)
        self.minimum = QPushButton("—")
        self.maximum = QPushButton("□")
        self.close = QPushButton("×")
        for button in (self.minimum, self.maximum, self.close):
            button.setObjectName("windowControl")
            button.setFixedSize(43, 40)
        self.close.setProperty("closeControl", True)
        self.minimum.clicked.connect(window.showMinimized)
        self.maximum.clicked.connect(window._toggle_max)
        self.close.clicked.connect(window.close)
        row.addWidget(self.minimum)
        row.addWidget(self.maximum)
        row.addWidget(self.close)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_origin = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_origin is not None and event.buttons() & Qt.LeftButton and not self.window.isMaximized():
            self.window.move(event.globalPosition().toPoint() - self.drag_origin)

    def mouseReleaseEvent(self, event):
        self.drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.window._toggle_max()
        super().mouseDoubleClickEvent(event)


class PlatformStatusBar(QFrame):
    downloads_requested = Signal()

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setObjectName("platformStatusBar")
        self.setFixedHeight(34)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 18, 0)
        row.setSpacing(18)
        channel = "PRIVATE · STAGING" if os.environ.get("NEXUS_ENVIRONMENT") == "staging" else "PRIVATE"
        self.version = QLabel(f"NEXUS {version} · {channel}")
        self.network = QLabel("● Сервисы: проверка")
        self.java = QLabel("Java: проверка")
        self.download = QPushButton("")
        self.download.setObjectName("downloadIndicator")
        self.download.hide()
        self.download.clicked.connect(self.downloads_requested)
        row.addWidget(self.version)
        row.addWidget(self.network)
        row.addWidget(self.java)
        row.addStretch()
        row.addWidget(self.download)

    def set_download(self, label: str, done: int, total: int, speed: float = 0.0) -> None:
        if total <= 0:
            self.download.hide()
            return
        percent = max(0, min(100, int(done * 100 / total)))
        speed_text = ""
        if speed > 0:
            value = speed / 1048576
            speed_text = f" · {value:.1f} МБ/с"
        self.download.setText(f"↓ {label} · {percent}%{speed_text}")
        self.download.show()
