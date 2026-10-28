"""Approved NEXUS presentation; service authority stays in PlatformLauncher."""
from dataclasses import replace

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedLayout, QTabWidget, QVBoxLayout, QWidget,
)

from nexus_launcher.modern_main import resource
from .models import WorldPresentation
from .pages import WorldPage
from .widgets import CoverLabel


class RoundedHero(QFrame):
    """Clip actual child artwork, not just the QSS frame background."""
    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 14, 14)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


def approved_world(world):
    # Only bundled Gearmorph fallback artwork changes. Remote creator media wins.
    if world.id == "main" and world.presentation.image.endswith("gearmorph-world-art.png"):
        return replace(world, presentation=WorldPresentation(
            type="image", image=str(resource("gearmorph-official.png"))))
    return world


def text(value, name="", wrap=True):
    label = QLabel(value)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    label.setTextFormat(Qt.PlainText)
    return label


def action(label, callback, primary=False):
    button = QPushButton(label)
    button.setMinimumHeight(42)
    button.setCursor(Qt.PointingHandCursor)
    if primary:
        button.setObjectName("primaryAction")
    button.clicked.connect(callback)
    return button


class PresentationSurface(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host.setMaximumWidth(1600)
        self.root = QVBoxLayout(self.host)
        self.root.setContentsMargins(40, 32, 40, 40)
        self.root.setSpacing(22)
        self.setWidget(self.host)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)


class NexusOverview(PresentationSurface):
    world_requested = Signal(object)

    def __init__(self, worlds, parent=None):
        super().__init__(parent)
        self.worlds = worlds
        self.tiles = {}
        self.root.addWidget(text("A PLACE INSIDE NEXUS", "eyebrow"))
        self.root.addWidget(text("Твоя следующая история.", "pageTitle"))
        self.root.addWidget(text("Играй. Исследуй. Создавай своё.", "muted"))
        if worlds:
            world = approved_world(worlds[0])
            self.hero = RoundedHero()
            self.hero.setObjectName("nexusHero")
            self.hero.setFixedHeight(440)
            stack = QStackedLayout(self.hero)
            stack.setStackingMode(QStackedLayout.StackAll)
            self.art = CoverLabel(world.presentation.image or world.presentation.poster)
            stack.addWidget(self.art)
            overlay = QFrame()
            overlay.setObjectName("nexusHeroOverlay")
            copy = QVBoxLayout(overlay)
            copy.setContentsMargins(35, 30, 35, 35)
            copy.addStretch()
            copy.addWidget(text("ТЕХНОЛОГИЧЕСКАЯ МАГИЯ" if world.id == "main" else world.season, "eyebrow"))
            copy.addWidget(text(world.title, "nexusHeroTitle"))
            description = text("Фабрики, технологическая магия и экспедиции в разломы." if world.id == "main" else world.description, "heroDescription")
            description.setMaximumWidth(420)
            copy.addWidget(description)
            button = action("Открыть мир", lambda: self.world_requested.emit(world), True)
            copy.addWidget(button, 0, Qt.AlignLeft)
            stack.addWidget(overlay)
            stack.setCurrentWidget(overlay)
            self.root.addWidget(self.hero)
            self.tabs = QTabWidget()
            for caption, value in (
                ("Обзор", world.description),
                ("Новости", "Публикации этого мира пока не подключены."),
                ("Авторы", "Сведения об авторах появятся после подключения профиля создателя."),
                ("Медиа", "Медиа этого мира пока не подключены."),
            ):
                panel = QWidget()
                layout = QVBoxLayout(panel)
                layout.setContentsMargins(24, 24, 24, 24)
                layout.addWidget(text(value, "muted"))
                layout.addStretch()
                self.tabs.addTab(panel, caption)
            self.tabs.setMinimumHeight(150)
            self.root.addWidget(self.tabs)
        self.root.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "hero"):
            self.hero.setFixedHeight(530 if self.viewport().width() >= 1400 else 440)

    def update_status(self, *_args):
        pass  # The home is presentation, not a synthetic server-status dashboard.

    def set_selected(self, *_args):
        pass


