"""Isolated exact-design preview with explicit access to existing services."""
import json
import os
import sys
import tempfile
from pathlib import Path
from contextlib import nullcontext


def main(*, readiness_callback=None):
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    storage = os.environ.get("NEXUS_PORTABLE_DATA")
    session = nullcontext(storage) if storage else tempfile.TemporaryDirectory(prefix="nexus-prototype-")
    with session as sandbox:
        os.environ["APPDATA"] = sandbox
        os.environ["NEXUS_PRIVATE_UI"] = "1"
        os.environ["NEXUS_DISABLE_SELF_UPDATE"] = "1"
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
        from nexus_launcher.modern_main import Launcher, WINDOWS_APP_ID, resource
        from nexus_launcher.nexus_platform.next_shell import NexusLauncher
        from nexus_launcher.nexus_platform.prototype_host import PrototypeHost
        if os.environ.get("NEXUS_UI_2") != "1" or "--self-test-report" in sys.argv:
            for method in ("_check_servers", "_restore_account_worker", "_refresh_build_access_worker"):
                setattr(Launcher, method, lambda self: None)
            NexusLauncher._refresh_remote_content = lambda self: None
        # This entrypoint bypasses modern_main.main(), so establish the same
        # native identity before creating any windows (including the WebEngine host).
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
        app = QApplication([])
        app.setApplicationName('NEXUS Launcher')
        app.setApplicationDisplayName('NEXUS Launcher')
        app.setDesktopFileName(WINDOWS_APP_ID)
        app.setWindowIcon(QIcon(str(resource('icon.ico' if sys.platform == 'win32' else 'icon.png'))))
        services = NexusLauncher()
        if os.environ.get("NEXUS_UI_2") == "1":
            from nexus_launcher.nexus_platform.design_bridge import DesignHost
            window = DesignHost(services)
        else:
            window = PrototypeHost(services)
        window.showMaximized()
        if readiness_callback is not None:
            from nexus_launcher.public_readiness import PublicReadinessProbe
            window.bootstrap_readiness = PublicReadinessProbe(window, services, readiness_callback)
        if "--self-test-report" in sys.argv:
            window.showNormal()
            window.resize(1366, 900)
            output = Path(sys.argv[sys.argv.index("--self-test-report") + 1])

            if "--academy-smoke" in sys.argv:
                from nexus_launcher.frozen_learning_smoke import start_learning
                invoked = [False]
                def academy_loaded(ok):
                    if ok and not invoked[0]:
                        invoked[0] = True
                        QTimer.singleShot(200, lambda: start_learning(window, output, app))
                window.view.loadFinished.connect(academy_loaded)
                QTimer.singleShot(30000, app.quit)
                app.exec()
                return
            def loaded(ok):
                def capture():
                    def received(value):
                        from nexus_launcher.release_metadata import CURRENT_VERSION
                        report = {"release_version": CURRENT_VERSION, "loaded": ok, "dom": value, "profile_off_record": window.profile.isOffTheRecord(), "script_errors": window.page.script_errors,
                                  "application_icon": not app.windowIcon().isNull(), "window_icon": not window.windowIcon().isNull(),
                                  "desktop_file_name": app.desktopFileName()}
                        if "--content-smoke" in sys.argv:
                            from nexus_launcher.frozen_content_smoke import check_content
                            report["content"] = check_content(window)
                        if "--filter-smoke" in sys.argv:
                            from nexus_launcher.frozen_filter_smoke import check_filters
                            report["filters"] = check_filters(window, output)
                        output.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
                        window.grab().save(str(output.with_suffix(".png")))
                        window.close()
                        app.quit()
                    window.page.runJavaScript("JSON.stringify({title:document.title,buttons:document.querySelectorAll('button').length,studio:!!document.querySelector('.studio'),image:!!Array.from(document.images).find(i=>i.naturalWidth>0)})", received)
                QTimer.singleShot(1000, capture)
            window.view.loadFinished.connect(loaded)
            QTimer.singleShot(30000, app.quit)
        app.exec()


if __name__ == "__main__":
    main()
