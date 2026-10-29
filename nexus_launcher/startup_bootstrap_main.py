"""Stable Windows tester bootstrap. No CLI endpoint/key/path overrides."""
import json
import os
from pathlib import Path
import sys


def main():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Use the packaged Windows bootstrap')
    import nexus_launcher.build_channel as build_channel
    build_channel.STAGING_BUILD = True
    build_channel.TESTER_BUILD = True
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.windows_bootstrap_process import WindowsLaunchLease, WindowsProcessAdapter
    from nexus_launcher.startup_update_window import StartupUpdateWindow
    from nexus_launcher.startup_portable_backend import PackageTransport, PortableStartupBackend
    from nexus_launcher.bootstrap_installation import provision_initial
    from nexus_launcher.update_state import update_lock
    from nexus_launcher.resource_limits import read_limited
    from nexus_launcher.safe_paths import checked_path, pinned_directory

    resources = Path(sys._MEIPASS) / 'assets'
    with (resources / 'bootstrap-release.json').open('rb') as stream:
        config = json.loads(read_limited(stream, 8192))
    hosts = {'nexusmc-control-plane-staging.robloxksergg.workers.dev'}
    if (not isinstance(config, dict) or set(config) != {'schema', 'channel', 'feed'}
            or config['schema'] != 1 or config['channel'] != 'beta'
            or (config['feed'] is not None and not isinstance(config['feed'], str))):
        raise ValueError('Invalid packaged bootstrap policy')
    root = Path(os.environ['LOCALAPPDATA']) / 'NEXUS Tester' / 'managed-beta'
    app = QApplication(sys.argv)
    app.setApplicationName('NEXUS')

    class Backend(PortableStartupBackend):
        def check(self):
            if not checked_path(root, 'active.json').exists():
                with (resources / 'initial-envelope.json').open('rb') as stream:
                    envelope = json.loads(read_limited(stream))
                provision_initial(root, resources / 'initial-package.zip', envelope,
                                  platform='windows', arch='x64')
            if config['feed'] is None:
                # Explicit local-only release policy, never an unsigned network
                # "no update" response. Feed is enabled only in an approved build.
                with update_lock(root):
                    self._current()
                return None
            return super().check()

    with pinned_directory(root, create=True):
        try:
            lease = WindowsLaunchLease(root)
        except RuntimeError:
            # A second starter cannot launch, download or alter an active child.
            from nexus_launcher.themed_dialog import NexusDialog
            from PySide6.QtWidgets import QVBoxLayout, QLabel, QPushButton
            from nexus_launcher.nexus_platform.presentation_style import stylesheet
            dialog = NexusDialog()
            dialog.setWindowTitle('NEXUS')
            dialog.setStyleSheet(stylesheet())
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel('NEXUS уже запускается или работает.'))
            close = QPushButton('Закрыть')
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec()
            return 0
        with lease:
            if config['feed'] and config['feed'].startswith('https://github.com/'):
                from nexus_launcher.github_updates import GitHubPackageTransport
                transport = GitHubPackageTransport(config['feed'])
            else:
                transport = PackageTransport(config['feed'], allowed_hosts=hosts) if config['feed'] else None
            backend = Backend(root, transport=transport, adapter=WindowsProcessAdapter(lease),
                              platform='windows', arch='x64')
            window = StartupUpdateWindow(backend)
            window.show()
            QTimer.singleShot(0, window, window.start)
            return app.exec()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        # Do not expose exceptions or silently loop after policy/storage failure.
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout
        from nexus_launcher.themed_dialog import NexusDialog
        from nexus_launcher.nexus_platform.presentation_style import stylesheet
        from nexus_launcher.nexus_platform.theme_tokens import TOKENS
        application = QApplication.instance() or QApplication([])
        dialog = NexusDialog()
        dialog.setWindowTitle('NEXUS — ошибка запуска')
        dialog.setMinimumWidth(440)
        dialog.setStyleSheet(stylesheet() + f"QDialog {{ background:{TOKENS['background']}; }}")
        layout = QVBoxLayout(dialog)
        label = QLabel('Не удалось запустить окно обновления. Проверьте целостность распакованной папки NEXUS.')
        label.setWordWrap(True)
        layout.addWidget(label)
        close = QPushButton('Закрыть')
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        sys.exit(1)
