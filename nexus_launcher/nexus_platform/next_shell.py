"""NEXUS navigation adapter; installation and launch remain in PlatformLauncher."""
import threading
from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStyle, QStyleOptionToolButton, QVBoxLayout, QWidget

from nexus_launcher.modern_main import LoginDialog
from nexus_launcher.nexus_account import AccountError
from .pack_library import PackLibraryPage
from .presentation import NexusOverview, NexusProfile, NexusWorldPage, SavedWorlds
from .presentation_style import stylesheet
from .theme_tokens import TOKENS
from .registration import RegistrationDialog, WebsiteRegistrationClient
from .settings_workspace import SettingsWorkspace
from .widgets import RailButton, WorldRail
from .window import PlatformLauncher


class SidebarButton(RailButton):
    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QPainter(self)
        self.style().drawComplexControl(QStyle.CC_ToolButton, option, painter, self)
        painter.setPen(QColor(TOKENS["accent"] if self.property("dataActive") else TOKENS["muted"]))
        painter.drawText(self.rect().adjusted(14, 0, -14, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text())


def settings_icon():
    import math
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(TOKENS["muted"]), 1.5))
    points = []
    for index in range(32):
        angle = index * math.pi / 16
        radius = 9 if index % 4 in (0, 1) else 7
        points.append(QPointF(12 + radius * math.cos(angle), 12 + radius * math.sin(angle)))
    painter.drawPolygon(QPolygonF(points))
    painter.drawEllipse(QPointF(12, 12), 3, 3)
    painter.end()
    return QIcon(pixmap)


class NexusLogin(LoginDialog):
    """Existing credentials contract with bounded, labeled NEXUS form controls."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setMinimumSize(460, 500)
        self.setMaximumSize(16777215, 16777215)
        self.resize(480, 520)
        root = self.layout()
        for field, caption in ((self.identifier, "Ник или электронная почта"), (self.password, "Пароль")):
            label = QLabel(caption)
            label.setBuddy(field)
            root.insertWidget(root.indexOf(field), label)
        self.reveal = self.password_visibility
        for button in self.findChildren(QPushButton):
            if button.text() == "Войти":
                button.setObjectName("primaryAction")

class GreyCube(QWidget):
    """Vector-rendered neutral three-dimensional placeholder, without a face."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 40)
        self.setAccessibleName("Серый объёмный аватар")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for color, points in (
            ("#b4b6ba", [(3, 10), (18, 4), (33, 10), (18, 16)]),
            ("#96999e", [(3, 10), (18, 16), (18, 34), (3, 28)]),
            ("#73777e", [(18, 16), (33, 10), (33, 28), (18, 34)]),
        ):
            painter.setBrush(QColor(color))
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in points]))


