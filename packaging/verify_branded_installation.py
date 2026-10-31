"""Offline full signed-package provisioning and completion presentation on CI.

Does not launch the installed bootstrap or contact an account/game server.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


def verify(archive, envelope, installer, root, report, screenshot):
    if os.name != 'nt':
        raise OSError('Windows required')
    import nexus_launcher.build_channel as channel
    channel.PUBLIC_PREVIEW_BUILD = True
    from nexus_launcher.github_updates import GitHubPackageTransport
    from nexus_launcher.online_installation import install, installation_details
    from nexus_launcher.windows_bootstrap_process import WindowsLaunchLease
    root = Path(root).absolute()
    if root.exists():
        raise ValueError('Owned acceptance directory must be new')
    signed = json.loads(Path(envelope).read_text(encoding='utf-8'))
    transport = GitHubPackageTransport('https://github.com/robloxksergg-creator/nexus-launcher/releases/download/updates-preview/portable-envelope.json')
    def local_open(url):
        if url == transport.manifest_url:
            return Path(envelope).open('rb')
        if url == signed['release']['url']:
            return Path(archive).open('rb')
        raise ValueError('Unexpected offline input URL')
    transport._open = local_open
    phases = []
    with WindowsLaunchLease(root):
        target = install(root, installer, transport, lambda phase, *_: phases.append(phase))
        details = installation_details(target)
        assert details.version == '1.0.3'
        assert details.file_count == len(signed['release']['files'])
        assert phases[-1] == 'COMPLETE'
        assert hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() == hashlib.file_digest(Path(installer).open('rb'), 'sha256').hexdigest()
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.installer_completion import CompletionWindow
    app = QApplication.instance() or QApplication([])
    window = CompletionWindow(details)
    window.show()
    app.processEvents()
    assert not window.launch.visibleRegion().isEmpty()
    assert not window.licenses_button.visibleRegion().isEmpty()
    assert window.grab().save(str(screenshot))
    result = {'version': details.version, 'files_verified': details.file_count,
              'bytes_verified': details.total_bytes, 'completion_visible': True,
              'installer_copy_verified': True, 'launch_executed': False,
              'shortcut_created': False, 'scope': 'Full owner-signed package; local transport only; no account/game/C2'}
    Path(report).write_text(json.dumps(result, indent=2), encoding='utf-8')
    window.close()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'envelope', 'installer', 'root', 'report', 'screenshot'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(**vars(args))))
