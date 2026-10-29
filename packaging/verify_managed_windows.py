"""Offline real-Windows two-version acceptance; only caller-owned test installs.

Requires owner-signed packages. No key loading, server access or fake readiness.
The existing frozen smoke mode suppresses account/content background work.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


def verify(initial_zip, initial_envelope, update_zip, update_envelope, root, report):
    if os.name != 'nt':
        raise OSError('Windows acceptance required')
    import nexus_launcher.build_channel as channel
    channel.PUBLIC_PREVIEW_BUILD = True
    from nexus_launcher.bootstrap_installation import provision_initial
    from nexus_launcher.github_updates import GitHubPackageTransport
    from nexus_launcher.startup_portable_backend import PortableStartupBackend
    from nexus_launcher.windows_bootstrap_process import WindowsLaunchLease, WindowsProcessAdapter
    root = Path(root).absolute()
    if root.exists():
        raise ValueError('Acceptance root must be new')
    root.mkdir(parents=True)
    initial = json.loads(Path(initial_envelope).read_text(encoding='utf-8'))
    update = json.loads(Path(update_envelope).read_text(encoding='utf-8'))
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['NEXUS_DISABLE_SELF_UPDATE'] = '1'

    class Adapter(WindowsProcessAdapter):
        def __init__(self, lease):
            super().__init__(lease)
            self.children = []
            self.report = None

        def _argv(self, executable):
            return [str(executable), '--self-test-report', str(self.report)]

        def launch(self, *args):
            child = super().launch(*args)
            self.children.append(child)
            return child

    transport = GitHubPackageTransport('https://github.com/robloxksergg-creator/nexus-launcher/releases/download/updates-preview/portable-envelope.json')
    # Replace network I/O only in this acceptance harness; production transport
    # still validates the signed GitHub URL and archive size/hash before staging.
    def local_open(url):
        if url == transport.manifest_url:
            return Path(update_envelope).open('rb')
        if url == update['release']['url']:
            return Path(update_zip).open('rb')
        raise ValueError('Unexpected acceptance URL')
    transport._open = local_open
    output = []
    with WindowsLaunchLease(root) as lease:
        adapter = Adapter(lease)
        try:
            backend = PortableStartupBackend(root, transport=transport, adapter=adapter,
                                             platform='windows', arch='x64')
            provision_initial(root, initial_zip, initial, platform='windows', arch='x64')
            (root / 'data').mkdir(exist_ok=True)
            sentinel = root / 'data/acceptance-sentinel.txt'
            sentinel.write_text('synthetic user data; preserve across update', encoding='utf-8')
            sentinel_hash = hashlib.sha256(sentinel.read_bytes()).hexdigest()
            previous = (root / 'active.json').read_bytes()
            for index, envelope in enumerate((initial, update)):
                adapter.report = root / f'acceptance-{index}.json'
                if index == 0:
                    if backend.launch_current() is not True:
                        raise ValueError('Initial native readiness not established')
                else:
                    release = backend.check()
                    if release is None:
                        raise ValueError('Expected newer signed release')
                    archive = backend.download(release, lambda *_: None)
                    candidate = backend.stage(archive, release)
                    if backend.activate(candidate) != 'COMPLETE':
                        raise ValueError('Native update did not commit')
                if adapter.children[-1].wait(timeout=90) != 0:
                    raise ValueError('Native UI smoke failed')
                smoke = json.loads(adapter.report.read_text(encoding='utf-8'))
                if (smoke.get('release_version') != envelope['release']['version']
                        or not smoke.get('loaded') or smoke.get('script_errors')
                        or not smoke.get('application_icon') or not smoke.get('window_icon')):
                    raise ValueError('Native smoke identity/readiness mismatch')
                output.append({'version': smoke['release_version'], 'native_readiness': 'PASS'})
            if previous == (root / 'active.json').read_bytes():
                raise ValueError('Active slot did not change')
            if hashlib.sha256(sentinel.read_bytes()).hexdigest() != sentinel_hash:
                raise ValueError('User data changed')
            result = {'versions': output, 'user_data_preserved': True,
                      'scope': 'Real Windows processes; local signed fixtures, no live network feed'}
            Path(report).write_text(json.dumps(result, indent=2), encoding='utf-8')
            return result
        finally:
            for child in adapter.children:
                if child.poll() is None and not adapter.stop_and_wait(child):
                    raise RuntimeError('Owned acceptance process could not be reaped')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('initial-zip', 'initial-envelope', 'update-zip', 'update-envelope', 'root', 'report'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.initial_zip, args.initial_envelope, args.update_zip,
                            args.update_envelope, args.root, args.report)))
