from __future__ import annotations

import os
import platform
import re
import time
from pathlib import Path

import PySide6

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from .models import WorldPresentation, WorldView
from .widgets import CoverLabel, HeroMedia


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionTitle")
    return label


class WorldTile(QPushButton):
    opened = Signal(object)

    def __init__(self, world: WorldView, compact: bool = False, parent=None):
        super().__init__(parent)
        self.world = world
        self.compact = compact
        self.setObjectName("worldTile")
        self.setCursor(Qt.PointingHandCursor)
        if compact:
            self.setFixedHeight(116)
        else:
            self.setMinimumHeight(166)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.art = CoverLabel(world.presentation.image or world.presentation.poster)
        self.art.setFixedWidth(124 if compact else 220)
        root.addWidget(self.art)
        text = QVBoxLayout()
        text.setContentsMargins(18, 17, 18, 15)
        eyebrow = QLabel(world.season)
        eyebrow.setObjectName("eyebrow")
        title = QLabel(world.title)
        title.setObjectName("tileTitle")
        self.title_label = title
        description = QLabel(world.description)
        description.setObjectName("muted")
        description.setWordWrap(True)
        description.setVisible(not compact)
        self.status = QLabel("● СТАТУС НЕДОСТУПЕН")
        self.status.setObjectName("worldStatus")
        text.addWidget(eyebrow)
        text.addWidget(title)
        text.addWidget(description)
        text.addStretch()
        text.addWidget(self.status)
        root.addLayout(text, 1)
        self.arrow = QLabel("→")
        self.arrow.setObjectName("tileArrow")
        self.arrow.setAlignment(Qt.AlignCenter)
        self.arrow.setFixedWidth(30)
        self.arrow.setVisible(False)
        root.addWidget(self.arrow)
        self.hover_animation = QVariantAnimation(self)
        self.hover_animation.setDuration(180)
        self.hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.hover_animation.valueChanged.connect(lambda value: self.art.set_zoom(float(value)))
        self.reduced_motion = False
        self.clicked.connect(lambda: self.opened.emit(self.world))

    def enterEvent(self, event):
        self.arrow.show()
        self._animate_zoom(1.02)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.arrow.hide()
        self._animate_zoom(1.0)
        super().leaveEvent(event)

    def _animate_zoom(self, target: float) -> None:
        if self.reduced_motion:
            self.art.set_zoom(target)
            return
        self.hover_animation.stop()
        self.hover_animation.setStartValue(self.art._zoom)
        self.hover_animation.setEndValue(target)
        self.hover_animation.start()

    def set_reduced_motion(self, reduced: bool) -> None:
        self.reduced_motion = bool(reduced)

    def set_status(self, ok: bool, current: int, maximum: int) -> None:
        if ok:
            self.status.setText(f"● ОНЛАЙН · {current}/{maximum}" if maximum else "● ОНЛАЙН")
            self.status.setProperty("online", True)
        else:
            self.status.setText("● СТАТУС НЕДОСТУПЕН")
            self.status.setProperty("online", False)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # Compatibility with the existing access/status update pipeline.
    def set_online(self, online: bool) -> None:
        self.set_status(online, 0, 0)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_access(self, mode, allowed) -> None:
        # Access controls launching, not browsing.  A closed or maintenance
        # world must still open so its status, news and files remain visible.
        self.setProperty("launchAllowed", bool(allowed))
        self.setProperty("accessMode", str(mode).upper())
        access_mode = str(mode).upper()
        if access_mode == "MAINTENANCE":
            self.status.setText("● ТЕХНИЧЕСКИЕ РАБОТЫ")
            self.status.setProperty("online", False)
        elif access_mode == "CLOSED":
            self.status.setText("● ДОСТУП ЗАКРЫТ")
            self.status.setProperty("online", False)
        self.style().unpolish(self)
        self.style().polish(self)


