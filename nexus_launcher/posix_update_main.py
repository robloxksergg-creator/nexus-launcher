"""Managed POSIX launcher updates; persistent player data stays outside slots.

First launch remains usable offline. After UI readiness, a bounded background
job can authenticate the distributed bundle against its immutable release
manifest and copy it into a managed slot. It never spawns an updated child
while the original UI is open. Later launches use the shared health-gated flow.
"""
import hashlib
import os
from pathlib import Path
import threading

from nexus_launcher import public_update_identity as identity
from nexus_launcher.github_updates import GitHubPackageTransport
from nexus_launcher.portable_package import verify_staged_portable
from nexus_launcher.portable_transition import _read
from nexus_launcher.posix_bootstrap_process import PIPE_ENV, PosixChildSession, PosixLaunchLease, PosixProcessAdapter
from nexus_launcher.posix_package import FORMAT, inventory, stage_directory
from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.signed_release import canonical, verify_envelope
from nexus_launcher.startup_portable_backend import PortableStartupBackend
from nexus_launcher.update_state import update_lock
from nexus_launcher.user_instances import atomic_json


def feed(platform, arch, *, version=None):
    if (platform, arch) not in {('linux', 'x64'), ('macos', 'arm64')}:
        raise ValueError('Unsupported POSIX update platform')
    if version is not None:
        import re
        if not isinstance(version, str) or not re.fullmatch(r'\d{1,6}(?:\.\d{1,6}){2,3}', version):
            raise ValueError('Invalid initial release identity')
    tag = 'updates-preview' if version is None else 'v' + version + '-preview.1'
    return ('https://github.com/robloxksergg-creator/nexus-launcher/releases/download/'
            + tag + '/posix-envelope-' + platform + '-' + arch + '.json')


def provision_directory(root, source_parent, envelope, *, platform, arch, version, keys=None,
                        cancelled=lambda: False):
    root = Path(root).absolute()
    with pinned_directory(root, create=True), update_lock(root):
        if checked_path(root, 'active.json').exists():
            return False
        payload = verify_envelope(envelope, keys=keys)
        if (payload.get('available') is not True or payload.get('format') != FORMAT
                or payload.get('platform') != platform or payload.get('arch') != arch
                or payload.get('version') != version):
            raise ValueError('Initial POSIX release mismatch')
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        if checked_path(root, 'transition.json').exists():
            raise ValueError('Existing transition requires recovery')
        receipt = checked_path(root, 'initial-provision.json')
        if receipt.exists():
            previous = _read(root, 'initial-provision.json')
            if (previous.get('schema') != 1 or previous.get('phase') != 'PREPARED'
                    or previous.get('identity') != digest):
                raise ValueError('Initial POSIX provisioning requires recovery')
            name = previous.get('slot')
            if not isinstance(name, str) or '/' in name or not name.startswith('portable-stage-'):
                raise ValueError('Invalid initial slot')
            slot = checked_path(root, 'slots/' + name)
            verify_staged_portable(slot, keys=keys)
            if hashlib.sha256(canonical(_read(slot, 'envelope.json')['release'])).hexdigest() != digest:
                raise ValueError('Initial recovery identity mismatch')
        else:
            if checked_path(root, 'highest-package.json').exists():
                raise ValueError('Do not recreate lost installed history')
            slot = stage_directory(source_parent, envelope, checked_path(root, 'slots'),
                                   keys=keys, cancelled=cancelled)
            if cancelled():
                raise InterruptedError('Initial provisioning cancelled')
            atomic_json(receipt, {'schema': 1, 'phase': 'PREPARED', 'slot': slot.name, 'identity': digest})
        atomic_json(root / 'highest-package.json', envelope)
        atomic_json(root / 'active.json', {'slot': slot.name})
        atomic_json(receipt, {'schema': 1, 'phase': 'COMPLETE', 'slot': slot.name, 'identity': digest})
        return True


def main(data_root, *, platform, arch, executable):
    from nexus_launcher.preview_prototype import main as run_ui
    if PIPE_ENV in os.environ:
        session = PosixChildSession.receive()
        try:
            return run_ui(readiness_callback=session.ready)
        finally:
            session.close()
    root = checked_path(Path(data_root), '.launcher-updates')
    with PosixLaunchLease(root) as lease:
        existing = any(checked_path(root, name).exists() for name in
                       ('active.json', 'highest-package.json', 'initial-provision.json', 'transition.json'))
        if existing:
            return managed_window(root, lease, platform=platform, arch=arch)
        # Current code was explicitly launched by the desktop user. It remains
        # usable without trusting a network response or declaring an update PASS.
        stopped = threading.Event()
        workers = []

        def prepare():
            try:
                initial = GitHubPackageTransport(feed(platform, arch, version=identity.VERSION)).manifest()
                inv = inventory(verify_envelope(initial))
                source_parent = Path(executable).absolute()
                for _ in Path(inv.entrypoint).parts:
                    source_parent = source_parent.parent
                provision_directory(root, source_parent, initial, platform=platform, arch=arch,
                                    version=identity.VERSION, cancelled=stopped.is_set)
                atomic_json(root / 'bootstrap-status.json', {'schema': 1, 'state': 'PREPARED'})
            except Exception:
                atomic_json(root / 'bootstrap-status.json', {'schema': 1, 'state': 'NOT_PREPARED'})

        def ready():
            if workers:
                return
            worker = threading.Thread(target=prepare, name='nexus-update-initialization')
            workers.append(worker)
            worker.start()
        try:
            return run_ui(readiness_callback=ready)
        finally:
            stopped.set()
            for worker in workers:
                worker.join()


def managed_window(root, lease, *, platform, arch):
    import sys
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.startup_update_window import StartupUpdateWindow
    class Backend(PortableStartupBackend):
        def check(self):
            if not checked_path(root, 'active.json').exists() and checked_path(root, 'initial-provision.json').exists():
                initial = GitHubPackageTransport(feed(platform, arch, version=identity.VERSION)).manifest()
                # PREPARED recovery uses the exact already staged signed slot;
                # source_parent is deliberately unused in that recovery branch.
                provision_directory(root, root, initial, platform=platform, arch=arch, version=identity.VERSION)
            return super().check()
    backend = Backend(root, transport=GitHubPackageTransport(feed(platform, arch)),
                      adapter=PosixProcessAdapter(lease), platform=platform, arch=arch)
    app = QApplication([])
    app.setApplicationName('NEXUS Launcher')
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    app.setWindowIcon(QIcon(str(resources / 'assets/icon.png')))
    window = StartupUpdateWindow(backend)
    window.show()
    QTimer.singleShot(0, window, window.start)
    return app.exec()
