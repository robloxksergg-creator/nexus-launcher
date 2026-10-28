"""Sanitized presentation state and validated action adapter over existing owners.

Browser receives display fields only. No filesystem paths, tokens, emails,
credentials or arbitrary Python capabilities cross the renderer boundary.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget

from .prototype_host import PrototypeHost, PrototypePage, same_origin


ACTIONS = frozenset({"support", "leave", "library", "settings", "downloads", "logs", "studio", "academy",
                     "create", "open-build", "play-build", "select-server", "play-server",
                     "save-server", "pin-server", "server-tools", "login", "register",
                     "logout", "refresh-profile", "edit-profile", "fullscreen", "refresh", "stop-game"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class DesignPage(PrototypePage):
    ui_action = Signal(str, str)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if url.path().startswith("/ui-action/"):
            name = url.path().removeprefix("/ui-action/")
            raw_query = url.query()
            # A command needs at most one short ID, not an unbounded query parser.
            if len(raw_query) > 1024:
                return False
            try:
                query = parse_qs(raw_query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
            except ValueError:
                return False
            identifier = query.get("id", [""])[0]
            valid_query = not query or (set(query) == {"id"} and len(query["id"]) == 1
                                       and bool(IDENTIFIER.fullmatch(identifier)))
            if (is_main_frame and name in ACTIONS and valid_query and not url.fragment()
                    and same_origin(url.toString(), self.origin)
                    and same_origin(self.url().toString(), self.origin)):
                self.ui_action.emit(name, identifier)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


def build_display(instance):
    """Read-only projection; never serialize a domain object wholesale."""
    return {"id": instance.id, "name": instance.name, "version": instance.minecraft_version,
            "loader": instance.loader, "mods": len(instance.installed_mods),
            "state": instance.state, "lastPlayed": instance.last_launch}


def world_display(world, services):
    server = world.server
    state = services.server_states.get(world.id)
    remote = services.remote_world_state.get(world.id, {})
    access = services.build_access.get(world.id, {})
    status = "unknown"
    players = None
    if not server.address:
        status = "local"
    elif state:
        status = "online" if state[0] else "unavailable"
        if state[0]:
            players = f"{state[1]} / {state[2]}"
    elif remote.get("status"):
        status = remote["status"]
        if status == "online" and "players" in remote:
            players = f"{remote['players']} / {remote.get('maxPlayers', '—')}"
    if server.visibility == "coming_soon":
        status = "development"
    mode = str(access.get("mode", "OPEN")).upper()
    allowed = bool(access.get("allowed", mode == "OPEN")) and status != "development"
    if mode in {"CLOSED", "MAINTENANCE"}:
        status = "maintenance" if mode == "MAINTENANCE" else "closed"
    snapshot = services._install_states.get(world.id)
    # Existing updater callbacks store either a DeliverySnapshot or InstallState.
    phase = getattr(snapshot, "state", snapshot)
    delivery = str(getattr(phase, "value", "not_installed"))
    artwork = {"main": "gearmorph-official.png", "building": "minecraft-city.png",
               "pinewood": "minecraft-meadow.png", "elderfall": "minecraft-mountain.png",
               "tech": "minecraft-desert.png"}.get(world.id, "minecraft-meadow.png")
    return {"id": world.id, "name": world.title, "description": world.description,
            "category": world.category, "version": server.minecraft_version, "loader": server.loader,
            "artwork": "/" + artwork, "status": status, "players": players,
            "allowed": allowed, "delivery": delivery, "local": not bool(server.address),
            "saved": world.id in services.config.get("savedWorlds", []),
            "pinned": world.id in services.config.get("pinnedWorlds", []),
            "accent": world.theme.accent}


class LibraryProjection(QObject):
    ready = Signal(object, str)

    def __init__(self, service, parent):
        super().__init__(parent)
        self.service = service
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nexus-display")
        self.pending = False
        self.closed = False

    def refresh(self):
        if self.pending or self.closed:
            return
        self.pending = True

        def read():
            try:
                value = [build_display(item) for item in self.service.list()[:512]]
                error = ""
            except (OSError, ValueError, TypeError):
                value, error = [], "Не удалось прочитать библиотеку. Проверьте доступ к папке данных."
            if not self.closed:
                self.ready.emit(value, error)
        self.pool.submit(read)

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)


class DesignHost(PrototypeHost):
    """NEXUS 2.0 shell. Existing native workflows occupy its content region."""
    page: DesignPage
    def __init__(self, services):
        super().__init__(services, redesigned=True)
        self.setWindowTitle("NEXUS 2.0")
        self.setMinimumSize(1000, 640)
        self._builds = []
        self._library_error = ""
        self._last_state = ""
        self._native_route = "library"
        self._routing = False
        self._original_navigate = services._navigate
        services._navigate = self._service_route
        from .utility_workspaces import polish_downloads
        polish_downloads(services.downloads_page)
        from .dialog_presentation import NativePresentation
        self.native_presentation = NativePresentation(self, services.instances_page)
        self.page.ui_action.connect(lambda name, identifier: QTimer.singleShot(0, lambda: self._action(name, identifier)))
        self.projection = LibraryProjection(services.instance_service, self)
        self.projection.ready.connect(self._library_ready)
        self.projection.refresh()
        self.projection_timer = QTimer(self)
        self.projection_timer.timeout.connect(self.projection.refresh)
        self.projection_timer.start(5000)
        self.state_timer = QTimer(self)
        self.state_timer.timeout.connect(self._sync_state)
        self.state_timer.start(750)
        self.view.loadFinished.connect(lambda ok: self._sync_state(True) if ok else None)
        # Native pages retain their original operation authority; routes resulting
        # from those operations are mirrored back into this persistent shell.
        services.downloads_page.worlds_requested.connect(lambda: self._show_web_route("catalog"))
        services.downloads_page.logs_requested.connect(lambda: self._embed("logs"))
        services.settings_page.logs_requested.connect(lambda: self._embed("logs"))
        services.settings_page.studio_requested.connect(lambda: self._embed("studio"))
        services.settings_page.tech_center_requested.connect(lambda: self._embed("tech"))

    def _library_ready(self, value, error):
        self.projection.pending = False
        self._builds, self._library_error = value, error
        self._sync_state()

    def _sync_state(self, force=False):
        profile = self.services.account_profile
        value = {"worlds": [world_display(world, self.services) for world in self.services.world_views],
                 "builds": self._builds, "libraryError": self._library_error,
                 "profile": {"nickname": (profile.display_name or profile.minecraft_nick) if profile else None,
                             "username": profile.username if profile else None,
                             "pendingNickname": getattr(self.services, "registration_nickname", "") if not profile else "",
                             "demo": bool(getattr(self.services, "registration_demo", False)),
                             "busy": not self.services.profile.isEnabled()},
                 "recent": list(self.services.config.get("recentWorlds", [])),
                 "creator": bool(self.services.config.get("creatorMode", False)),
                 "reducedMotion": bool(self.services.config.get("reducedMotion", False)),
                 "sound": self.server.preferences.sound_enabled(),
                 "gameRunning": bool(self.services.game_process and self.services.game_process.poll() is None)}
        from PySide6.QtWebEngineCore import QWebEngineSettings
        encoded = json.dumps(value, ensure_ascii=True)
        if force or encoded != self._last_state:
            self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, not value['reducedMotion'])
            self._last_state = encoded
            self.page.runJavaScript("window.NexusUI?.setState(" + encoded + ")")

    def _find_build(self, identifier):
        page = self.services.instances_page
        for index in range(page.instances.count()):
            if page.instances.item(index).data(Qt.ItemDataRole.UserRole) == identifier:
                page.instances.setCurrentRow(index)
                return page.instances.item(index)
        return None

    def _action(self, name, identifier):
        targets = {"support": "support", "leave": "home", "library": "library", "settings": "settings",
                   "downloads": "downloads", "logs": "logs", "studio": "studio",
                   "create": "library", "open-build": "library", "play-build": "library",
                   "select-server": "world", "play-server": "world"}
        if name in targets and not self._navigation_allowed(targets[name]):
            return
        if name in targets:
            self.services._current_page = targets[name]
        if name == "academy":
            if not self._navigation_allowed("studio"):
                return
            self.services.studio_page.open_creator(True)
            self._embed("studio")
        elif name == "leave":
            self.services._current_page = "home"
            self._hide_library()
        elif name in {"support", "library", "settings", "downloads", "logs", "studio"}:
            if name != "studio" or self.services.config.get("creatorMode", False):
                self._embed(name)
        elif name in {"open-build", "play-build", "create"}:
            self._embed("library")
            page = self.services.instances_page
            if name == "create":
                page._create()
            else:
                item = self._find_build(identifier)
                if item is None:
                    self.page.runJavaScript("window.NexusUI?.notify('Сборка больше не найдена. Обновите библиотеку.')")
                    return
                page._open_card(item)
                if name == "play-build":
                    page._launch()
            self.projection.refresh()
        elif name in {"select-server", "play-server", "save-server", "pin-server", "server-tools"}:
            if name == "select-server":
                self._hide_library()
            world = next((item for item in self.services.world_views if item.id == identifier), None)
            if world is None:
                return
            if name == "pin-server":
                self.services._toggle_pin(identifier)
            else:
                self.services.select_server(world.server)
                if name in {"select-server", "play-server"}:
                    self.services._current_page = "world"
                if name == "save-server":
                    self.services._save_world()
                elif name == "play-server":
                    if not self.services.account_profile:
                        self.services._login_account()
                    elif self.services.play.isEnabled() and not (self.services.game_process and self.services.game_process.poll() is None):
                        self.services._play()
                elif name == "server-tools":
                    self.services._make_world_menu(world.server).exec(QCursor.pos())
            self._sync_state(True)
        elif name in {"login", "register", "logout", "refresh-profile", "edit-profile"}:
            callback = {"login": self.services._login_account, "register": self.services._register_account,
                        "logout": self.services._logout_account, "refresh-profile": self.services._refresh_account,
                        "edit-profile": self.services._open_web_profile}[name]
            callback()
            self._sync_state(True)
        elif name == "stop-game":
            self.services._stop_game()
            self._sync_state(True)
        elif name == "fullscreen":
            self.showMaximized() if self.isFullScreen() else self.showFullScreen()
        elif name == "refresh":
            self.projection.refresh()
            self._sync_state(True)

    def _show_web_route(self, route):
        self._hide_library()
        self.page.runJavaScript("window.NexusUI?.navigate(" + json.dumps(route) + ")")

    def _service_route(self, key, context):
        # Existing operation callbacks continue to use their original routing
        # contract. Presentation is mirrored only after the operation chooses it.
        if self._routing:
            return
        if not self._navigation_allowed(key):
            return
        self.services._current_page = key
        if key in {"settings", "logs", "mods", "downloads", "studio", "tech", "library", "registration"}:
            self._embed(key)
        elif key in {"home", "worlds", "saved", "profile"}:
            self._show_web_route({"worlds": "catalog"}.get(key, key))
        elif key == "world" and self.services.current_server:
            self._hide_library()
            self.page.runJavaScript("window.NexusUI?.navigate('server'," + json.dumps(self.services.current_server.id) + ")")

    def _navigation_allowed(self, route):
        if self.services._current_page == "registration" and route != "registration":
            page = self.services.page_map.get("registration")
            form = getattr(page, "registration_form", None)
            if form and form.busy:
                form.error.setText("Дождитесь ответа сайта. Запрос уже отправлен.")
                return False
            if form and not form.completed:
                form._reset()
                form.password.clear()
                form.confirm.clear()
        if (self.services._current_page == "studio" and route != "studio"
                and not self.services.studio_page.may_leave()):
            self.page.runJavaScript("window.NexusNativeLibrary?.enter('studio')")
            return False
        return True

    def _embed(self, route):
        if not self._navigation_allowed(route):
            return
        self._routing = True
        try:
            if route == "library":
                self.services.instances_page.refresh()
            elif route == "settings":
                self.services._settings()
            elif route == "logs":
                self.services._show_logs()
            elif route == "studio":
                self.services._show_studio()
        finally:
            self._routing = False
        self._native_route = route
        self.services._current_page = route
        surface = self.services.page_map.get(route)
        if not isinstance(surface, QWidget):
            return
        while self.library_layout.count():
            previous = self.library_layout.takeAt(0).widget()
            if previous:
                previous.hide()
        # Qt accepts nullptr to remove an effect; PySide6 6.8 stub is non-nullable.
        surface.setGraphicsEffect(None)  # pyright: ignore[reportArgumentType]
        self.library_layout.addWidget(surface)
        surface.show()
        self._library_animate = not self._library_active
        self._library_active = True
        self.page.runJavaScript("window.NexusNativeLibrary?.enter(" + json.dumps(route) + ")")
        self.library_geometry_timer.start()
        self._position_library()
        self.services.hide()

    def closeEvent(self, event):
        super().closeEvent(event)
        if not event.isAccepted():
            return
        self.services.studio_page.shutdown_learning()
        self.state_timer.stop()
        self.projection_timer.stop()
        self.projection.close()
        self.native_presentation.close()
        self.services._navigate = self._original_navigate