class DiscoverPage(QWidget):
    world_requested = Signal(object)

    def __init__(self, worlds: list[WorldView], recent_ids: list[str], reduced_motion: bool = False, parent=None):
        super().__init__(parent)
        self.worlds = worlds
        self.tiles: dict[str, list[WorldTile]] = {}
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setMaximumWidth(1760)
        root = QVBoxLayout(host)
        root.setContentsMargins(32, 24, 32, 40)
        root.setSpacing(16)
        featured = worlds[0] if worlds else None
        hero = self._featured(featured) if featured else QFrame()
        root.addWidget(hero)
        recent = []
        seen = set()
        for identifier in recent_ids:
            world = next((item for item in worlds if item.id == identifier), None)
            if world and world.id not in seen:
                recent.append(world)
                seen.add(world.id)
            if len(recent) == 3:
                break
        if recent:
            root.addWidget(section_title("Продолжить"))
            row = QHBoxLayout()
            row.setSpacing(12)
            for world in recent:
                tile = WorldTile(world, compact=True)
                tile.set_reduced_motion(reduced_motion)
                tile.opened.connect(self.world_requested)
                row.addWidget(tile, 1)
                self.tiles.setdefault(world.id, []).append(tile)
            row.addStretch()
            root.addLayout(row)
        excluded = {featured.id} if featured else set()
        excluded.update(world.id for world in recent)
        new_worlds = [world for world in worlds if world.id not in excluded][:4]
        if new_worlds:
            root.addWidget(section_title("Новое в NEXUS"))
            grid = QGridLayout()
            grid.setSpacing(12)
            for index, world in enumerate(new_worlds):
                tile = WorldTile(world, compact=True)
                tile.set_reduced_motion(reduced_motion)
                tile.opened.connect(self.world_requested)
                grid.addWidget(tile, index // 2, index % 2)
                self.tiles.setdefault(world.id, []).append(tile)
            root.addLayout(grid)
        root.addWidget(section_title("События"))
        event = QFrame()
        event.setObjectName("contentCard")
        event_layout = QHBoxLayout(event)
        event_layout.setContentsMargins(16, 12, 16, 12)
        event_title = QLabel("GEARMORPH · SEASON II")
        event_title.setObjectName("cardTitle")
        event_copy = QLabel("Технический сезон и развитие индустриальных государств")
        event_copy.setObjectName("muted")
        event_layout.addWidget(event_title)
        event_layout.addSpacing(16)
        event_layout.addWidget(event_copy, 1)
        root.addWidget(event)
        root.addWidget(section_title("Новости NEXUS"))
        news = QFrame()
        news.setObjectName("contentCard")
        news_layout = QHBoxLayout(news)
        for title, body in (
            ("GLOBAL UPDATE", "Новая платформа миров доступна в приватном тестовом канале."),
            ("GEARMORPH", "Season II: технологии, аэронатика и развитие государств."),
            ("LAUNCHER", "Проверка файлов, подписи и безопасный rollback сохранены."),
        ):
            block = QVBoxLayout()
            head = QLabel(title)
            head.setObjectName("cardTitle")
            copy = QLabel(body)
            copy.setObjectName("muted")
            copy.setWordWrap(True)
            block.addWidget(head)
            block.addWidget(copy)
            news_layout.addLayout(block, 1)
        root.addWidget(news)
        root.addStretch()
        scroll.setWidget(host)
        scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def _featured(self, world: WorldView) -> QFrame:
        frame = QFrame()
        frame.setObjectName("featuredWorld")
        frame.setMinimumHeight(310)
        stack = QStackedLayout(frame)
        stack.setStackingMode(QStackedLayout.StackAll)
        art = CoverLabel(world.presentation.image or world.presentation.poster)
        stack.addWidget(art)
        overlay = QFrame()
        overlay.setObjectName("featuredOverlay")
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.addWidget(section_title("Featured world"))
        layout.addStretch()
        season = QLabel(world.season)
        season.setObjectName("eyebrow")
        title = QLabel(world.title)
        title.setObjectName("featuredTitle")
        description = QLabel(world.description)
        description.setObjectName("featuredDescription")
        button = QPushButton("ОТКРЫТЬ МИР  →")
        button.setObjectName("primaryAction")
        button.setFixedWidth(210)
        button.clicked.connect(lambda: self.world_requested.emit(world))
        layout.addWidget(season)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addSpacing(8)
        layout.addWidget(button)
        stack.addWidget(overlay)
        stack.setCurrentWidget(overlay)
        return frame

    def update_status(self, world_id: str, ok: bool, current: int, maximum: int) -> None:
        for tile in self.tiles.get(world_id, []):
            tile.set_status(ok, current, maximum)

    def set_selected(self, world_id: str) -> None:
        for identifier, tiles in self.tiles.items():
            for tile in tiles:
                tile.set_selected(identifier == world_id)


class WorldPage(QWidget):
    play_requested = Signal()
    menu_requested = Signal(object)
    video_muted_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.world: WorldView | None = None
        stack = QStackedLayout(self)
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)
        self.media = HeroMedia()
        stack.addWidget(self.media)
        overlay = QFrame()
        overlay.setObjectName("worldOverlay")
        root = QVBoxLayout(overlay)
        root.setContentsMargins(46, 34, 46, 42)
        controls = QHBoxLayout()
        controls.addStretch()
        self.pause = QPushButton("Ⅱ")
        self.mute = QPushButton("🔇")
        for button in (self.pause, self.mute):
            button.setObjectName("mediaControl")
            button.setFixedSize(40, 40)
            button.hide()
        self.pause.clicked.connect(self.media.toggle_playback)
        self.mute.clicked.connect(self._toggle_mute)
        controls.addWidget(self.pause)
        controls.addWidget(self.mute)
        root.addLayout(controls)
        root.addStretch()
        self.season = QLabel()
        self.season.setObjectName("worldSeason")
        self.title = QLabel()
        self.title.setObjectName("worldTitle")
        self.description = QLabel()
        self.description.setObjectName("worldDescription")
        self.description.setWordWrap(True)
        self.description.setMaximumWidth(680)
        self.status = QLabel("● СТАТУС НЕДОСТУПЕН")
        self.status.setObjectName("heroStatus")
        self.meta = QLabel()
        self.meta.setObjectName("heroMeta")
        root.addWidget(self.season)
        root.addWidget(self.title)
        root.addWidget(self.description)
        root.addSpacing(10)
        root.addWidget(self.status)
        root.addWidget(self.meta)
        actions = QHBoxLayout()
        self.play = QPushButton("ИГРАТЬ")
        self.play.setObjectName("heroPlay")
        self.play.setMinimumSize(240, 58)
        self.play.clicked.connect(self.play_requested)
        menu = QPushButton("•••")
        menu.setObjectName("heroMenu")
        menu.setFixedSize(62, 58)
        menu.clicked.connect(lambda: self.menu_requested.emit(menu))
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(260)
        self.progress.hide()
        actions.addWidget(self.play)
        actions.addWidget(menu)
        actions.addWidget(self.progress)
        actions.addStretch()
        root.addSpacing(16)
        root.addLayout(actions)
        self.client_status = QLabel("Готов к запуску")
        self.client_status.setObjectName("clientStatus")
        root.addWidget(self.client_status)
        stack.addWidget(overlay)
        stack.setCurrentWidget(overlay)
        self.media.video_ready.connect(self._video_ready)
        self.media.player.playbackStateChanged.connect(self._playback_state)

    def set_world(self, world: WorldView, muted: bool = True, video_enabled: bool = True) -> None:
        self.world = world
        self.season.setText(world.season)
        self.title.setText(world.title)
        self.description.setText(world.description)
        loader = {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric", "quilt": "Quilt", "vanilla": "Vanilla"}.get(world.server.loader.lower(), world.server.loader)
        self.meta.setText(f"Minecraft {world.server.minecraft_version}  ·  {loader}")
        accent = QColor(world.theme.accent)
        foreground = world.theme.accent_foreground
        hover = accent.lighter(112).name()
        pressed = accent.darker(118).name()
        self.play.setStyleSheet(f"""
            QPushButton#heroPlay {{ background:{accent.name()}; color:{foreground}; border:1px solid {hover}; font-weight:800; letter-spacing:1px; }}
            QPushButton#heroPlay:hover {{ background:{hover}; }}
            QPushButton#heroPlay:pressed {{ background:{pressed}; }}
            QPushButton#heroPlay:disabled {{ background:#17202b; color:#6f7c8d; border-color:#2a3645; }}
            QPushButton#heroPlay[focusVisible="true"] {{ border:2px solid #ffffff; }}
        """)
        self.media.set_muted(muted)
        self.mute.setText("🔇" if muted else "🔊")
        presentation = world.presentation
        if presentation.type == "video" and not video_enabled:
            image = presentation.poster or presentation.fallback_image
            presentation = WorldPresentation(type="image", image=image)
        self.media.set_presentation(presentation)
        is_video = world.presentation.type == "video" and video_enabled
        self.pause.setVisible(is_video)
        self.mute.setVisible(is_video)

    def set_reduced_motion(self, reduced: bool) -> None:
        self.media.set_reduced_motion(reduced)

    def set_server_status(self, status: str, current: int = 0, maximum: int = 0) -> None:
        labels = {
            "online": f"● ОНЛАЙН · {current}/{maximum}" if maximum else "● ОНЛАЙН",
            "offline": "● ОФЛАЙН",
            "maintenance": "● ТЕХНИЧЕСКИЕ РАБОТЫ",
            "development": "● В РАЗРАБОТКЕ",
            "closed": "● ДОСТУП ЗАКРЫТ",
            "unavailable": "● СТАТУС НЕДОСТУПЕН",
        }
        self.status.setText(labels.get(status, labels["unavailable"]))
        self.status.setProperty("state", status)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def release(self) -> None:
        self.media.release()

    def _toggle_mute(self):
        muted = not self.media.audio.isMuted()
        self.media.set_muted(muted)
        self.mute.setText("🔇" if muted else "🔊")
        self.video_muted_changed.emit(muted)

    def _video_ready(self, ready: bool):
        if ready:
            self.client_status.setText("Видео загружено")

    def _playback_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        self.pause.setText("Ⅱ" if state == QMediaPlayer.PlayingState else "▶")


class WorldsCatalogue(QWidget):
    world_requested = Signal(object)

    def __init__(self, worlds: list[WorldView], reduced_motion: bool = False, parent=None):
        super().__init__(parent)
        self.worlds = worlds
        self.tiles: dict[str, WorldTile] = {}
        self._columns = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 24, 34, 30)
        header = QLabel("МИРЫ")
        header.setObjectName("pageTitle")
        root.addWidget(header)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти мир")
        self.search.setMaximumWidth(620)
        self.search.textChanged.connect(self._filter)
        filters.addWidget(self.search, 1)
        self.category_value = "ВСЕ"
        self.category_chips = {}
        for label, value in (("Все", "ВСЕ"), ("Tech", "TECH"), ("RPG", "RPG"), ("Vanilla", "VANILLA"), ("Adventure", "ADVENTURE")):
            chip = QPushButton(label)
            chip.setObjectName("filterChip")
            chip.setProperty("dataActive", value == self.category_value)
            chip.clicked.connect(lambda _checked=False, category=value: self._select_category(category))
            filters.addWidget(chip)
            self.category_chips[value] = chip
        filters.addStretch()
        root.addLayout(filters)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setMaximumWidth(1680)
        self.grid_host = host
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 12, 8, 12)
        self.grid.setSpacing(14)
        self.ordered_tiles = []
        for world in worlds:
            tile = WorldTile(world)
            tile.set_reduced_motion(reduced_motion)
            tile.opened.connect(self.world_requested)
            tile.setProperty("searchText", f"{world.title} {world.category} {world.description}".lower())
            self.tiles[world.id] = tile
            self.ordered_tiles.append(tile)
        self._reflow(2)
        scroll.setWidget(host)
        scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        root.addWidget(scroll, 1)

    def _select_category(self, category: str) -> None:
        self.category_value = category
        for value, chip in self.category_chips.items():
            chip.setProperty("dataActive", value == category)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        self._filter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = max(1, self.width() - 68)
        columns = 1 if available < 900 else (3 if available >= 1680 else 2)
        self._reflow(columns)

    def _reflow(self, columns: int) -> None:
        columns = max(1, columns)
        if columns == self._columns:
            return
        self._columns = columns
        for tile in self.ordered_tiles:
            self.grid.removeWidget(tile)
        for index, tile in enumerate(self.ordered_tiles):
            self.grid.addWidget(tile, index // columns, index % columns)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)

    def _filter(self, *_args):
        query = self.search.text().strip().lower()
        category = self.category_value
        for world in self.worlds:
            visible = (not query or query in self.tiles[world.id].property("searchText")) and (
                category == "ВСЕ" or world.category == category
            )
            self.tiles[world.id].setVisible(visible)

    def update_status(self, world_id, ok, current, maximum):
        tile = self.tiles.get(world_id)
        if tile:
            tile.set_status(ok, current, maximum)

    def set_selected(self, world_id: str) -> None:
        for identifier, tile in self.tiles.items():
            tile.set_selected(identifier == world_id)


class DownloadsPage(QWidget):
    worlds_requested = Signal()
    retry_requested = Signal(str)
    logs_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 36)
        title = QLabel("ЗАГРУЗКИ")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.states = QStackedWidget()
        self.states.setObjectName("downloadStates")
        self.empty = QWidget()
        empty_box = QVBoxLayout(self.empty)
        empty_box.setContentsMargins(20, 20, 20, 80)
        empty_box.addStretch()
        empty_icon = QLabel("↓")
        empty_icon.setObjectName("emptyIcon")
        empty_icon.setAlignment(Qt.AlignCenter)
        self.empty_title = QLabel("Нет активных загрузок")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_copy = QLabel("Все установленные миры и сборки находятся в актуальном состоянии.")
        empty_copy.setObjectName("muted")
        empty_copy.setAlignment(Qt.AlignCenter)
        empty_copy.setWordWrap(True)
        worlds = QPushButton("ОТКРЫТЬ МИРЫ")
        worlds.setObjectName("primaryAction")
        worlds.setFixedWidth(190)
        worlds.clicked.connect(self.worlds_requested)
        empty_box.addWidget(empty_icon)
        empty_box.addWidget(self.empty_title)
        empty_box.addWidget(empty_copy)
        empty_box.addSpacing(10)
        empty_box.addWidget(worlds, 0, Qt.AlignHCenter)
        empty_box.addStretch()
        self.states.addWidget(self.empty)

        self.active = QFrame()
        self.active.setObjectName("downloadActive")
        self.active.setMaximumWidth(920)
        self.active.setMaximumHeight(320)
        box = QVBoxLayout(self.active)
        box.setContentsMargins(28, 26, 28, 26)
        box.setSpacing(10)
        eyebrow = QLabel("ЗАЩИЩЁННАЯ УСТАНОВКА")
        eyebrow.setObjectName("eyebrow")
        self.name = QLabel("NEXUS")
        self.name.setObjectName("downloadTitle")
        self.detail = QLabel("Подготовка загрузки…")
        self.detail.setObjectName("muted")
        self.bytes = QLabel("")
        self.bytes.setObjectName("downloadBytes")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.percent = QLabel("0%")
        self.percent.setObjectName("downloadPercent")
        box.addWidget(eyebrow)
        box.addWidget(self.name)
        box.addWidget(self.detail)
        box.addWidget(self.bytes)
        self.telemetry = QLabel("Расчёт времени…")
        self.telemetry.setObjectName("muted")
        box.addWidget(self.telemetry)
        box.addWidget(self.progress)
        box.addWidget(self.percent)
        box.addStretch()
        self.states.addWidget(self.active)
        self.failure = QFrame()
        failure_box = QVBoxLayout(self.failure)
        self.failure_title = QLabel("Не удалось обновить")
        self.failure_title.setObjectName("downloadTitle")
        self.failure_file = QLabel("")
        self.failure_reason = QLabel("")
        retry = QPushButton("Повторить")
        retry.clicked.connect(lambda: self.retry_requested.emit(getattr(self, "_failed_instance", "")))
        logs = QPushButton("Открыть лог")
        logs.clicked.connect(self.logs_requested)
        copy_details = QPushButton("Скопировать сведения")
        copy_details.clicked.connect(self._copy_failure)
        failure_box.addWidget(self.failure_title); failure_box.addWidget(self.failure_file); failure_box.addWidget(self.failure_reason)
        failure_box.addWidget(retry); failure_box.addWidget(logs); failure_box.addWidget(copy_details)
        self.states.addWidget(self.failure)
        root.addWidget(self.states, 1)
        self.states.setCurrentWidget(self.empty)
        self._samples = {}
        self._last_event = None
        self.current_speed = 0.0
        self._last_paint = 0.0
        self._last_phase = ""

    def update_progress(self, world_name: str, done: int, total: int, status: str = "") -> None:
        if total <= 0:
            self.states.setCurrentWidget(self.empty)
            return
        self.states.setCurrentWidget(self.active)
        self.name.setText(world_name or "NEXUS")
        self.detail.setText(status or "Загрузка файлов…")
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        percent = max(0, min(100, int(done * 100 / total)))
        self.percent.setText(f"{percent}%")
        self.bytes.setText(f"{self._format_bytes(done)} / {self._format_bytes(total)}")

    def update_event(self, event, world_name="NEXUS"):
        self._last_paint = time.monotonic()
        self._last_phase = event.phase
        self._last_event = event
        self.states.setCurrentWidget(self.active)
        self.name.setText(world_name)
        labels = {"preparing": "Подготовка", "download": "Загрузка", "downloading": "Загрузка",
                  "verifying": "Проверка", "applying": "Применение", "finalizing": "Завершение",
                  "ready": "Готово", "checking": "Проверка обновлений"}
        phase = labels.get(str(event.phase).lower(), str(event.phase).replace("_", " ").title())
        current = str(event.current_file or "")
        shown = ("…" + current[-68:]) if len(current) > 69 else current
        self.detail.setText(phase + (f" · {shown}" if shown else ""))
        self.detail.setToolTip(current)
        total = event.bytes_total
        if total:
            self.progress.setRange(0, max(total, 1)); self.progress.setValue(event.bytes_done)
            self.percent.setText(f"{max(0, min(100, int(event.bytes_done * 100 / total)))}%")
            self.bytes.setText(f"{self._format_bytes(event.bytes_done)} / {self._format_bytes(total)}")
        else:
            self.progress.setRange(0, 0); self.percent.setText("—")
            self.bytes.setText(self._format_bytes(event.bytes_done))
        network_phase = str(event.phase).lower() in {"download", "downloading"}
        samples = self._samples.setdefault(event.operation_id, [])
        if network_phase:
            samples.append((event.sampled_at, event.bytes_done))
            del samples[:-8]
        speed = 0.0
        if network_phase and len(samples) >= 2 and samples[-1][0] > samples[0][0] and samples[-1][1] >= samples[0][1]:
            speed = (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])
        self.current_speed = speed
        if speed > 0 and total and len(samples) >= 3:
            eta = max(0, int((total - event.bytes_done) / speed))
            self.telemetry.setText(f"{self._format_bytes(int(speed))}/с · осталось ~{eta // 60}:{eta % 60:02d}")
        elif speed > 0:
            self.telemetry.setText(f"{self._format_bytes(int(speed))}/с · общий размер неизвестен")
        elif network_phase:
            self.telemetry.setText("Расчёт времени…")
        else:
            self.telemetry.setText("Проверка без использования сети" if str(event.phase).lower() == "verifying" else phase)

    def show_failure(self, reason):
        event = self._last_event
        self._failed_instance = event.instance_id if event else ""
        lowered = reason.lower()
        integrity = any(word in lowered for word in ("sha", "hash", "повреж", "размер файла"))
        storage = any(word in lowered for word in ("space", "disk", "мест"))
        self.failure_title.setText("Проверка файла не пройдена" if integrity else ("Недостаточно места" if storage else "Не удалось загрузить файл"))
        self.failure_file.setText(event.current_file if event and event.current_file else "Текущий файл не определён")
        kind = "integrity" if integrity else ("storage" if storage else "network")
        self.failure_reason.setText(
            "Nexus не будет использовать повреждённый файл." if kind == "integrity"
            else ("Освободите место в папке установки и повторите попытку." if kind == "storage"
                  else "Проверьте подключение к интернету и повторите попытку.")
        )
        self.failure_reason.setToolTip(reason)
        self.states.setCurrentWidget(self.failure)

    def _copy_failure(self):
        event = self._last_event
        raw = self.failure_reason.toolTip()
        sanitized = re.sub(r"(?i)(token|cookie|authorization|api[_-]?key|secret)\s*[:=]\s*\S+", r"\1=[скрыто]", raw)
        sanitized = re.sub(r"[A-Za-z]:\\[^\r\n]+", "[локальный путь скрыт]", sanitized)
        lines = [f"operation ID: {getattr(event, 'operation_id', '')}",
                 f"world: {self.name.text()}", f"phase: {getattr(event, 'phase', '')}",
                 f"error: {sanitized}"]
        QApplication.clipboard().setText("\n".join(lines))

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, value))
        for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
            if size < 1024 or unit == "ТБ":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} ТБ"


class NewsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 40)
        title = QLabel("НОВОСТИ")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        for category, title_text, body in (
            ("NEXUS", "Платформа миров", "Новая навигация объединяет официальные миры и личные сборки в одном окне."),
            ("GEARMORPH", "Season II", "Индустриальный мир готовится к следующему этапу технического тестирования."),
            ("LAUNCHER", "Private Global Update", "Сборка доступна только на этом компьютере и не входит в публичный канал обновлений."),
        ):
            card = QFrame()
            card.setObjectName("contentCard")
            box = QVBoxLayout(card)
            eye = QLabel(category)
            eye.setObjectName("eyebrow")
            head = QLabel(title_text)
            head.setObjectName("cardTitle")
            copy = QLabel(body)
            copy.setObjectName("muted")
            copy.setWordWrap(True)
            box.addWidget(eye)
            box.addWidget(head)
            box.addWidget(copy)
            root.addWidget(card)
        root.addStretch()


class TechCenterPage(QWidget):
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root=QVBoxLayout(self); root.setContentsMargins(36,28,36,36); root.setSpacing(14)
        title=QLabel("NEXUS CONTROL CENTER"); title.setObjectName("pageTitle"); root.addWidget(title)
        self.summary=QLabel("Загрузка реальных staging данных…"); self.summary.setObjectName("cardTitle"); root.addWidget(self.summary)
        self.health=QLabel(""); self.health.setObjectName("settingsValue"); root.addWidget(self.health)
        self.submissions=QListWidget(); root.addWidget(self.submissions,1)
        refresh=QPushButton("Обновить"); refresh.clicked.connect(self.refresh_requested); root.addWidget(refresh)

    def set_data(self, overview:dict, submissions:list[dict], error=""):
        if error:
            self.summary.setText("Control Center недоступен")
            self.health.setText(error); return
        counts=overview.get("submissions",{}); catalogue=overview.get("catalogue",{})
        self.summary.setText(f"Pending submissions  {counts.get('pending',0)}     Under review  {counts.get('underReview',0)}     Approved  {counts.get('approved',0)}     Worlds  {overview.get('worlds',0)}")
        health=overview.get("health",{})
        self.health.setText(f"Staging catalogue v{catalogue.get('sequence',0)} · {'Valid' if catalogue.get('valid') else 'Empty'}\nAPI  ● {health.get('api','?')}    D1  ● {health.get('d1','?')}    R2  ● {health.get('r2','?')}    Signing  ● {health.get('signing','?')}")
        self.submissions.clear()
        for item in submissions:
            metadata=item.get("metadata_json",{})
            if isinstance(metadata,str):
                try: metadata=__import__('json').loads(metadata)
                except ValueError: metadata={}
            self.submissions.addItem(f"{metadata.get('title',item.get('project_id','World'))} · r{item.get('revision')} · {item.get('state')} · v{metadata.get('version','?')} · {metadata.get('minecraft','?')} · {metadata.get('loader','?')}")