class NexusSidebar(WorldRail):
    """Reuses the rail's status/selection contract with readable navigation labels."""
    def __init__(self, worlds, pinned, parent=None):
        QFrame.__init__(self, parent)
        self.setObjectName("nexusSidebar")
        self.setMinimumWidth(0)
        self.setMaximumWidth(258)
        self.buttons, self.section_buttons = {}, {}
        self.selectedWorldId = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 28, 16, 18)
        root.setSpacing(12)
        logo = QLabel("N E X U S")
        logo.setObjectName("nexusBrand")
        root.addWidget(logo)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setMinimumWidth(0)
        menu = QVBoxLayout(body)
        menu.setContentsMargins(0, 16, 0, 0)
        menu.setSpacing(6)
        for route, label, signal in (
            ("home", "Обзор", self.home_requested),
            ("library", "Мои сборки", self.library_requested),
            ("saved", "Мои миры", self.worlds_requested),
            ("downloads", "Загрузки", self.downloads_requested),
            ("news", "Новости", self.news_requested),
            ("studio", "Студия", self.studio_requested),
        ):
            button = self._button(label)
            button.clicked.connect(signal)
            self.section_buttons[route] = button
            menu.addWidget(button)
        catalogue = self._button("Каталог")
        self.section_buttons["worlds"] = catalogue
        menu.insertWidget(3, catalogue)
        label = QLabel("МОИ СЕРВЕРЫ")
        label.setObjectName("sidebarCaption")
        menu.addSpacing(20)
        menu.addWidget(label)
        for world in worlds:
            button = self._button(world.title)
            button.clicked.connect(lambda _=False, item=world: self.world_requested.emit(item))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda point, item=world, control=button:
                self.world_menu_requested.emit(item, control.mapToGlobal(point)))
            button.setVisible(world.id in pinned)
            menu.addWidget(button)
            self.buttons[world.id] = button
        add = self._button("Добавить сервер")
        add.clicked.connect(self.add_requested)
        menu.addWidget(add)
        menu.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.footer = QHBoxLayout()
        self.footer.addWidget(GreyCube())
        root.addLayout(self.footer)
        self.settings = RailButton("", "Глобальные настройки")
        self.settings.setIcon(settings_icon())
        self.settings.setIconSize(QSize(22, 22))
        self.settings.setObjectName("settingsSquare")
        self.settings.setFixedSize(40, 40)
        self.settings.setAccessibleName("Глобальные настройки")
        self.settings.setToolTip("Глобальные настройки")
        self.settings.clicked.connect(self.settings_requested)
        self.section_buttons["settings"] = self.settings
        credit = QLabel("Сделано ForceCore")
        credit.setObjectName("sidebarCaption")
        root.addWidget(credit)

    @staticmethod
    def _button(label):
        button = SidebarButton(label, label)
        button.setMinimumWidth(0)
        button.setMaximumWidth(16777215)
        button.setFixedHeight(46)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setObjectName("sidebarNavigation")
        return button

    def select_route(self, route, world_id=""):
        super().select_route(route, world_id)
        self.settings.setProperty("dataActive", route == "settings")

    def sizeHint(self):
        return QSize(258, 700)


