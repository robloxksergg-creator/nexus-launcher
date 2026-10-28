"""Exact prototype renderer; no Python objects or filesystem APIs exposed to JS."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit
import base64
import json

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal, QPropertyAnimation
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QStackedWidget, QPushButton, QGraphicsOpacityEffect
from PySide6.QtGui import QImage, QIcon

from nexus_launcher.modern_main import resource
from nexus_launcher.nexus_platform.window_chrome import TitleBar, create_resize_edges, position_resize_edges
from nexus_launcher.nexus_platform.ui_preferences import UIPreferences


COMMANDS = frozenset({"login", "register", "services", "packs", "mods", "sound-on", "sound-off", "library-leave"})


class AssetServer:
    """Loopback GET-only resource whitelist, never a directory/file server."""
    def __init__(self, redesigned=False, creator=False):
        self.preferences = UIPreferences()
        if creator:
            from .theme_tokens import browser_tokens
            html = resource("approved-ui/index.html").read_bytes()
            css = browser_tokens().encode() + resource("academy/learning.css").read_bytes() + resource("studio/workspace.css").read_bytes()
            adapter = resource("academy/editor-adapter.js").read_bytes() + resource("studio/workspace.js").read_bytes()
            html = html.replace(b"<style>", b"<style>.app{visibility:hidden!important}</style><style>", 1)
            self.assets = {"/": (html + b"<style>" + css + b"</style><script>" + adapter + b"</script>", "text/html; charset=utf-8")}
            self.assets["/gearmorph-official.png"] = (resource("gearmorph-official.png").read_bytes(), "image/png")
            self._start_server()
            return
        if redesigned:
            from .theme_tokens import browser_tokens
            html = resource("ui2/index.html").read_bytes()
            import os
            if os.environ.get("NEXUS_TESTER_VERSION"):
                from nexus_launcher.release_metadata import CURRENT_VERSION
                html = html.replace(b"NEXUS 2.0", ("NEXUS " + CURRENT_VERSION + " / TEST").encode())
            css = browser_tokens().encode() + resource("ui2/launcher.css").read_bytes()
            css += resource("ui2/refinements.css").read_bytes()
            adapter = resource("ui2/launcher.js").read_bytes()
            adapter += b"\n" + resource("approved-ui/skin-preview.js").read_bytes()
            css += b"\n" + resource("approved-ui/skin-preview.css").read_bytes()
            adapter += b"\n" + resource("approved-ui/smooth-scroll.js").read_bytes()
            self.assets = {
                "/": (html, "text/html; charset=utf-8"),
                "/launcher.css": (css, "text/css; charset=utf-8"),
                "/launcher.js": (adapter, "text/javascript; charset=utf-8"),
                "/components.js": (resource("ui2/components.js").read_bytes(), "text/javascript; charset=utf-8"),
                "/screens.js": (resource("ui2/screens.js").read_bytes(), "text/javascript; charset=utf-8"),
            }
            for name in ("gearmorph-official.png", "minecraft-meadow.png",
                         "minecraft-desert.png", "minecraft-city.png", "minecraft-mountain.png"):
                self.assets["/" + name] = (resource(name).read_bytes(), "image/png")
            self._start_server()
            return
        html = resource("approved-ui/index.html").read_bytes()
        adapter = resource("approved-ui/desktop-adapter.js").read_bytes()
        adapter += b"\n" + resource("approved-ui/server-layout.js").read_bytes()
        adapter += b"\n" + resource("approved-ui/discover-page.js").read_bytes()
        adapter += b"\n" + resource("approved-ui/ui-polish.js").read_bytes()
        adapter += b"\n" + resource("approved-ui/banner-media.js").read_bytes()
        adapter += b"\n" + resource("approved-ui/skin-preview.js").read_bytes()
        adapter += b"\n" + resource("approved-ui/live-services.js").read_bytes()
        adapter += b"\n" + resource("approved-ui/smooth-scroll.js").read_bytes()
        initial_sound = b"true" if self.preferences.sound_enabled() else b"false"
        adapter = b"window.NexusInitialSound=" + initial_sound + b";\n" + adapter
        css = resource("approved-ui/desktop-adapter.css").read_bytes()
        css += b"\n" + resource("approved-ui/server-layout.css").read_bytes()
        css += b"\n" + resource("approved-ui/discover-page.css").read_bytes()
        css += b"\n" + resource("approved-ui/ui-polish.css").read_bytes()
        css += b"\n" + resource("approved-ui/skin-preview.css").read_bytes()
        self.assets = {
            "/": (html + b"\n<style>" + css + b"</style><script>" + adapter + b"</script>", "text/html; charset=utf-8"),
            "/gearmorph-official.png": (resource("gearmorph-official.png").read_bytes(), "image/png"),
        }
        for name in ("minecraft-meadow.png", "minecraft-desert.png", "minecraft-city.png", "minecraft-mountain.png"):
            self.assets["/" + name] = (resource(name).read_bytes(), "image/png")
        self._start_server()

    def _start_server(self):
        assets = self.assets

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlsplit(self.path).path
                entry = assets.get(path)
                if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or entry is None:
                    self.send_error(404)
                    return
                body, content_type = entry
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def same_origin(url, origin):
    try:
        value = urlsplit(url)
        trusted = urlsplit(origin)
        return (value.scheme, value.hostname, value.port) == (trusted.scheme, trusted.hostname, trusted.port)
    except ValueError:
        return False


class ResourcePolicy(QWebEngineUrlRequestInterceptor):
    def __init__(self, origin, parent):
        super().__init__(parent)
        self.origin = origin

    def interceptRequest(self, info):
        url = info.requestUrl()
        # Offline source, user-picked blobs and inline data only. No remote scripts.
        if url.scheme() not in {"data", "blob"} and not same_origin(url.toString(), self.origin):
            info.block(True)


class PrototypePage(QWebEnginePage):
    command = Signal(str)

    def __init__(self, profile, origin, parent):
        super().__init__(profile, parent)
        self.origin = origin
        self.script_errors = []

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        if level == QWebEnginePage.ErrorMessageLevel:
            self.script_errors.append({"message": message, "line": line_number})

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if url.path().startswith("/desktop-command/"):
            command = url.path().removeprefix("/desktop-command/")
            if (is_main_frame and same_origin(url.toString(), self.origin)
                    and same_origin(self.url().toString(), self.origin)
                    and command in COMMANDS and not url.query() and not url.fragment()):
                self.command.emit(command)
            return False
        return is_main_frame and same_origin(url.toString(), self.origin)

    def createWindow(self, _kind):
        return None


class PrototypeHost(QMainWindow):
    def __init__(self, services, redesigned=False):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint | Qt.WindowSystemMenuHint)
        self.setMinimumSize(640, 480)
        self.services = services
        from .smooth_scroll import SmoothScroll
        self.smooth_scroll = SmoothScroll(self)
        # Embedded service pages leave their original window and its inherited
        # stylesheet. Keep the canonical native theme on their new owner.
        from .presentation_style import stylesheet
        self.setStyleSheet(stylesheet())
        self.server = AssetServer(redesigned)
        self.setWindowTitle("NEXUS — прототип в EXE · перенос функций")
        self.setWindowIcon(QIcon(str(resource('icon.ico'))))
        self.resize(1366, 768)
        self.profile = QWebEngineProfile(self)
        self.policy = ResourcePolicy(self.server.origin, self.profile)
        self.profile.setUrlRequestInterceptor(self.policy)
        self.profile.downloadRequested.connect(lambda item: item.cancel())
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        if redesigned:
            from .design_bridge import DesignPage
            self.page = DesignPage(self.profile, self.server.origin, self.view)
        else:
            self.page = PrototypePage(self.profile, self.server.origin, self.view)
        self.view.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, True)
        self.page.settings().setAttribute(QWebEngineSettings.ShowScrollBars, False)
        for flag in (QWebEngineSettings.LocalContentCanAccessFileUrls,
                     QWebEngineSettings.LocalContentCanAccessRemoteUrls,
                     QWebEngineSettings.JavascriptCanOpenWindows,
                     QWebEngineSettings.JavascriptCanAccessClipboard):
            self.page.settings().setAttribute(flag, False)
        self.page.command.connect(lambda name: QTimer.singleShot(0, lambda: self._command(name)))
        self.page.settings().setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        self.page.fullScreenRequested.connect(self._fullscreen)
        wrapper = QWidget(self)
        wrapper.setObjectName("platformRoot")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        layout.addWidget(self.title_bar)
        self.back_to_design = QPushButton('← Вернуться в NEXUS')
        self.back_to_design.clicked.connect(self._return_design)
        self.back_to_design.hide()
        layout.addWidget(self.back_to_design)
        self.surfaces = QStackedWidget()
        self.surfaces.setObjectName("platformPages")
        self.surfaces.addWidget(self.view)
        self.library_overlay = QWidget(self.surfaces)
        self.library_overlay.setObjectName("platformRoot")
        self.library_overlay.setAttribute(Qt.WA_StyledBackground, True)
        self.library_layout = QVBoxLayout(self.library_overlay)
        self.library_layout.setContentsMargins(0, 0, 0, 0)
        self.library_overlay.hide()
        self._library_active = False
        self._library_geometry_pending = False
        self._library_animate = False
        self.library_geometry_timer = QTimer(self)
        self.library_geometry_timer.setInterval(50)
        self.library_geometry_timer.timeout.connect(self._position_library)
        layout.addWidget(self.surfaces, 1)
        self.setCentralWidget(wrapper)
        self.resize_edges = create_resize_edges(self)
        self._skin_key = object()
        self.skin_timer = QTimer(self)
        self.skin_timer.timeout.connect(self._sync_skin)
        self.skin_timer.start(500)
        self.view.loadFinished.connect(lambda ok: self._sync_skin(force=True) if ok else None)
        self.view.load(QUrl(self.server.origin + "/"))

    def _sync_skin(self, force=False):
        profile = getattr(self.services, "account_profile", None)
        if not force and profile is self._skin_key:
            return
        self._skin_key = profile
        png = getattr(profile, "skin_png", None)
        encoded = None
        if isinstance(png, bytes) and len(png) <= 1024 * 1024 and png.startswith(b"\x89PNG\r\n\x1a\n"):
            image = QImage.fromData(png)
            if image.width() == 64 and image.height() in (32, 64):
                encoded = base64.b64encode(png).decode("ascii")
        # Only a validated texture and model cross the boundary, never tokens/PII.
        value = {"png": encoded, "model": "slim" if getattr(profile, "skin_model", None) == "slim" else "classic"}
        self.page.runJavaScript("window.NexusSkin?.setProfile(" + json.dumps(value) + ")")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "resize_edges"):
            position_resize_edges(self)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "resize_edges"):
            self.title_bar.sync()
            position_resize_edges(self)

    def _command(self, name):
        if name == "library-leave":
            self._hide_library()
        elif name in {"packs", "mods"} and isinstance(self.services.instances_page, QWidget):
            surface = self.services.instances_page
            surface.refresh()
            surface.setGraphicsEffect(None)
            if name == "mods":
                surface.open_mod_catalog()
            if surface.parentWidget() is not self.library_overlay:
                self.library_layout.addWidget(surface)
            surface.show()
            self.surfaces.setCurrentWidget(self.view)
            self.back_to_design.hide()
            self._library_animate = not self._library_active
            self._library_active = True
            self.page.runJavaScript("window.NexusNativeLibrary?.enter()")
            self.library_geometry_timer.start()
            self._position_library()
            self.services.hide()
        elif name in {"sound-on", "sound-off"}:
            try:
                self.server.preferences.save_sound(name == "sound-on")
            except OSError:
                self.page.runJavaScript("info('Не удалось сохранить настройку звука. Она изменена только на этот запуск.')")
        elif name == "login":
            self.services._login_account()
        elif name == "register":
            self.services._register_account()
        elif name in {"packs", "mods"}:
            self._hide_library()
            # The host owns navigation now. The legacy shell's fade effect and
            # stacked-page navigation must not run on a reparented workspace.
            surface = self.services.instances_page
            if isinstance(surface, QWidget):
                surface.refresh()
                surface.setGraphicsEffect(None)
            else:
                self.services.show_instances()
            if name == "mods":
                surface.open_mod_catalog()
            if isinstance(surface, QWidget):
                if self.surfaces.indexOf(surface) < 0:
                    self.surfaces.addWidget(surface)
                self.surfaces.setCurrentWidget(surface)
                self.back_to_design.show()
                self.services.hide()
                return
            self.services.showMaximized()
            self.services.raise_()

        elif name == "services":
            self.services.showMaximized()
            self.services.raise_()

    def _return_design(self):
        self._hide_library()
        self.surfaces.setCurrentWidget(self.view)
        self.back_to_design.hide()

    def _hide_library(self):
        self._library_active = False
        self.library_geometry_timer.stop()
        if hasattr(self, "_library_animation"):
            self._library_animation.stop()
        self.library_overlay.setGraphicsEffect(None)
        self.library_overlay.hide()
        self.page.runJavaScript("window.NexusNativeLibrary?.leave()")

    def _position_library(self):
        if not self._library_active or self._library_geometry_pending:
            return
        self._library_geometry_pending = True

        def apply(value):
            self._library_geometry_pending = False
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    return
            if not self._library_active or not isinstance(value, dict):
                return
            self._web_reduced_motion = bool(value.get('reducedMotion'))
            self.page.settings().setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, not self._web_reduced_motion)
            try:
                x, y, width, height = (round(float(value[key])) for key in ("x", "y", "width", "height"))
            except (KeyError, TypeError, ValueError, OverflowError):
                return
            x = max(0, min(x, self.view.width()))
            y = max(0, min(y, self.view.height()))
            width = max(0, min(width, self.view.width() - x))
            height = max(0, min(height, self.view.height() - y))
            geometry = self.library_overlay.geometry()
            if (geometry.x(), geometry.y(), geometry.width(), geometry.height()) != (x, y, width, height):
                self.library_overlay.setGeometry(x, y, width, height)
            # Repeated show/raise steals focus from native combo popups on
            # Windows. Raise only when entering the native workspace.
            if not self.library_overlay.isVisible():
                self.library_overlay.show()
                self.library_overlay.raise_()
            if self._library_animate:
                self._library_animate = False
                if not value.get("reducedMotion") and not self.services.config.get("reducedMotion", False):
                    effect = QGraphicsOpacityEffect(self.library_overlay)
                    self.library_overlay.setGraphicsEffect(effect)
                    self._library_animation = QPropertyAnimation(effect, b"opacity", self)
                    self._library_animation.setDuration(180)
                    self._library_animation.setStartValue(0.0)
                    self._library_animation.setEndValue(1.0)
                    self._library_animation.finished.connect(lambda: self.library_overlay.setGraphicsEffect(None))
                    self._library_animation.start()

        self.page.runJavaScript(
            "(()=>{const library=window.NexusNativeLibrary;"
            "if(!library)return null;return JSON.stringify(library.geometry())})()", apply)

    def _fullscreen(self, request):
        if not same_origin(request.origin().toString(), self.server.origin):
            request.reject()
            return
        request.accept()
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showMaximized()

    def closeEvent(self, event):
        if not self.services.close():
            event.ignore()
            return
        self.library_geometry_timer.stop()
        self.skin_timer.stop()
        self.view.stop()
        self.smooth_scroll.stop()
        self.server.close()
        super().closeEvent(event)