class SettingsPage(QWidget):
    launch_settings_requested = Signal()
    logs_requested = Signal()
    storage_refresh_requested = Signal()
    settings_changed = Signal(object)
    studio_requested = Signal()
    tech_center_requested = Signal()

    CATEGORIES = ("Основные", "Игра", "Java", "Хранилище", "Загрузки", "Оформление", "Сеть", "Логи", "О программе", "Дополнительно")

    def __init__(self, config: dict, java_label: str, data_root: Path, version: str, parent=None):
        super().__init__(parent)
        self.config = config
        self.data_root = Path(data_root)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 32)
        root.setSpacing(16)
        title = QLabel("НАСТРОЙКИ")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        shell = QFrame()
        shell.setObjectName("settingsShell")
        shell.setMinimumWidth(900)
        shell.setMaximumWidth(1100)
        shell.setMaximumHeight(650)
        shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.categories = QListWidget()
        self.categories.setObjectName("settingsCategories")
        self.categories.setFixedWidth(190)
        self.categories.addItems(self.CATEGORIES)
        shell_layout.addWidget(self.categories)
        self.panels = QStackedWidget()
        self.panels.setObjectName("settingsPanels")
        shell_layout.addWidget(self.panels, 1)
        shell_row = QHBoxLayout()
        shell_row.setContentsMargins(0, 0, 0, 0)
        shell_row.addWidget(shell)
        shell_row.setAlignment(shell, Qt.AlignTop)
        shell_row.addStretch()
        root.addLayout(shell_row, 1)

        self.general_values = self._value_panel("ОСНОВНЫЕ", "Основное поведение платформы NEXUS")
        self.game_values = self._value_panel("ИГРА", "Параметры запуска Minecraft")
        self.java_values = self._value_panel("JAVA", "Обнаруженная среда выполнения")
        self.storage_values = self._value_panel("ХРАНИЛИЩЕ", "Использование локального диска")
        self.download_values = self._value_panel("ЗАГРУЗКИ", "Действующий защищённый updater")
        self.appearance_values = self._value_panel("ОФОРМЛЕНИЕ", "Интерфейс и движение")
        self.network_values = self._value_panel("СЕТЬ", "Источники данных официальных миров")
        self.logs_values = self._value_panel("ЛОГИ", "Лаунчер, игра и отчёты о сбоях")
        self.about_values = self._value_panel("О ПРОГРАММЕ", "NEXUS Launcher Private")
        self.advanced_values = self._value_panel("ДОПОЛНИТЕЛЬНО", "Локальные инструменты создания сборок")
        self.creator_mode = QCheckBox("Creator Mode")
        self.creator_mode.setChecked(bool(config.get("creatorMode", False)))
        self.studio_button = QPushButton("Открыть Nexus Studio")
        self.studio_button.setVisible(self.creator_mode.isChecked())
        self.studio_button.clicked.connect(self.studio_requested)
        self.creator_mode.toggled.connect(self.studio_button.setVisible)
        self.creator_mode.toggled.connect(lambda enabled: self.settings_changed.emit({"creatorMode": enabled}))
        self.advanced_values.layout().addWidget(self.creator_mode)
        self.backup_retention = QSpinBox()
        self.backup_retention.setRange(1, 20)
        self.backup_retention.setValue(max(1, min(20, int(config.get("backupRetention", 5)))))
        self.backup_retention.setPrefix("Хранить копий: ")
        self.backup_retention.valueChanged.connect(lambda value: self.settings_changed.emit({"backupRetention": value}))
        self.advanced_values.layout().addWidget(self.backup_retention)
        self.advanced_values.layout().addWidget(self.studio_button)
        self.tech_center_button = QPushButton("Открыть NEXUS Control Center")
        self.tech_center_button.setVisible(False)
        self.tech_center_button.clicked.connect(self.tech_center_requested)
        self.advanced_values.layout().addWidget(self.tech_center_button)

        game_button = QPushButton("Изменить параметры запуска")
        game_button.clicked.connect(self.launch_settings_requested)
        self.game_values.layout().addWidget(game_button)
        java_button = QPushButton("Изменить Java")
        java_button.clicked.connect(self.launch_settings_requested)
        self.java_values.layout().addWidget(java_button)
        storage_button = QPushButton("Пересчитать использование")
        storage_button.clicked.connect(self.storage_refresh_requested)
        self.storage_values.layout().addWidget(storage_button)
        self.storage = QLabel("Нажмите «Пересчитать», чтобы получить актуальные размеры.")
        self.storage.setObjectName("settingsValue")
        self.storage.setWordWrap(True)
        self.storage_values.layout().addWidget(self.storage)
        self.video_muted = QCheckBox("Запускать видео миров без звука")
        self.video_backgrounds = QCheckBox("Фоновые видео миров")
        self.reduced_motion = QCheckBox("Уменьшить движение и переходы")
        self.appearance_values.layout().addWidget(self.video_backgrounds)
        self.appearance_values.layout().addWidget(self.video_muted)
        self.appearance_values.layout().addWidget(self.reduced_motion)
        self.video_muted.toggled.connect(self._emit_appearance)
        self.video_backgrounds.toggled.connect(self._emit_appearance)
        self.reduced_motion.toggled.connect(self._emit_appearance)
        logs_button = QPushButton("Открыть просмотрщик логов")
        logs_button.clicked.connect(self.logs_requested)
        copy_path = QPushButton("Копировать путь данных")
        copy_path.clicked.connect(lambda: QApplication.clipboard().setText(str(self.data_root)))
        self.logs_values.layout().addWidget(logs_button)
        self.logs_values.layout().addWidget(copy_path)
        for panel in (
            self.general_values, self.game_values, self.java_values, self.storage_values,
            self.download_values, self.appearance_values, self.network_values, self.logs_values, self.about_values, self.advanced_values,
        ):
            panel.layout().addStretch()
            self.panels.addWidget(panel)
        self.categories.currentRowChanged.connect(self.panels.setCurrentIndex)
        self.categories.setCurrentRow(0)
        self.set_config(config, java_label, version)

    def set_tech_center_visible(self, visible: bool) -> None:
        self.tech_center_button.setVisible(visible)

    @staticmethod
    def _value_panel(title: str, subtitle: str) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("settingsHeading")
        copy = QLabel(subtitle)
        copy.setObjectName("muted")
        layout.addWidget(heading)
        layout.addWidget(copy)
        layout.addSpacing(8)
        return panel

    @staticmethod
    def _set_lines(panel: QWidget, lines: list[tuple[str, str]]) -> None:
        old = panel.findChildren(QLabel, "settingLine")
        for label in old:
            panel.layout().removeWidget(label)
            label.setParent(None)
            label.deleteLater()
        insert_at = 3
        for name, value in lines:
            label = QLabel(f"{name}\n{value}")
            label.setObjectName("settingLine")
            label.setWordWrap(True)
            panel.layout().insertWidget(insert_at, label)
            insert_at += 1

    def set_config(self, config: dict, java_label: str, version: str = "") -> None:
        self.config = config
        behavior = str(config.get("launcherAfterLaunch", "keep_open"))
        behavior_text = {"keep_open": "Оставлять лаунчер открытым", "minimize": "Сворачивать после запуска", "close": "Закрывать после запуска"}.get(behavior, behavior)
        self._set_lines(self.general_values, [("Язык", "Русский"), ("После запуска игры", behavior_text)])
        resolution = f"{config.get('width', 'авто')} × {config.get('height', 'авто')}"
        self._set_lines(self.game_values, [
            ("Оперативная память", f"{int(config.get('memory', 4096)) // 1024:g} ГБ"),
            ("Разрешение", resolution),
            ("Полноэкранный режим", "Включён" if config.get("fullscreen", False) else "Выключен"),
            ("JVM arguments", str(config.get("jvm_args") or "По умолчанию")),
        ])
        java_path = str(config.get("java_path") or "Автоматический выбор")
        self._set_lines(self.java_values, [("Среда", java_label), ("Путь", java_path), ("Совместимость", "Рекомендовано для Minecraft 1.21.1")])
        install_root = str(config.get("install_root") or self.data_root)
        self._set_lines(self.download_values, [("Папка установок", install_root), ("Проверка", "Подписи, хеши и rollback включены"), ("Параллельность", "Одна безопасная транзакция")])
        self._set_lines(self.storage_values, [("Nexus data", str(self.data_root)), ("Расчёт", "Без перехода по symlink и junction")])
        feed = str(config.get("worldsFeedUrl") or "Встроенный каталог и локальный кэш")
        self._set_lines(self.network_values, [("Каталог миров", feed), ("Fallback", "Кэш → встроенные данные")])
        self._set_lines(self.logs_values, [("Папка данных", str(self.data_root)), ("Доступно", "Launcher logs · latest.log · launch log · crash reports")])
        self._set_lines(self.about_values, [
            ("NEXUS Launcher", version or "Private Global Update"),
            ("Канал", "PRIVATE · только этот компьютер"),
            ("Qt", PySide6.__version__),
            ("Python", platform.python_version()),
            ("Разработчик", "ForceCore"),
        ])
        self.video_muted.blockSignals(True)
        self.video_backgrounds.blockSignals(True)
        self.reduced_motion.blockSignals(True)
        self.video_muted.setChecked(bool(config.get("videoMuted", True)))
        self.video_backgrounds.setChecked(bool(config.get("videoBackgrounds", True)))
        self.reduced_motion.setChecked(bool(config.get("reducedMotion", False)))
        self.video_muted.blockSignals(False)
        self.video_backgrounds.blockSignals(False)
        self.reduced_motion.blockSignals(False)

    def _emit_appearance(self) -> None:
        self.settings_changed.emit({
            "videoMuted": self.video_muted.isChecked(),
            "videoBackgrounds": self.video_backgrounds.isChecked(),
            "reducedMotion": self.reduced_motion.isChecked(),
        })