class NexusLauncher(PlatformLauncher):
    """Approved presentation over the original installation/account services."""
    def _build(self):
        super()._build()
        self._replace_presentation_pages()
        original_instances = self.instances_page
        self.pages.removeWidget(original_instances)
        self.instances_page = PackLibraryPage(self.instance_service, self)
        self.instances_page.backup_retention = original_instances.backup_retention
        self.instances_page.launch_requested.connect(self._launch_user_instance)
        self.page_map["library"] = self.instances_page
        self.pages.addWidget(self.instances_page)
        original_instances.deleteLater()
        layout = self.centralWidget().layout()
        old_rail = self.rail
        layout.removeWidget(old_rail)
        old_rail.hide()
        old_rail.deleteLater()
        self.rail = NexusSidebar(self.world_views, self.config.get("pinnedWorlds", []))
        layout.insertWidget(0, self.rail)
        for signal, callback in (
            (self.rail.home_requested, self.show_catalog),
            (self.rail.library_requested, self.show_instances),
            (self.rail.worlds_requested, self._show_saved_worlds),
            (self.rail.downloads_requested, lambda: self._navigate("downloads", "NEXUS / ЗАГРУЗКИ")),
            (self.rail.news_requested, lambda: self._navigate("news", "NEXUS / НОВОСТИ")),
            (self.rail.studio_requested, self._show_studio),
            (self.rail.settings_requested, self._settings),
            (self.rail.add_requested, self._add_to_nexus),
            (self.rail.world_requested, lambda world: self.show_server(world.server)),
            (self.rail.world_menu_requested, self._rail_menu),
        ):
            signal.connect(callback)
        self.rail.section_buttons["worlds"].clicked.connect(lambda: self._navigate("worlds", "NEXUS / КАТАЛОГ"))
        self.rail.section_buttons["studio"].setVisible(bool(self.config.get("creatorMode", False)))
        self.title_bar.layout().removeWidget(self.profile)
        self.profile.setParent(self.rail)
        self.profile.setMinimumWidth(0)
        self.rail.footer.addWidget(self.profile, 1)
        self.rail.footer.addWidget(self.rail.settings)
        self.profile.show()
        self.profile.setText("NEXUS профиль")
        self.profile.setAccessibleName("Открыть профиль NEXUS")
        self.profile_page = NexusProfile(self)
        self.page_map["profile"] = self.profile_page
        self.pages.addWidget(self.profile_page)
        self.status_bar.hide()
        self.registration_button = QPushButton("Создать аккаунт NEXUS")
        self.registration_button.setMinimumHeight(36)
        self.registration_button.clicked.connect(self._register_account)
        self.rail.layout().insertWidget(self.rail.layout().count() - 2, self.registration_button)
        self.registration_button.setVisible(not self.account_profile)
        self.navigation_toggle = QPushButton("Скрыть навигацию")
        self.navigation_toggle.setAccessibleName("Скрыть навигацию")
        self.navigation_toggle.setCheckable(True)
        self.navigation_toggle.clicked.connect(self._toggle_navigation)
        self.title_bar.layout().insertWidget(0, self.navigation_toggle)
        self._sidebar_animation = QPropertyAnimation(self.rail, b"maximumWidth", self)
        self._sidebar_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._sidebar_animation.finished.connect(self._finish_sidebar_animation)
        # Restore space at route boundaries; never place a transparent overlay over pages.
        self.rail.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        settings_shell = self.settings_page.findChild(QFrame, "settingsShell")
        settings_shell.setMinimumWidth(0)
        self.settings_page.categories.setFixedWidth(160)
        self.pages.removeWidget(self.settings_page)
        self.settings_scroll = SettingsWorkspace(self.settings_page)
        self.settings_page.hide()
        self.page_map["settings"] = self.settings_scroll
        self.pages.addWidget(self.settings_scroll)

    def _replace_presentation_pages(self):
        for key, attribute, replacement in (
            ("home", "discover_page", NexusOverview(self.world_views)),
            ("world", "world_page", NexusWorldPage()),
        ):
            previous = getattr(self, attribute)
            self.pages.removeWidget(previous)
            previous.hide()
            previous.deleteLater()
            setattr(self, attribute, replacement)
            self.page_map[key] = replacement
            self.pages.addWidget(replacement)
        self.catalog = self.discover_page
        self.discover_page.world_requested.connect(lambda world: self.show_server(world.server))
        self.world_page.play_requested.connect(self._play)
        self.world_page.menu_requested.connect(self._world_menu)
        self.world_page.video_muted_changed.connect(self._video_muted_changed)
        self.world_page.save_requested.connect(self._save_world)
        self.world_page.set_reduced_motion(bool(self.config.get("reducedMotion", False)))
        self.play = self.catalog_play = self.world_page.play
        self.progress = self.catalog_progress = self.world_page.progress
        self.status = self.catalog_status = self.world_page.client_status
        self.details_title = self.world_page.title
        self.details_status = self.world_page.status
        self.saved_worlds = SavedWorlds(self)
        self.saved_worlds.world_requested.connect(lambda world: self.show_server(world.server))
        self.saved_worlds.catalogue_requested.connect(lambda: self._navigate("worlds", "NEXUS / КАТАЛОГ"))
        self.page_map["saved"] = self.saved_worlds
        self.pages.addWidget(self.saved_worlds)

    def _show_saved_worlds(self):
        self.saved_worlds.refresh()
        self._navigate("saved", "NEXUS / МОИ МИРЫ")

    def _save_world(self):
        if not self.current_server:
            return
        saved = list(self.config.get("savedWorlds", []))
        identifier = self.current_server.id
        if identifier in saved:
            saved.remove(identifier)
        else:
            saved.append(identifier)
        self.config["savedWorlds"] = saved
        self._save_config()
        self._sync_saved_world()

    def _sync_saved_world(self):
        saved = self.current_server and self.current_server.id in self.config.get("savedWorlds", [])
        self.world_page.save.setText("Убрать мир" if saved else "Сохранить мир")

    def select_server(self, server):
        super().select_server(server)
        self._sync_saved_world()

    def show_catalog(self):
        self._navigate("home", "NEXUS / ОБЗОР")

    def _profile_menu(self):
        # Account is a route, not a downward popup anchored at the window bottom.
        self.profile_page.sync()
        self._navigate("profile", "NEXUS / ПРОФИЛЬ")

    def show_instances(self):
        self.instances_page.refresh()
        self._navigate("library", "NEXUS / МОИ СБОРКИ")

    def _register_account(self):
        if not self.profile.isEnabled():
            return
        if "registration" in self.page_map:
            self._navigate("registration", "NEXUS / РЕГИСТРАЦИЯ")
            return
        client = WebsiteRegistrationClient(self.account_client.base_url)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        dialog = RegistrationDialog(client, page)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        dialog.setMaximumWidth(560)
        layout.addStretch()
        layout.addWidget(dialog, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        page.registration_form = dialog
        def saved(nickname):
            # Presentation only. A completed website registration is not a launcher session.
            self.registration_nickname = nickname
            self.registration_button.hide()
            self.profile.setText(nickname)
        dialog.profile_saved.connect(saved)
        self.page_map["registration"] = page
        self.pages.addWidget(page)

        def finished(result):
            identifier = dialog.nick.text().strip() if result and dialog.profile_completed else ""
            self.pages.removeWidget(page)
            self.page_map.pop("registration", None)
            self._navigate("profile", "NEXUS / ПРОФИЛЬ")
            if result:
                self.profile_page.sync()
            page.deleteLater()
            if identifier:
                # Match the tester handoff: only prefill identity, never reuse a
                # registration password or treat registration as a login grant.
                QTimer.singleShot(0, self, lambda: self._login_account(identifier))
        dialog.finished.connect(finished)
        self._navigate("registration", "NEXUS / РЕГИСТРАЦИЯ")

    def _login_account(self, identifier=""):
        if not self.profile.isEnabled():
            return
        dialog = NexusLogin(self)
        if isinstance(identifier, str):
            dialog.identifier.setText(identifier)
            if identifier:
                dialog.password.setFocus()
        if not dialog.exec():
            dialog.password.clear()
            return
        identifier, password = dialog.credentials()
        totp_code, recovery_code = dialog.second_factor()
        dialog.password.clear()
        if not identifier or not password:
            QMessageBox.warning(self, "NEXUS Launcher", "Введите ник или почту и пароль.")
            return
        self.profile.setEnabled(False)
        self.profile.setText("Вход…")
        self.profile_page.sync()
        threading.Thread(target=self._login_account_worker, args=(identifier, password, totp_code, recovery_code), daemon=True).start()

    def _account_failed(self, message):
        super()._account_failed(message)
        self.profile.setText("NEXUS профиль")
        self.profile_page.sync()

    def _refresh_account(self):
        if not self.profile.isEnabled():
            return
        self.profile.setEnabled(False)
        self.profile_page.sync()

        def refresh():
            try:
                self.bridge.account_ready.emit(self.account_client.restore())
            except AccountError as error:
                self.bridge.account_failed.emit(str(error))

        threading.Thread(target=refresh, daemon=True).start()

    def _logout_account(self):
        if not self.profile.isEnabled():
            return
        super()._logout_account()
        self.profile.setText("NEXUS профиль")
        self.registration_button.show()
        self.profile_page.sync()

    def _account_ready(self, profile):
        self.registration_nickname = ''
        super()._account_ready(profile)
        if hasattr(self, "registration_button"):
            self.registration_button.setVisible(not self.account_profile)
            self.profile.setText("NEXUS профиль")
            self.profile_page.sync()

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.instances_page.shutdown_catalog()

    def _finish_sidebar_animation(self):
        if self.navigation_toggle.isChecked():
            self.rail.hide()

    def _toggle_navigation(self, collapsed):
        self._sidebar_animation.stop()
        self.rail.show()
        self.navigation_toggle.setText("Показать навигацию" if collapsed else "Скрыть навигацию")
        self.navigation_toggle.setAccessibleName(self.navigation_toggle.text())
        target = 0 if collapsed else 258
        if self.config.get("reducedMotion", False):
            self.rail.setMaximumWidth(target)
            self._finish_sidebar_animation()
        else:
            self._sidebar_animation.setDuration(220)
            self._sidebar_animation.setStartValue(self.rail.width())
            self._sidebar_animation.setEndValue(target)
            self._sidebar_animation.start()

    def _style(self):
        self.setStyleSheet(stylesheet())
