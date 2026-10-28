"""Production NEXUS 1.0 platform entry point."""
from __future__ import annotations

import ctypes
import os
import sys

import nexus_launcher.build_channel as build_channel

# Build trust is chosen by the frozen entry point, never inherited from a shell.
build_channel.STAGING_BUILD = False
os.environ.pop("NEXUS_ENVIRONMENT", None)
os.environ["NEXUS_PRIVATE_UI"] = "1"
os.environ.pop("NEXUS_DISABLE_SELF_UPDATE", None)

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from nexus_launcher.modern_main import CONFIG_FILE, WINDOWS_APP_ID, resource
from nexus_launcher.nexus_platform.config import migrate_private_config
from nexus_launcher.nexus_platform.window import PlatformLauncher
from nexus_launcher.projects import DEFAULT_PROJECTS


def main() -> int:
    ids = [server.id for project in DEFAULT_PROJECTS for server in project.servers]
    migrate_private_config(CONFIG_FILE, ids)
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NEXUS Launcher")
    app.setApplicationDisplayName("NEXUS Launcher")
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