class LogsPage(QWidget):
    open_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 24, 34, 28)
        row = QHBoxLayout()
        title = QLabel("ЛОГИ")
        title.setObjectName("pageTitle")
        self.kind = QComboBox()
        self.kind.addItems(["Launcher updater", "Minecraft latest", "Minecraft launch", "Crash reports"])
        self.kind.currentIndexChanged.connect(self.refresh)
        copy = QPushButton("Копировать")
        copy.clicked.connect(lambda: self.editor.selectAll() or self.editor.copy())
        folder = QPushButton("Открыть папку")
        folder.clicked.connect(self.open_folder_requested)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(self.kind)
        row.addWidget(copy)
        row.addWidget(folder)
        root.addLayout(row)
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setObjectName("logViewer")
        root.addWidget(self.editor, 1)
        self.instance_root = Path()

    def set_instance(self, root: Path) -> None:
        self.instance_root = root
        self.refresh()

    def refresh(self, *_args) -> None:
        root = self.instance_root
        candidates = [
            root / ".nexus-launcher/logs/launcher-updater.log",
            root / "logs/latest.log",
            root / ".nexus-launcher/logs/minecraft-launch.log",
        ]
        index = self.kind.currentIndex()
        if index == 3:
            reports = sorted((root / "crash-reports").glob("*.txt"), reverse=True) if (root / "crash-reports").is_dir() else []
            path = reports[0] if reports else None
        else:
            path = candidates[index]
        if path and path.is_file():
            try:
                data = path.read_text(encoding="utf-8", errors="replace")
                self.editor.setPlainText(data[-500_000:])
                return
            except OSError as error:
                self.editor.setPlainText(str(error))
                return
        self.editor.setPlainText("Лог пока не создан.")