class NexusWorldPage(WorldPage):
    """Preserves the launch/progress/media interface with an in-hero play button."""
    save_requested = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        old = self.layout()
        parts = [old.takeAt(0).widget(), old.takeAt(0).widget()]
        # Remove the empty layout before installing the approved page structure.
        from shiboken6 import delete
        delete(old)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        surface = PresentationSurface()
        outer.addWidget(surface)
        row = QHBoxLayout()
        row.setSpacing(28)
        self.info = QFrame()
        self.info.setObjectName("contentCard")
        self.info.setFixedWidth(200)
        details = QVBoxLayout(self.info)
        details.setContentsMargins(20, 22, 20, 22)
        details.addWidget(text("О мире", "cardTitle"))
        self.info_name = text("", "cardTitle")
        self.info_meta = text("", "muted")
        details.addWidget(self.info_name)
        details.addWidget(self.info_meta)
        self.save = action("Сохранить мир", self.save_requested.emit)
        details.addWidget(self.save)
        details.addStretch()
        row.addWidget(self.info, 0, Qt.AlignTop)
        main = QVBoxLayout()
        self.hero = RoundedHero()
        self.hero.setObjectName("nexusHero")
        self.hero.setFixedHeight(440)
        stack = QStackedLayout(self.hero)
        stack.setStackingMode(QStackedLayout.StackAll)
        for part in parts:
            part.setParent(self.hero)
            stack.addWidget(part)
        stack.setCurrentWidget(parts[1])
        parts[1].setObjectName("nexusHeroOverlay")
        self.title.setObjectName("nexusHeroTitle")
        self.description.setObjectName("heroDescription")
        for label in (self.title, self.description, self.status, self.meta, self.client_status):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
        self.play.setMinimumSize(180, 48)
        self.progress.setMaximumWidth(160)
        main.addWidget(self.hero)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("nexusWorldTabs")
        self.about = text("")
        for title, body in (
            ("Обзор", self.about),
            ("Новости", text("Публикации этого мира пока не подключены.", "muted")),
            ("Авторы", text("Сведения об авторах появятся после подключения профиля создателя.", "muted")),
            ("Медиа", text("Медиа этого мира пока не подключены.", "muted")),
        ):
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.addWidget(body)
            layout.addStretch()
            self.tabs.addTab(panel, title)
        self.tabs.setMinimumHeight(180)
        main.addWidget(self.tabs)
        row.addLayout(main, 1)
        surface.root.addLayout(row)
        surface.root.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Information column is secondary on compact windows; hero remains usable.
        self.info.setVisible(self.width() >= 1000)

    def set_world(self, world, muted=True, video_enabled=True):
        world = approved_world(world)
        super().set_world(world, muted, video_enabled)
        self.info_name.setText(world.title)
        self.info_meta.setText(f"Minecraft {world.server.minecraft_version}\n{world.server.loader.title()}")
        self.about.setText(world.description)


class SavedWorlds(PresentationSurface):
    world_requested = Signal(object)
    catalogue_requested = Signal()

    def __init__(self, launcher):
        super().__init__()
        self.launcher = launcher
        self.root.addWidget(text("Мои миры", "pageTitle"))
        self.root.addWidget(text("Сохраняй понравившиеся серверы. Установленные сборки остаются в «Мои сборки».", "muted"))
        self.entries = QVBoxLayout()
        self.root.addLayout(self.entries)
        self.root.addWidget(action("Найти сервер в каталоге", self.catalogue_requested.emit), 0, Qt.AlignLeft)
        self.root.addStretch()

    def refresh(self):
        while self.entries.count():
            item = self.entries.takeAt(0)
            item.widget().deleteLater()
        saved = set(self.launcher.config.get("savedWorlds", []))
        worlds = [world for world in self.launcher.world_views if world.id in saved]
        if not worlds:
            self.entries.addWidget(text("Пока нет сохранённых миров. Открой мир в каталоге и нажми «Сохранить мир».", "muted"))
        for world in worlds:
            self.entries.addWidget(action(world.title, lambda _=False, item=world: self.world_requested.emit(item)))


class NexusProfile(PresentationSurface):
    """Full route replaces the footer popup; identity is never locally invented."""
    def __init__(self, launcher):
        super().__init__()
        self.launcher = launcher
        cover = QFrame()
        cover.setObjectName("profileCover")
        cover.setMinimumHeight(210)
        layout = QVBoxLayout(cover)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.addWidget(text("FORCECORE / PROFILE", "eyebrow"))
        layout.addStretch()
        layout.addWidget(text("Твоё пространство в NEXUS", "pageTitle"))
        self.root.addWidget(cover)
        identity = QHBoxLayout()
        # Same vector cube as the footer, not a PNG image with a face.
        from .next_shell import GreyCube
        identity.addWidget(GreyCube())
        names = QVBoxLayout()
        self.name = text("NEXUS профиль", "pageTitle")
        self.handle = text("Войдите, чтобы подключить профиль сайта.", "muted")
        names.addWidget(self.name)
        names.addWidget(self.handle)
        identity.addLayout(names, 1)
        self.root.addLayout(identity)
        controls = QHBoxLayout()
        self.login = action("Войти", launcher._login_account, True)
        self.register = action("Создать аккаунт", launcher._register_account)
        self.edit = action("Редактировать на сайте", launcher._open_web_profile, True)
        self.refresh = action("Обновить профиль", launcher._refresh_account)
        self.logout = action("Выйти", launcher._logout_account)
        for control in (self.login, self.register, self.edit, self.refresh, self.logout):
            controls.addWidget(control)
        controls.addStretch()
        self.root.addLayout(controls)
        self.root.addWidget(action("Глобальные настройки", launcher._settings), 0, Qt.AlignLeft)
        self.root.addWidget(text("Профиль связан с аккаунтом сайта NEXUS. Minecraft / Microsoft подключаются отдельно.", "muted"))
        self.root.addStretch()
        self.sync()

    def sync(self):
        profile = self.launcher.account_profile
        self.name.setText(profile.minecraft_nick if profile else "NEXUS профиль")
        self.handle.setText("@" + profile.minecraft_nick if profile else "Войдите, чтобы подключить профиль сайта.")
        for control in (self.login, self.register):
            control.setVisible(not profile)
        for control in (self.edit, self.refresh, self.logout):
            control.setVisible(bool(profile))
        for control in (self.login, self.register, self.refresh, self.logout):
            control.setEnabled(self.launcher.profile.isEnabled())
