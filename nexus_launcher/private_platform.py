"""Local-only NEXUS Global Update entry point."""
from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from nexus_launcher.modern_main import CONFIG_FILE, WINDOWS_APP_ID, resource
from nexus_launcher.projects import DEFAULT_PROJECTS

from nexus_launcher.nexus_platform.config import migrate_private_config
from nexus_launcher.nexus_platform.window import PlatformLauncher


def main() -> int:
    os.environ["NEXUS_PRIVATE_UI"] = "1"
    os.environ["NEXUS_DISABLE_SELF_UPDATE"] = "1"
    ids = [server.id for project in DEFAULT_PROJECTS for server in project.servers]
    migrate_private_config(CONFIG_FILE, ids)
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID + ".private-global-update")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NEXUS Launcher Private")
    app.setApplicationDisplayName("NEXUS Launcher · Private Global Update")
    app.setWindowIcon(QIcon(str(resource("icon.png"))))
    window = PlatformLauncher()
    if "--smoke-test" in sys.argv:
        window.show()
        app.processEvents()
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
