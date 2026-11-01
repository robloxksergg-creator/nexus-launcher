from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
    QPushButton,
)

from nexus_launcher.instance_ui import InstancePage
from nexus_launcher.studio_ui import StudioPage
from nexus_launcher.modern_main import APP_DIR, CONFIG_FILE, Launcher as CoreLauncher
from nexus_launcher.modern_main import SettingsDialog, detect_java_label, nexus_nav_icon, resource
from nexus_launcher.platform_support import open_in_file_manager
from nexus_launcher.self_update import CURRENT_VERSION
from nexus_launcher.updater import InstallState, ModpackUpdater
from nexus_launcher.publishing import BundledCatalogueRepository
from nexus_launcher.feature_flags import feature_enabled

from .config import atomic_write, remember_world, canonical_world_preferences
from .content import RemoteWorldContent
from .models import WorldView, world_from_server
from .pages import (
    DiscoverPage,
    DownloadsPage,
    LogsPage,
    ModsPage,
    NewsPage,
    SettingsPage,
    TechCenterPage,
    WorldPage,
    WorldsCatalogue,
)
from .widgets import FocusVisibleTracker, PlatformStatusBar, TitleBar, WorldRail


class PlatformLauncher(CoreLauncher):
    """Private presentation shell; all install/launch/security work stays in CoreLauncher."""

    remote_content_ready = Signal(object)
    tech_center_ready = Signal(object, object)
    tech_access_ready = Signal(bool)
    tech_center_failed = Signal(str)

    def __init__(self):
        self.world_views: list[WorldView] = []
        self.page_map: dict[str, QWidget] = {}
        self._current_page = ""
        self._last_progress_total = 0
        self._download_auto_opened = False
        self._install_states = {}
        from .native_style import install_native_style
        install_native_style(QApplication.instance())
        super().__init__()
        if os.environ.get("NEXUS_ENVIRONMENT") == "staging":
            self.setWindowTitle("NEXUS Launcher — STAGING")
        self._focus_visible_tracker = FocusVisibleTracker(self)
        self._focus_visible_tracker.track_tree(self)
        self.remote_content_ready.connect(self._apply_remote_content)
        self.tech_center_ready.connect(lambda overview, submissions: self.tech_center_page.set_data(overview, submissions))
        self.tech_access_ready.connect(self.settings_page.set_tech_center_visible)
        self.tech_center_failed.connect(lambda message: self.tech_center_page.set_data({}, [], message))
        self.bridge.updater_progress.connect(self._updater_progress)
        self._refresh_remote_content()
        self.server_cards = dict(self.catalogue_page.tiles)
        if self.current_server:
            selected = str(self.config.get("selectedWorld", self.current_server.id))
            server = next((world.server for world in self.world_views if world.id == selected), self.current_server)
            self.select_server(server)
        QApplication.instance().applicationStateChanged.connect(self._application_state_changed)
        if not self.config.get("welcomeCompleted", False) and not self.config.get("recentWorlds"):
            self._navigate("welcome", "NEXUS / ДОБРО ПОЖАЛОВАТЬ")

    def _build(self):
        self.config.update(canonical_world_preferences(self.config))
        self.config.setdefault("videoBackgrounds", True)
        developer = self.config.setdefault("developer", {})
        if not isinstance(developer, dict):
            developer = {}
            self.config["developer"] = developer
        developer.setdefault("showPerformanceOverlay", False)
        built_in_worlds = BundledCatalogueRepository([
            world_from_server(server, resource)
            for project in self.projects
            for server in project.servers
        ]).list_worlds()
        self.remote_content = RemoteWorldContent(
            str(self.config.get("worldsFeedUrl", "")),
            APP_DIR / "cache" / "official-worlds.json",
            {world.id for world in built_in_worlds},
        )
        self.remote_world_state = self.remote_content.load_cache()
        self.world_views = self.remote_content.apply(built_in_worlds, self.remote_world_state)
        pinned = [str(value) for value in self.config.get("pinnedWorlds", [])]
        central = QWidget()
        central.setObjectName("platformRoot")
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        rail_icons = {
            "worlds": nexus_nav_icon(1),
            "library": nexus_nav_icon(3),
            "downloads": self.style().standardIcon(QStyle.SP_ArrowDown),
            "news": nexus_nav_icon(2),
            "settings": nexus_nav_icon(4),
        }
        self.rail = WorldRail(self.world_views, pinned, rail_icons)
        outer.addWidget(self.rail)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        outer.addLayout(content, 1)
        self.title_bar = TitleBar(self)
        self.profile = self.title_bar.profile
        self.maximize_button = self.title_bar.maximum
        content.addWidget(self.title_bar)
        self.pages = QStackedWidget()
        self.pages.setObjectName("platformPages")
        content.addWidget(self.pages, 1)
        self.status_bar = PlatformStatusBar(CURRENT_VERSION)
        content.addWidget(self.status_bar)

        reduced_motion = bool(self.config.get("reducedMotion", False))
        self.discover_page = DiscoverPage(self.world_views, list(self.config.get("recentWorlds", [])), reduced_motion)
        self.catalogue_page = WorldsCatalogue(self.world_views, reduced_motion)
        self.world_page = WorldPage()
        self.world_page.set_reduced_motion(bool(self.config.get("reducedMotion", False)))
        self.instances_page = InstancePage(self.instance_service, self)
        self.instances_page.backup_retention = int(self.config.get("backupRetention", 5))
        self.studio_page = StudioPage(self.instance_service, self)
        self.studio_page.set_mode(bool(self.config.get("creatorMode", False)))
        self.instances_page.backup_retention = int(self.config.get("backupRetention", 5))
        self.rail.section_buttons["studio"].setVisible(bool(self.config.get("creatorMode", False)))
        self.downloads_page = DownloadsPage()
        self.news_page = NewsPage()
        from .support_page import SupportPage
        self.support_page = SupportPage(self)
        self.rail.support_requested.connect(lambda: self._navigate('support', 'NEXUS / ПОДДЕРЖКА'))
        self.settings_page = SettingsPage(self.config, detect_java_label(self.config.get("java_path", "")), APP_DIR, CURRENT_VERSION)
        self.tech_center_page = TechCenterPage()
        self.logs_page = LogsPage()
        self.mods_page = ModsPage()
        self.welcome_page = QWidget()
        welcome = QVBoxLayout(self.welcome_page)
        welcome.setContentsMargins(70, 50, 70, 50)
        welcome.addStretch()
        welcome_title = QLabel("ДОБРО ПОЖАЛОВАТЬ В NEXUS")
        welcome_title.setObjectName("pageTitle")
        welcome.addWidget(welcome_title)
        welcome.addWidget(QLabel("Выберите готовый мир или создайте собственную сборку Minecraft."))
        for label, own in (("Играть в миры", False), ("Создать свою сборку", True)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, custom=own: self._finish_welcome(custom))
            welcome.addWidget(button)
        welcome.addStretch()
        self.catalog = self.discover_page
        for key, page in (
            ("home", self.discover_page),
            ("worlds", self.catalogue_page),
            ("world", self.world_page),
            ("library", self.instances_page),
            ("studio", self.studio_page),
            ("downloads", self.downloads_page),
            ("news", self.news_page),
            ("support", self.support_page),
            ("settings", self.settings_page),
            ("tech", self.tech_center_page),
            ("logs", self.logs_page),
            ("mods", self.mods_page),
            ("welcome", self.welcome_page),
        ):
            self.page_map[key] = page
            self.pages.addWidget(page)

        self.play = self.world_page.play
        self.progress = self.world_page.progress
        self.status = self.world_page.client_status
        self.catalog_play = self.play
        self.catalog_progress = self.progress
        self.catalog_status = self.status
        self.footer_java = self.status_bar.java
        self.footer_build = QLabel()
        self.details_title = self.world_page.title
        self.details_version = QLabel()
        self.details_loader = QLabel()
        self.details_players = QLabel()
        self.details_status = self.world_page.status

        self.rail.home_requested.connect(self.show_catalog)
        self.rail.worlds_requested.connect(lambda: self._navigate("worlds", "NEXUS / МИРЫ"))
        self.rail.library_requested.connect(self.show_instances)
        self.rail.studio_requested.connect(self._show_studio)
        self.rail.news_requested.connect(lambda: self._navigate("news", "NEXUS / НОВОСТИ"))
        self.rail.downloads_requested.connect(lambda: self._navigate("downloads", "NEXUS / ЗАГРУЗКИ"))
        self.rail.settings_requested.connect(self._settings)
        self.rail.add_requested.connect(self._add_to_nexus)
        self.rail.world_requested.connect(lambda world: self.show_server(world.server))
        self.rail.world_menu_requested.connect(self._rail_menu)
        self.discover_page.world_requested.connect(lambda world: self.show_server(world.server))
        self.catalogue_page.world_requested.connect(lambda world: self.show_server(world.server))
        self.world_page.play_requested.connect(self._play)
        self.world_page.menu_requested.connect(self._world_menu)
        self.world_page.video_muted_changed.connect(self._video_muted_changed)
        self.instances_page.launch_requested.connect(self._launch_user_instance)
        self.studio_page.test_launch_requested.connect(lambda identifier: self._launch_user_instance(identifier, "test"))
        self.settings_page.studio_requested.connect(self._show_studio)
        self.settings_page.tech_center_requested.connect(lambda: self._navigate("tech", "NEXUS / CONTROL CENTER"))
        self.tech_center_page.refresh_requested.connect(self._refresh_tech_center)
        self.status_bar.downloads_requested.connect(lambda: self._navigate("downloads", "NEXUS / ЗАГРУЗКИ"))
        self.downloads_page.worlds_requested.connect(lambda: self._navigate("worlds", "NEXUS / МИРЫ"))
        self.downloads_page.retry_requested.connect(self._retry_download)
        self.downloads_page.logs_requested.connect(self._show_logs)
        self.settings_page.launch_settings_requested.connect(self._launch_settings)
        self.settings_page.logs_requested.connect(self._show_logs)
        self.settings_page.storage_refresh_requested.connect(self._refresh_storage)
        self.settings_page.settings_changed.connect(self._platform_settings_changed)
        self.logs_page.open_folder_requested.connect(self._open_logs_folder)
        self.mods_page.optional_requested.connect(self._optional_mods)
        self.mods_page.open_folder_requested.connect(self._open_mods_folder)
        self.mods_page.diagnostics_requested.connect(self._open_instance_diagnostics)
        self.status_bar.java.setText(detect_java_label(self.config.get("java_path", "")))
        for world_id, item in self.remote_world_state.items():
            self._set_remote_status(world_id, item)

    def _account_ready(self, profile):
        super()._account_ready(profile)
        if not hasattr(self, "settings_page"):
            return
        self.settings_page.set_tech_center_visible(False)
        if profile and feature_enabled("controlCenter"):
            threading.Thread(target=self._refresh_tech_center, daemon=True).start()

    def _refresh_tech_center(self):
        if not feature_enabled("controlCenter"):
            self.tech_access_ready.emit(False)
            return
        try:
            from nexus_launcher.remote_publishing import ControlPlaneClient, RemoteReviewRepository, RemoteTechRepository
            client = ControlPlaneClient(self.account_client.base_url, self.account_client._token)
            capabilities = client.request("/api/v1/capabilities").get("capabilities", [])
            allowed = "review:read" in capabilities
            if not allowed:
                self.tech_access_ready.emit(False)
                return
            self.tech_access_ready.emit(True)
            self.tech_center_ready.emit(RemoteTechRepository(client).overview(), RemoteReviewRepository(client).inbox())
        except Exception as error:
            self.tech_center_failed.emit(str(error))

    def _style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget#platformRoot, QStackedWidget#platformPages { background:#05080f; color:#eef4fb; }
            QWidget { color:#e8eef7; font-family:'Segoe UI'; font-size:13px; }
            QFrame#worldRail { background:#070b13; border-right:1px solid #162130; }
            QFrame#railSeparator { background:#253246; border:0; }
            QToolButton { background:#101722; border:1px solid #1b293b; border-radius:15px; color:#a9b7c9; font-weight:700; }
            QToolButton:hover { background:#172334; border-color:#467dab; color:white; }
            QToolButton:pressed { background:#0c131d; border-color:#345f82; color:#dcecff; }
            QToolButton[focusVisible="true"] { border:2px solid #8ad1ff; color:white; }
            QToolButton[dataActive="true"] { background:#16304b; border:1px solid #54a9e9; color:white; border-radius:12px; }
            QToolButton[dataActive="true"]:hover { background:#1b3b5c; border-color:#78c7ff; }
            QToolButton[dataActive="true"]:pressed { background:#0d2438; border-color:#78c7ff; }
            QToolButton#nexusRailButton { color:#fff; font-size:24px; background:#101722; border-color:#1b293b; }
            QToolButton#nexusRailButton[dataActive="true"] { background:#16304b; border-color:#54a9e9; }
            QLabel#railStatusDot { border:2px solid #070b13; border-radius:5px; background:#657184; }
            QLabel#railStatusDot[state="online"] { background:#44d18b; }
            QLabel#railStatusDot[state="maintenance"], QLabel#railStatusDot[state="development"], QLabel#railStatusDot[state="closed"] { background:#e2ad4f; }
            QLabel#railStatusDot[state="offline"], QLabel#railStatusDot[state="unavailable"] { background:#657184; }
            QLabel#railUpdateBadge { border:2px solid #070b13; border-radius:5px; background:#f0a43c; }
            QLabel#railNotificationBadge { border:1px solid #070b13; border-radius:4px; background:#e96374; }
            QLabel#railProgressBadge { background:#0b263b; color:#bde8ff; border:1px solid #4aa8ee; border-radius:7px; font-size:8px; font-weight:800; }
            QFrame#platformTitleBar { background:#080d15; border-bottom:1px solid #152131; }
            QLabel#titleContext { color:#71839b; font-size:10px; font-weight:700; letter-spacing:2px; }
            QPushButton#accountButton { background:#0d1521; border:1px solid #213147; border-radius:8px; padding:8px 14px; }
            QPushButton#windowControl { background:transparent; border:0; border-radius:5px; font-size:16px; }
            QPushButton#windowControl:hover { background:#172438; }
            QPushButton#windowControl[closeControl="true"]:hover { background:#c43c4d; }
            QFrame#platformStatusBar { background:#070b12; border-top:1px solid #142030; }
            QFrame#platformStatusBar QLabel { color:#74859a; font-size:10px; }
            QPushButton#downloadIndicator { background:transparent; border:0; color:#6ebaff; font-size:10px; }
            QScrollArea { background:transparent; border:0; }
            QScrollArea > QWidget > QWidget { background:transparent; }
            QScrollBar:vertical { width:0px; background:#080d15; border:0; }
            QScrollBar::handle:vertical { min-height:45px; background:#2a3d54; border-radius:4px; }
            QLabel#pageTitle { color:#f5f8fc; font-family:'Georgia'; font-size:31px; font-weight:700; letter-spacing:4px; }
            QLabel#sectionTitle, QLabel#eyebrow { color:#70a6d5; font-size:10px; font-weight:700; letter-spacing:2px; }
            QLabel#muted { color:#8c9aad; }
            QLabel#cardTitle { color:#f3f7fb; font-size:16px; font-weight:650; }
            QFrame#contentCard { background:#0b111b; border:1px solid #1b293a; border-radius:12px; padding:12px; }
            QFrame#featuredWorld { background:#0b111b; border:1px solid #26394e; border-radius:16px; }
            QFrame#featuredOverlay { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(4,8,14,240),stop:.48 rgba(4,8,14,145),stop:1 rgba(4,8,14,18)); border-radius:16px; }
            QLabel#featuredTitle { color:white; font-family:'Georgia'; font-size:40px; font-weight:700; letter-spacing:3px; }
            QLabel#featuredDescription { color:#d8e2ec; font-size:15px; }
            QLabel#tileArrow { color:#7dc6f5; font-size:20px; font-weight:700; }
            QPushButton { background:#101925; border:1px solid #26384d; border-radius:8px; padding:9px 14px; outline:none; }
            QPushButton:hover { background:#17263a; border-color:#4c8ec5; }
            QPushButton:pressed { background:#0b121c; border-color:#315d82; }
            QPushButton[focusVisible="true"], QLineEdit[focusVisible="true"], QComboBox[focusVisible="true"], QListWidget[focusVisible="true"], QPlainTextEdit[focusVisible="true"] { border:2px solid #8ad1ff; }
            QPushButton:disabled { color:#657184; background:#0c1119; border-color:#1b2532; }
            QPushButton#primaryAction, QPushButton#heroPlay { background:#e8f4ff; color:#07111e; border:1px solid white; font-weight:800; letter-spacing:1px; }
            QPushButton#primaryAction:hover, QPushButton#heroPlay:hover { background:white; }
            QPushButton#primaryAction:pressed, QPushButton#heroPlay:pressed { background:#b9d8ee; border-color:#d8edfc; }
            QPushButton#worldTile { background:#0a1019; border:1px solid #1c2a3a; border-radius:12px; padding:0; text-align:left; }
            QPushButton#worldTile:hover { background:#0e1825; border-color:#3a6f9c; }
            QPushButton#worldTile:pressed { background:#09111b; border-color:#315d82; }
            QPushButton#worldTile[selected="true"] { background:#102033; border:1px solid #54a9e9; }
            QPushButton#filterChip { background:#0b131e; border:1px solid #26384d; border-radius:15px; padding:7px 15px; }
            QPushButton#filterChip:hover { background:#122236; border-color:#477aa4; }
            QPushButton#filterChip[dataActive="true"] { background:#183753; border-color:#65b8ed; color:white; }
            QLabel#tileTitle { font-family:'Georgia'; font-size:21px; font-weight:700; letter-spacing:1px; }
            QLabel#worldStatus, QLabel#heroStatus { color:#98a8ba; font-size:11px; font-weight:700; letter-spacing:1px; }
            QLabel#worldStatus[online="true"], QLabel#heroStatus[state="online"] { color:#52dd94; }
            QLabel#heroStatus[state="maintenance"] { color:#f2bd5b; }
            QLabel#heroStatus[state="offline"], QLabel#heroStatus[state="closed"] { color:#f07878; }
            QFrame#worldOverlay { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(3,6,11,20),stop:.48 rgba(3,6,11,35),stop:1 rgba(3,7,13,245)); }
            QLabel#worldSeason { color:#9fcdf2; font-size:11px; font-weight:700; letter-spacing:3px; }
            QLabel#worldTitle { color:white; font-family:'Georgia'; font-size:48px; font-weight:700; letter-spacing:4px; }
            QLabel#worldDescription { color:#dce6ef; font-size:16px; }
            QLabel#heroMeta { color:#a8b7c8; font-size:12px; }
            QLabel#clientStatus { color:#a5b3c3; }
            QPushButton#heroMenu, QPushButton#mediaControl { background:rgba(8,15,24,205); border:1px solid rgba(124,164,199,100); }
            QPushButton#heroMenu:pressed, QPushButton#mediaControl:pressed { background:rgba(3,8,14,235); border-color:#64b5ed; }
            QLineEdit, QComboBox, QPlainTextEdit, QListWidget { background:#0a111b; border:1px solid #223348; border-radius:8px; padding:9px; selection-background-color:#234d72; }
            QFrame#settingsShell { background:#080e17; border:1px solid #1b293a; border-radius:12px; }
            QListWidget#settingsCategories { background:#080e17; border:0; border-right:1px solid #1b293a; border-radius:10px; padding:12px 8px; outline:none; }
            QListWidget#settingsCategories::item { min-height:38px; padding:5px 12px; border-radius:7px; color:#90a0b5; }
            QListWidget#settingsCategories::item:hover { background:#111e2e; color:#dcecff; }
            QListWidget#settingsCategories::item:selected { background:#173653; color:white; border-left:2px solid #68bdf2; }
            QStackedWidget#settingsPanels { background:#0a111b; border-radius:0 12px 12px 0; }
            QLabel#settingsHeading { color:white; font-family:'Georgia'; font-size:26px; font-weight:700; letter-spacing:2px; }
            QLabel#settingLine { background:#0d1723; border:1px solid #1d2e42; border-radius:9px; padding:12px; color:#dbe7f3; }
            QLabel#settingsValue { background:#09121d; border:1px solid #21344a; border-radius:8px; padding:12px; color:#aec2d7; }
            QLabel#emptyIcon { color:#64b8ef; font-size:48px; font-weight:300; }
            QLabel#emptyTitle { color:white; font-family:'Georgia'; font-size:27px; font-weight:700; }
            QFrame#downloadActive { background:#0a111b; border:1px solid #21334a; border-radius:12px; }
            QLabel#downloadTitle { color:white; font-family:'Georgia'; font-size:28px; font-weight:700; }
            QLabel#downloadBytes { color:#cad8e7; font-size:14px; }
            QLabel#downloadPercent { color:#72c4f5; font-size:24px; font-weight:750; }
            QProgressBar { background:#111c29; border:0; border-radius:4px; min-height:8px; text-align:center; }
            QProgressBar::chunk { background:#4aa8ee; border-radius:4px; }
            QDialog { background:#080e18; }
            QMenu { background:#0b121d; border:1px solid #273a50; padding:7px; }
            QMenu::item { padding:9px 28px 9px 12px; border-radius:5px; }
            QMenu::item:selected { background:#18304a; }
            QTabWidget::pane { border:1px solid #233348; background:#090f18; }
            QTabBar::tab { background:#0d1521; padding:9px 13px; border:1px solid #213147; }
            QTabBar::tab:selected { background:#18304a; }
        """)

    def _navigate(self, key: str, context: str) -> None:
        if self._current_page == "registration" and key != "registration":
            page = self.page_map.get("registration")
            form = getattr(page, "registration_form", None)
            if form and form.busy:
                form.error.setText("Дождитесь ответа сайта. Запрос уже отправлен.")
                return
            if form and not form.completed:
                form._reset()
                form.password.clear()
                form.confirm.clear()
        if key == "studio" and not self.config.get("creatorMode", False):
            return
        if self._current_page == "studio" and key != "studio" and not self.studio_page.may_leave():
            return
        if self._current_page == "world" and key != "world":
            self.world_page.release()
        self._current_page = key
        self.pages.setCurrentWidget(self.page_map[key])
        if not self.config.get("reducedMotion", False):
            target = self.page_map[key]
            effect = QGraphicsOpacityEffect(target)
            target.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            self._page_animation = QPropertyAnimation(effect, b"opacity", self)
            self._page_animation.setDuration(180)
            self._page_animation.setStartValue(0.0)
            self._page_animation.setEndValue(1.0)
            self._page_animation.setEasingCurve(QEasingCurve.OutCubic)
            self._page_animation.finished.connect(lambda: target.setGraphicsEffect(None))
            self._page_animation.start()
        self.title_bar.context.setText(context)
        world_id = self.current_server.id if key == "world" and self.current_server else ""
        self.rail.select_route(key, world_id)

    def show_catalog(self):
        self._navigate("home", "NEXUS / DISCOVER")

    def _finish_welcome(self, custom):
        self.config["welcomeCompleted"] = True
        self._save_config()
        if custom:
            self._create_instance()
        else:
            self._navigate("worlds", "NEXUS / МИРЫ")

    def _show_studio(self):
        if self.config.get("creatorMode", False):
            self.studio_page.refresh()
            self._navigate("studio", "NEXUS / STUDIO")

    def show_instances(self):
        self.instances_page.refresh(self.current_user_instance_id)
        self._navigate("library", "NEXUS / МОЯ БИБЛИОТЕКА")

    def show_server(self, server):
        self.select_server(server)
        self._navigate("world", f"NEXUS / {self._world(server.id).title}")

    def select_server(self, server):
        if server is None:
            return
        self.current_server = server
        world = self._world(server.id)
        self.world_page.set_world(
            world,
            bool(self.config.get("videoMuted", True)),
            bool(self.config.get("videoBackgrounds", True)),
        )
        self.discover_page.set_selected(server.id)
        self.catalogue_page.set_selected(server.id)
        remember_world(self.config, server.id)
        self._save_config()
        state = self.server_states.get(server.id)
        access = self.build_access.get(server.id, {})
        mode = str(access.get("mode", "OPEN")).upper()
        allowed = bool(access.get("allowed", mode == "OPEN"))
        if mode == "MAINTENANCE":
            self.world_page.set_server_status("maintenance")
        elif mode == "CLOSED":
            self.world_page.set_server_status("closed")
        elif server.visibility == "coming_soon":
            self.world_page.set_server_status("development")
        elif state:
            ok, current, maximum = state
            self.world_page.set_server_status("online" if ok else "unavailable", current, maximum)
        elif server.id in self.remote_world_state:
            item = self.remote_world_state[server.id]
            self.world_page.set_server_status(item["status"], item["players"], item["maxPlayers"])
        else:
            self.world_page.set_server_status("unavailable")
        updater = ModpackUpdater(self._instance_dir(), instance_id=server.id)
        installed = updater.installed_version
        snapshot = updater.delivery_snapshot()
        if snapshot.state == InstallState.NOT_INSTALLED and installed:
            snapshot = updater._set_delivery(InstallState.READY)
        if snapshot.state == InstallState.READY and installed:
            audit = updater.audit_managed_files()
            if audit["missing"] or audit["changed"]:
                snapshot = updater._set_delivery(InstallState.REPAIR_REQUIRED)
        self._install_states[server.id] = snapshot
        self.footer_build.setText(f"Сборка {installed}" if installed else "Сборка не установлена")
        can_play = server.visibility != "coming_soon" and allowed and bool(self.account_profile)
        self.play.setEnabled(can_play)
        if not allowed:
            self.play.setText("ДОСТУП ЗАКРЫТ")
            self.status.setText(str(access.get("message") or "Сборка временно недоступна"))
        elif server.visibility == "coming_soon":
            self.play.setText("В РАЗРАБОТКЕ")
        elif not self.account_profile:
            self.play.setText("ВОЙТИ ДЛЯ ЗАПУСКА")
        else:
            labels = {
                InstallState.NOT_INSTALLED: "УСТАНОВИТЬ", InstallState.CHECKING: "ПРОВЕРКА…",
                InstallState.PREPARING: "ПОДГОТОВКА…", InstallState.DOWNLOADING: "ЗАГРУЗКА",
                InstallState.VERIFYING: "ПРОВЕРКА ФАЙЛОВ", InstallState.APPLYING: "УСТАНОВКА",
                InstallState.FINALIZING: "ЗАВЕРШЕНИЕ", InstallState.READY: "ИГРАТЬ",
                InstallState.UPDATE_AVAILABLE: "ОБНОВИТЬ", InstallState.REPAIR_REQUIRED: "ВОССТАНОВИТЬ",
                InstallState.FAILED: "ПОВТОРИТЬ", InstallState.RUNNING: "ИГРА ЗАПУЩЕНА",
            }
            label = labels[snapshot.state]
            if snapshot.state == InstallState.DOWNLOADING and snapshot.bytes_total:
                label += f" · {int(snapshot.bytes_done * 100 / snapshot.bytes_total)}%"
            self.play.setText(label)
            busy = snapshot.state in {InstallState.CHECKING, InstallState.PREPARING, InstallState.DOWNLOADING,
                                      InstallState.VERIFYING, InstallState.APPLYING, InstallState.FINALIZING,
                                      InstallState.RUNNING}
            self.play.setEnabled(can_play and not busy)
            self.status.setText({
                InstallState.NOT_INSTALLED: "Требуется установка",
                InstallState.READY: "Установленная версия готова к запуску",
                InstallState.REPAIR_REQUIRED: "Обнаружены повреждённые или отсутствующие файлы",
                InstallState.FAILED: "Операция требует внимания",
            }.get(snapshot.state, label.title()))

    def _world(self, server_id: str) -> WorldView:
        return next(world for world in self.world_views if world.id == server_id)

    def _refresh_remote_content(self) -> None:
        if not self.remote_content.feed_url:
            return

        def worker():
            try:
                content = self.remote_content.fetch()
            except Exception:
                return
            self.remote_content_ready.emit(content)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_remote_content(self, content: dict[str, dict]) -> None:
        updated = self.remote_content.apply(self.world_views, content)
        self.remote_world_state = content
        if updated == self.world_views:
            return
        self.world_views = updated
        for world in updated:
            button = self.rail.buttons.get(world.id)
            if button:
                button.set_tooltip(f"{world.title}\nСтатус загружается отдельно")
            self._set_remote_status(world.id, content.get(world.id, {}))
        if self.current_server:
            self.world_page.set_world(
                self._world(self.current_server.id),
                bool(self.config.get("videoMuted", True)),
                bool(self.config.get("videoBackgrounds", True)),
            )
            item = content.get(self.current_server.id)
            if item and self.current_server.id not in self.server_states:
                self.world_page.set_server_status(item["status"], item["players"], item["maxPlayers"])

    def _set_remote_status(self, world_id: str, item: dict) -> None:
        if not item or world_id in self.server_states:
            return
        status = item.get("status", "unavailable")
        current = int(item.get("players", 0))
        maximum = int(item.get("maxPlayers", 0))
        self.rail.set_status(world_id, status, current, maximum)
        online = status == "online"
        self.discover_page.update_status(world_id, online, current, maximum)
        self.catalogue_page.update_status(world_id, online, current, maximum)

    def _server_checked(self, server_id, ok, current, maximum):
        self.server_states[server_id] = (ok, current, maximum)
        access = self.build_access.get(server_id, {})
        mode = str(access.get("mode", "OPEN")).upper()
        rail_state = "maintenance" if mode == "MAINTENANCE" else ("closed" if mode == "CLOSED" else ("online" if ok else "unavailable"))
        self.rail.set_status(server_id, rail_state, current, maximum)
        self.discover_page.update_status(server_id, ok, current, maximum)
        self.catalogue_page.update_status(server_id, ok, current, maximum)
        if self.current_server and self.current_server.id == server_id:
            self.select_server(self.current_server)
        self.status_bar.network.setText("● СЕРВИСЫ ДОСТУПНЫ" if any(value[0] for value in self.server_states.values()) else "● СТАТУС НЕДОСТУПЕН")

    def _build_access_ready(self, access):
        super()._build_access_ready(access)
        for world in self.world_views:
            state = self.build_access.get(world.id, {})
            mode = str(state.get("mode", "OPEN")).upper()
            if mode == "MAINTENANCE":
                self.rail.set_status(world.id, "maintenance")
            elif mode == "CLOSED":
                self.rail.set_status(world.id, "closed")
            elif world.server.visibility == "coming_soon":
                self.rail.set_status(world.id, "development")

    def _settings(self):
        self.settings_page.set_config(self.config, detect_java_label(self.config.get("java_path", "")), CURRENT_VERSION)
        self._navigate("settings", "NEXUS / НАСТРОЙКИ")

    def _save_config(self):
        atomic_write(CONFIG_FILE, self.config)

    def _launch_settings(self):
        if self._launch_lock.locked() or (self.game_process and self.game_process.poll() is None):
            QMessageBox.information(self, "Параметры игры", "Закройте Minecraft перед изменением параметров.")
            return
        dialog = SettingsDialog(self, self.config)
        if dialog.exec():
            self.config.update(dialog.values())
            self._save_config()
            self.status_bar.java.setText(detect_java_label(self.config.get("java_path", "")))
            self.settings_page.set_config(self.config, detect_java_label(self.config.get("java_path", "")), CURRENT_VERSION)

    def _platform_settings_changed(self, values: dict) -> None:
        self.config.update(values)
        self.studio_page.set_mode(bool(self.config.get("creatorMode", False)))
        self.rail.section_buttons["studio"].setVisible(bool(self.config.get("creatorMode", False)))
        self._save_config()
        reduced = bool(self.config.get("reducedMotion", False))
        self.world_page.set_reduced_motion(reduced)
        self.world_page.media.set_muted(bool(self.config.get("videoMuted", True)))
        if self.current_server and self._current_page == "world":
            self.world_page.set_world(
                self._world(self.current_server.id),
                bool(self.config.get("videoMuted", True)),
                bool(self.config.get("videoBackgrounds", True)),
            )

    def _world_menu(self, anchor):
        if not self.current_server:
            return
        menu = self._make_world_menu(self.current_server)
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomRight()))

    def _rail_menu(self, world: WorldView, position):
        self._make_world_menu(world.server).exec(position)

    def _make_world_menu(self, server):
        menu = QMenu(self)
        menu.addAction("Открыть", lambda: self.show_server(server))
        menu.addAction("Играть", lambda: (self.select_server(server), self._play()))
        menu.addSeparator()
        menu.addAction("Проверить файлы", lambda: (self.select_server(server), self._repair_pack()))
        menu.addAction("Моды", lambda: (self.select_server(server), self._show_mods()))
        menu.addAction("Optional Mods", lambda: (self.select_server(server), self._optional_mods()))
        menu.addAction("Параметры запуска", self._launch_settings)
        menu.addSeparator()
        menu.addAction("Открыть папку", lambda: (self.select_server(server), self._open_folder()))
        menu.addAction("Логи", lambda: (self.select_server(server), self._show_logs()))
        pinned = server.id in self.config.get("pinnedWorlds", [])
        menu.addAction("Убрать из панели" if pinned else "Добавить в панель", lambda: self._toggle_pin(server.id))
        menu.addSeparator()
        menu.addAction("О мире", lambda: QMessageBox.information(self, self._world(server.id).title, self._world(server.id).description))
        return menu

    def _toggle_pin(self, server_id: str):
        pinned = [str(item) for item in self.config.get("pinnedWorlds", [])]
        if server_id in pinned:
            pinned.remove(server_id)
        else:
            pinned.append(server_id)
        self.config["pinnedWorlds"] = pinned
        self._save_config()
        button = self.rail.buttons.get(server_id)
        if button:
            button.setVisible(server_id in pinned)

    def _add_to_nexus(self):
        menu = QMenu(self)
        menu.addAction("Найти мир", lambda: self._navigate("worlds", "NEXUS / МИРЫ"))
        menu.addAction("Создать свою сборку", self._create_instance)
        menu.addAction("Импортировать сборку", self._import_instance)
        menu.exec(self.rail.mapToGlobal(self.rail.rect().center()))

    def _create_instance(self):
        self.show_instances()
        self.instances_page._create()

    def _import_instance(self):
        self.show_instances()
        self.instances_page._import_zip()

    def _show_mods(self):
        updater = ModpackUpdater(self._instance_dir(), lambda _message: None)
        optional = {
            str(item.get("filename", "")).lower()
            for item in updater.optional_catalog()
            if item.get("filename")
        }
        self.mods_page.set_instance(self._instance_dir(), optional)
        self._navigate("mods", f"{self._world(self.current_server.id).title} / МОДЫ")

    def _open_mods_folder(self):
        folder = self._instance_dir() / "mods"
        folder.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(folder)

    def _open_instance_diagnostics(self):
        from .instance_diagnostics_dialog import InstanceDiagnosticsDialog
        dialog = InstanceDiagnosticsDialog(self._instance_dir(), self.current_server.loader, self.current_server.name, self)
        dialog.exec()

    def _show_logs(self):
        self.logs_page.set_instance(self._instance_dir())
        self._navigate("logs", "NEXUS / ЛОГИ")

    def _open_logs_folder(self):
        folder = self._instance_dir() / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(folder)

    def _refresh_storage(self):
        self.settings_page.storage.setText("Подсчёт использования диска…")

        def worker():
            values = []
            temp = 0
            backups = 0
            for world in self.world_views:
                path = self._instance_dir_for(world.server)
                values.append((world.title, self._directory_size(path)))
                temp += self._directory_size(path / ".nexus-launcher" / "staging")
                backups += self._directory_size(path / ".nexus-launcher" / "backup-files")
            custom = self._directory_size(self.instance_service.root)
            cache = self._directory_size(APP_DIR / "cache")
            backup_root = APP_DIR / "backups"
            backups += self._directory_size(backup_root)
            launcher_files = sum(path.stat().st_size for path in APP_DIR.iterdir() if path.is_file() and not path.is_symlink()) if APP_DIR.is_dir() else 0
            rows = [("Nexus Launcher", launcher_files), *values, ("Мои сборки", custom), ("Кэш", cache),
                    ("Временные файлы", temp), ("Резервные копии", backups)]
            text = "\n".join(f"{name:<22} {self._format_size(size)}" for name, size in rows)
            self.bridge.status.emit("STORAGE::" + text)

        threading.Thread(target=worker, daemon=True).start()

    def _instance_dir_for(self, server) -> Path:
        """Resolve an official instance without mutating UI selection state."""
        if server.instance_id:
            return self._storage_root / "instances" / server.instance_id
        for project in self.projects:
            if server in project.servers:
                return self._storage_root / "instances" / project.id / server.id
        return self._storage_root / "instances" / "default" / server.id

    @staticmethod
    def _directory_size(root: Path) -> int:
        total = 0
        if not root.is_dir():
            return 0
        for base, directories, files in os.walk(root, followlinks=False):
            directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()]
            for name in files:
                path = Path(base) / name
                try:
                    if not path.is_symlink():
                        total += path.stat().st_size
                except OSError:
                    continue
        return total

    @staticmethod
    def _format_size(value: int) -> str:
        size = float(value)
        for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
            if size < 1024 or unit == "ТБ":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} ТБ"

    def _set_status(self, text):
        if str(text).startswith("STORAGE::"):
            self.settings_page.storage.setText(str(text).split("::", 1)[1])
            return
        self.status.setText(text)
        self.downloads_page.detail.setText(text)
        lowered = str(text).lower()
        states = (
            ("провер", "ПРОВЕРКА"),
            ("скач", "СКАЧИВАНИЕ"),
            ("устан", "УСТАНОВКА"),
            ("запуск", "ЗАПУСК"),
        )
        for marker, label in states:
            if marker in lowered and self.game_process is None:
                self.play.setText(label)
                break
        if self.current_server and "доступно обновление" in lowered:
            self.rail.set_update_available(self.current_server.id, True)

    def _progress(self, done, total):
        self._last_progress_total = total
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.progress.setVisible(total > 0)
        operation_server = getattr(self, "_launch_server", None)
        world_name = self._world(operation_server.id).title if operation_server else "NEXUS"
        self.downloads_page.update_progress(world_name, done, total, self.status.text())
        self.status_bar.set_download(world_name, done, total)
        lowered = self.status.text().lower()
        if total > 0 and not self._download_auto_opened and self._current_page == "world" and any(marker in lowered for marker in ("скач", "загруз", "устан")):
            self._download_auto_opened = True
            self._navigate("downloads", "NEXUS / ЗАГРУЗКИ")
        if operation_server:
            self.rail.set_download_progress(operation_server.id, done, total)

    def _updater_progress(self, event):
        try:
            world = self._world(event.instance_id)
            world_name = world.title
        except (KeyError, StopIteration):
            world_name = event.instance_id or "NEXUS"
        self.downloads_page.update_event(event, world_name)
        if event.bytes_total:
            self.status_bar.set_download(world_name, event.bytes_done, event.bytes_total, self.downloads_page.current_speed)
        state = {
            "download": InstallState.DOWNLOADING, "downloading": InstallState.DOWNLOADING,
            "verifying": InstallState.VERIFYING, "applying": InstallState.APPLYING,
            "finalizing": InstallState.FINALIZING, "ready": InstallState.READY,
        }.get(str(event.phase).lower())
        if state:
            self._install_states[event.instance_id] = state
            if self.current_server and self.current_server.id == event.instance_id:
                labels = {InstallState.DOWNLOADING: "ЗАГРУЗКА", InstallState.VERIFYING: "ПРОВЕРКА ФАЙЛОВ",
                          InstallState.APPLYING: "УСТАНОВКА", InstallState.FINALIZING: "ЗАВЕРШЕНИЕ",
                          InstallState.READY: "ИГРАТЬ"}
                label = labels[state]
                if state == InstallState.DOWNLOADING and event.bytes_total:
                    label += f" · {int(event.bytes_done * 100 / event.bytes_total)}%"
                self.play.setText(label)
        if event.instance_id in self.rail.buttons:
            denominator = event.bytes_total or max(event.bytes_done, 1)
            self.rail.set_download_progress(event.instance_id, event.bytes_done, denominator)

    def _reset_play(self):
        super()._reset_play()
        self._download_auto_opened = False
        self.downloads_page.update_progress("", 0, 0)
        self.status_bar.set_download("", 0, 0)
        if self.current_server:
            self.rail.set_download_progress(self.current_server.id, 0, 0)
            self.rail.set_update_available(self.current_server.id, False)
            self.select_server(self.current_server)

    def _retry_download(self, instance_id):
        server = next((world.server for world in self.world_views if world.id == instance_id), None)
        if server:
            self.select_server(server)
            self._play()

    def _failed(self, text):
        super()._failed(text)
        self.downloads_page.show_failure(str(text))

    def _launched(self, pid):
        super()._launched(pid)
        server = getattr(self, "_launch_server", None)
        if server:
            ModpackUpdater(self._instance_dir_for(server), instance_id=server.id).mark_running(True)
        self.play.setText("ИГРА ЗАПУЩЕНА · ОСТАНОВИТЬ")

    def _game_exited(self, return_code):
        server = getattr(self, "_launch_server", None)
        super()._game_exited(return_code)
        if server:
            ModpackUpdater(self._instance_dir_for(server), instance_id=server.id).mark_running(False)
            if self.current_server and self.current_server.id == server.id:
                self.select_server(server)

    def _video_muted_changed(self, muted: bool):
        self.config["videoMuted"] = muted
        self._save_config()

    def _application_state_changed(self, state):
        if state == Qt.ApplicationInactive:
            self.world_page.media.pause()
        elif state == Qt.ApplicationActive and self._current_page == "world":
            self.world_page.media.resume(automatic=True)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            self.world_page.media.pause()
        super().changeEvent(event)

    def hideEvent(self, event):
        self.world_page.media.pause()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._current_page == "world" and not self.isMinimized():
            self.world_page.media.resume(automatic=True)

    def closeEvent(self, event):
        if not self.studio_page.may_leave():
            event.ignore()
            return
        if self._launch_lock.locked() and not (self.game_process and self.game_process.poll() is None):
            answer = QMessageBox.warning(
                self,
                "Идёт установка",
                "Nexus сейчас устанавливает или проверяет мир. Закрытие прервёт операцию; при следующем запуске она будет безопасно продолжена или откачена.",
                QMessageBox.Close | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Close:
                event.ignore()
                return
        self.world_page.release()
        self._focus_visible_tracker.stop()
        super().closeEvent(event)
