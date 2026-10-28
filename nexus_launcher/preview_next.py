"""Disposable preview. No account restore; user-invoked Modrinth access is live."""
import os
import tempfile
import sys

if __name__ == "__main__":
    sandbox = tempfile.TemporaryDirectory(prefix="nexus-next-preview-")
    os.environ["APPDATA"] = sandbox.name
    os.environ["NEXUS_PRIVATE_UI"] = "1"
    os.environ["NEXUS_DISABLE_SELF_UPDATE"] = "1"
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.modern_main import Launcher
    from nexus_launcher.nexus_platform.next_shell import NexusLauncher
    from nexus_launcher.nexus_platform.config import migrate_private_config
    from nexus_launcher.modern_main import CONFIG_FILE
    from nexus_launcher.projects import DEFAULT_PROJECTS

    # Prevent background account/server calls and keyring restore. Modrinth is opt-in.
    for method in ("_check_servers", "_restore_account_worker", "_refresh_build_access_worker"):
        setattr(Launcher, method, lambda self: None)
    NexusLauncher._refresh_remote_content = lambda self: None
    migrate_private_config(CONFIG_FILE, [server.id for project in DEFAULT_PROJECTS for server in project.servers if server.id == "main"])
    app = QApplication([])
    window = NexusLauncher()
    window.setWindowTitle("NEXUS Next — Design Test")
    window.profile.setToolTip("Вход и регистрация — настоящие аккаунты сайта NEXUS. Автоматический вход отключён.")
    window.showMaximized()
    if "--self-test-report" in sys.argv:
        from nexus_launcher.frozen_smoke import check
        check(app, window, sys.argv[sys.argv.index("--self-test-report") + 1])
    else:
        app.exec()
    # Sandbox may contain draft packs, not installed user saves.
    sandbox.cleanup()
