"""Native two-version acceptance with ephemeral synthetic release signatures.

Launches actual frozen GUI bundles through the production POSIX adapter.
Fixture keys exist only in this parent harness, never in a binary, feed or
published release. This tests lifecycle and data preservation, not owner trust.
"""
import argparse
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def verify(initial, update, initial_inventory, update_inventory, root, output, platform, arch):
    if os.name != 'posix':
        raise OSError('Native POSIX acceptance required')
    root, output = Path(root).absolute(), Path(output).absolute()
    if root.exists() or output.exists():
        raise ValueError('New acceptance paths required')
    root.mkdir()
    output.mkdir()
    # Imports occur after the caller selected the native source/harness.
    from nexus_launcher.bootstrap_installation import provision_initial
    from nexus_launcher.github_updates import GitHubPackageTransport
    from nexus_launcher.posix_bootstrap_process import PosixLaunchLease, PosixProcessAdapter
    from nexus_launcher.posix_package import verify_tree
    from nexus_launcher.portable_package import verify_staged_portable
    from nexus_launcher.signed_release import METADATA, canonical
    from nexus_launcher.posix_update_main import provision_directory, PosixStartupBackend
    key = Ed25519PrivateKey.generate()
    keys = {'native-fixture': key.public_key().public_bytes_raw().hex()}
    now = datetime.now(UTC)

    def envelope(metadata, archive):
        p = json.loads(Path(metadata).read_text(encoding='utf-8'))
        if p['platform'] != platform or p['arch'] != arch:
            raise ValueError('Wrong native acceptance target')
        with Path(archive).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != p['sha256']:
                raise ValueError('Native fixture archive hash mismatch')
        p.update(channel=METADATA['channel'], available=True,
                 published_at=(now - timedelta(minutes=1)).isoformat(),
                 expires_at=(now + timedelta(days=1)).isoformat(),
                 url='https://github.com/robloxksergg-creator/nexus-launcher/releases/download/'
                     'native-fixture/' + Path(archive).name)
        return {'schema': 2, 'key_id': 'native-fixture', 'release': p,
                'signature': base64.b64encode(key.sign(canonical(p))).decode()}

    first, second = envelope(initial_inventory, initial), envelope(update_inventory, update)
    transport = GitHubPackageTransport('https://github.com/robloxksergg-creator/nexus-launcher/'
                                       'releases/download/native-fixture/posix-envelope.json')
    manifest = output / 'fixture-envelope.json'
    manifest.write_text(json.dumps(second), encoding='utf-8')
    def local_open(url, offset=0):
        if offset:
            raise ValueError('No interrupted fixture reads expected')
        if url == transport.manifest_url:
            return manifest.open('rb')
        if url == second['release']['url']:
            return Path(update).open('rb')
        raise ValueError('Native fixture egress forbidden')
    transport._open = local_open

    class Adapter(PosixProcessAdapter):
        def __init__(self, lease):
            super().__init__(lease, health_timeout=90)
            self.children, self.report = [], None
        def _argv(self, executable):
            return [str(executable), '--self-test-report', str(self.report), '--preinstall-smoke']
        def launch(self, *args):
            child = super().launch(*args)
            self.children.append(child)
            return child

    os.environ['XDG_DATA_HOME'] = str(root / 'desktop-data')
    (root / 'home').mkdir()
    os.environ['HOME'] = str(root / 'home')
    data = root / 'player-world.dat'
    data.write_bytes(b'synthetic player data, must not change')
    before = hashlib.sha256(data.read_bytes()).hexdigest()
    managed = root / 'managed'
    versions = []
    with PosixLaunchLease(managed) as lease:
        adapter = Adapter(lease)
        backend = PosixStartupBackend(managed, transport=transport, adapter=adapter,
                                      platform=platform, arch=arch, keys=keys)
        try:
            provision_initial(managed, initial, first, platform=platform, arch=arch, keys=keys)
            pointer = (managed / 'active.json').read_bytes()
            slot = json.loads(pointer)['slot']
            initial_slot = managed / 'slots' / slot
            inv = verify_staged_portable(initial_slot, keys=keys)
            # Also verify first-launch adoption without any binary mutation.
            adopted = root / 'adopted'
            assert provision_directory(adopted, initial_slot / 'files', first, platform=platform,
                                       arch=arch, version=first['release']['version'], keys=keys)
            for index, signed in enumerate((first, second)):
                adapter.report = output / ('native-' + str(index) + '.json')
                if index == 0:
                    assert backend.launch_current() is True
                else:
                    release = backend.check()
                    assert release is not None
                    archive = backend.download(release, lambda *_: None)
                    candidate = backend.stage(archive, release)
                    assert backend.activate(candidate) == 'COMPLETE'
                assert adapter.children[-1].wait(timeout=90) == 0
                report = json.loads(adapter.report.read_text(encoding='utf-8'))
                assert report['release_version'] == signed['release']['version']
                assert report['loaded'] and report['application_icon'] and not report['script_errors']
                assert report['preinstall']['visible'] and report['preinstall']['cards'] == 5
                versions.append({'version': report['release_version'], 'native_readiness': 'PASS'})
            assert (managed / 'active.json').read_bytes() != pointer
            assert hashlib.sha256(data.read_bytes()).hexdigest() == before
            verify_tree(initial_slot / 'files', inv)
        finally:
            for child in adapter.children:
                if child.poll() is None and not adapter.stop_and_wait(child):
                    raise RuntimeError('Owned native fixture child could not be reaped')
    result = {'platform': platform, 'arch': arch, 'versions': versions,
              'user_data_preserved': True, 'initial_adoption_verified': True,
              'signed_fixture_trust': 'ephemeral parent-harness key only',
              'scope': 'Real frozen UI, IPC, executable mode, bundle integrity and pointer update; '
                       'not owner-signed feed or real game/account qualification'}
    (output / 'native-posix-update-acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('initial', 'update', 'initial-inventory', 'update-inventory', 'root', 'output', 'platform', 'arch'):
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    verify(a.initial, a.update, a.initial_inventory, a.update_inventory, a.root, a.output, a.platform, a.arch)
