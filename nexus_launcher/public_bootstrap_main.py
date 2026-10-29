"""New public managed installation; never adopts the legacy portable data."""
import os
from pathlib import Path
import sys


def main():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Packaged Windows bootstrap required')
    import nexus_launcher.build_channel as channel
    channel.PUBLIC_PREVIEW_BUILD = True
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from nexus_launcher import public_update_identity as identity
    from nexus_launcher.github_updates import GitHubPackageTransport
    from nexus_launcher.windows_bootstrap_process import WindowsLaunchLease, WindowsProcessAdapter
    from nexus_launcher.startup_portable_backend import PortableStartupBackend
    from nexus_launcher.startup_update_window import StartupUpdateWindow
    from nexus_launcher.bootstrap_installation import provision_initial
    from nexus_launcher.resource_limits import read_limited
    from nexus_launcher.safe_paths import checked_path, pinned_directory
    import json

    resources = Path(sys._MEIPASS)
    # A new directory and trust chain; no automatic copying/deleting old saves.
    root = Path(os.environ['LOCALAPPDATA']) / 'NEXUS Launcher' / 'managed-preview'
    app = QApplication(sys.argv)
    app.setApplicationName('NEXUS Launcher')
    app.setWindowIcon(QIcon(str(resources / 'assets' / 'icon.ico')))

    class Backend(PortableStartupBackend):
        def check(self):
            if not checked_path(root, 'active.json').exists():
                with (resources / 'initial-envelope.json').open('rb') as stream:
                    envelope = json.loads(read_limited(stream))
                provision_initial(root, resources / 'initial-package.zip', envelope,
                                  platform='windows', arch='x64')
            return super().check()

    with pinned_directory(root, create=True), WindowsLaunchLease(root) as lease:
        backend = Backend(root, transport=GitHubPackageTransport(identity.FEED),
                          adapter=WindowsProcessAdapter(lease), platform='windows', arch='x64')
        window = StartupUpdateWindow(backend)
        window.show()
        QTimer.singleShot(0, window, window.start)
        return app.exec()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout
        from nexus_launcher.themed_dialog import NexusDialog
        from nexus_launcher.nexus_platform.presentation_style import stylesheet
        app = QApplication.instance() or QApplication([])
        dialog = NexusDialog()
        dialog.setWindowTitle('NEXUS — запуск недоступен')
        dialog.setStyleSheet(stylesheet())
        layout = QVBoxLayout(dialog)
        label = QLabel('Не удалось подтвердить запуск. Если NEXUS уже работает, используйте открытое окно. Иначе проверьте целостность полной папки стартовой сборки.')
        label.setWordWrap(True)
        layout.addWidget(label)
        close = QPushButton('Закрыть')
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        sys.exit(1)