class ModsPage(QWidget):
    optional_requested = Signal()
    open_folder_requested = Signal()
    diagnostics_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modsWorkspace")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 24, 34, 30)
        title = QLabel("МОДЫ")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        from .diagnostic_widgets import DiagnosticEntryCard
        self.diagnostics_card = DiagnosticEntryCard(managed=True)
        self.diagnostics_card.requested.connect(self.diagnostics_requested)
        root.addWidget(self.diagnostics_card)
        self.inventory_status = QLabel('Выберите сборку, чтобы увидеть установленные моды.')
        self.inventory_status.setObjectName('muted')
        self.inventory_status.setWordWrap(True)
        root.addWidget(self.inventory_status)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('Поиск по установленным модам')
        self.search.setPlaceholderText("Поиск по установленным модам")
        self.search.textChanged.connect(self._filter)
        root.addWidget(self.search)
        self.list = QListWidget()
        root.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        optional = QPushButton("Дополнительные моды")
        optional.clicked.connect(self.optional_requested)
        folder = QPushButton("Открыть папку модов")
        folder.clicked.connect(self.open_folder_requested)
        buttons.addWidget(optional)
        buttons.addWidget(folder)
        buttons.addStretch()
        root.addLayout(buttons)

    def set_instance(self, root: Path, optional_names: set[str] | None = None) -> None:
        self.list.clear()
        optional_names = {name.lower() for name in (optional_names or set())}
        mods = root / "mods"
        disabled = root / "disabled_mods"
        enabled_count = disabled_count = 0
        for folder, enabled in ((mods, True), (disabled, False)):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.jar"), key=lambda item: item.name.lower()):
                enabled_count += int(enabled)
                disabled_count += int(not enabled)
                kind = "Дополнительный" if path.name.lower() in optional_names else "Управляемый"
                item = f"{path.name}\n{'Включён' if enabled else 'Отключён'} · {kind}"
                self.list.addItem(item)
        self.inventory_status.setText(f'Включено: {enabled_count} · Отключено: {disabled_count}' if self.list.count() else 'Модов пока нет. Папка сборки пуста или ещё не установлена.')
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        query = text.strip().lower()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(bool(query and query not in item.text().lower()))
