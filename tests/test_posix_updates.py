"""Synthetic signed bundles; no release key, accounts, game or remote network."""
import copy
from datetime import UTC, datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile
import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nexus_launcher.posix_package import FORMAT, TARGETS, inventory, verify_archive, verify_tree, stage_archive
from nexus_launcher.portable_package import verify_portable_inventory, verify_installed_inventory
from nexus_launcher.posix_update_main import feed, provision_directory
from nexus_launcher.signed_release import canonical, METADATA


@pytest.fixture
def bundle():
    key = Ed25519PrivateKey.generate()
    keys = {'fixture': key.public_key().public_bytes_raw().hex()}
    root, entry = TARGETS['linux', 'x64']
    data = {entry: b'synthetic executable', root + '/lib/runtime': b'synthetic runtime'}
    records = [{'path': p, 'kind': 'file', 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
                'mode': 0o755 if p == entry else 0o644} for p, b in data.items()]
    records.append({'path': root + '/runtime-link', 'kind': 'symlink', 'target': 'lib/runtime'})
    now = datetime.now(UTC)
    payload = {'format': FORMAT, 'version': '1.2.3', 'entrypoint': entry,
               'platform': 'linux', 'arch': 'x64', 'available': True,
               'channel': METADATA['channel'], 'published_at': (now - timedelta(minutes=1)).isoformat(),
               'expires_at': (now + timedelta(days=1)).isoformat(), 'files': records}
    def sign(p):
        return {'schema': 2, 'key_id': 'fixture', 'release': p,
                'signature': base64.b64encode(key.sign(canonical(p))).decode()}
    return payload, sign, keys, data


def zip_bytes(payload, data):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as z:
        for item in payload['files']:
            info = zipfile.ZipInfo(item['path'])
            info.create_system = 3
            info.external_attr = ((stat.S_IFLNK | 0o777) if item['kind'] == 'symlink'
                                  else (stat.S_IFREG | item['mode'])) << 16
            z.writestr(info, item['target'].encode() if item['kind'] == 'symlink' else data[item['path']])
    return raw.getvalue()


def test_signed_inventory_and_archive_dispatch(bundle):
    p, sign, keys, data = bundle
    e = sign(p)
    expected = inventory(p)
    assert verify_portable_inventory(e, keys=keys) == expected
    assert verify_archive(io.BytesIO(zip_bytes(p, data)), e, keys=keys) == expected
    changed = copy.deepcopy(e)
    changed['release']['files'][0]['mode'] = 0o644
    with pytest.raises(ValueError):
        verify_portable_inventory(changed, keys=keys)


@pytest.mark.parametrize('change', [
    {'platform': 'windows'}, {'arch': 'arm64'}, {'format': 'unknown'},
    {'version': '1.2'}, {'version': True}, {'entrypoint': 'nexus.exe'},
])
def test_wrong_target_or_identity_refused(bundle, change):
    p = copy.deepcopy(bundle[0])
    p.update(change)
    with pytest.raises(ValueError):
        inventory(p)


@pytest.mark.parametrize('path', ['/escape', '../escape', 'NEXUS-Linux-x64/../escape',
                                  'OTHER/file', 'NEXUS-Linux-x64/a\\b', 'NEXUS-Linux-x64//file'])
def test_unsafe_signed_member_path_refused(bundle, path):
    p = copy.deepcopy(bundle[0])
    p['files'][1]['path'] = path
    with pytest.raises(ValueError):
        inventory(p)


@pytest.mark.parametrize('target', ['/etc/passwd', '../../escape', 'lib/missing',
                                    'runtime-link', 'C:/escape', 'lib\\runtime', 'lib/\x00bad'])
def test_unsafe_dangling_or_cyclic_link_refused(bundle, target):
    p = copy.deepcopy(bundle[0])
    p['files'][-1]['target'] = target
    with pytest.raises(ValueError):
        inventory(p)


def test_resolve_links_before_parent_components(bundle):
    p = copy.deepcopy(bundle[0])
    root = TARGETS['linux', 'x64'][0]
    p['files'] += [{'path': root + '/deep/up', 'kind': 'symlink', 'target': '..'},
                   {'path': root + '/escape', 'kind': 'symlink', 'target': 'deep/up/../outside'}]
    with pytest.raises(ValueError, match='escapes'):
        inventory(p)


@pytest.mark.parametrize('mode', [0o4755, 0o777, 0o600, True, -1])
def test_unsafe_or_noncanonical_mode_refused(bundle, mode):
    p = copy.deepcopy(bundle[0])
    p['files'][0]['mode'] = mode
    with pytest.raises(ValueError):
        inventory(p)


def test_no_descendants_below_links_or_regular_files(bundle):
    p = copy.deepcopy(bundle[0])
    item = copy.deepcopy(p['files'][1])
    item['path'] = 'NEXUS-Linux-x64/runtime-link/child'
    p['files'].append(item)
    with pytest.raises(ValueError):
        inventory(p)


def test_case_duplicate_and_expanded_budget(bundle):
    p = copy.deepcopy(bundle[0])
    item = copy.deepcopy(p['files'][0])
    item['path'] = item['path'].upper()
    p['files'].append(item)
    with pytest.raises(ValueError):
        inventory(p)
    p = copy.deepcopy(bundle[0])
    p['files'][1]['size'] = 2 * 1024**3 + 1
    with pytest.raises(ValueError):
        inventory(p)


def test_archive_content_and_link_tampering_refused(bundle):
    p, sign, keys, data = bundle
    bad = dict(data)
    bad[p['entrypoint']] = b'X' * len(data[p['entrypoint']])
    with pytest.raises(ValueError, match='hash'):
        verify_archive(io.BytesIO(zip_bytes(p, bad)), sign(p), keys=keys)
    q = copy.deepcopy(p)
    q['files'][-1]['target'] = '../outside'
    with pytest.raises(ValueError, match='Link'):
        verify_archive(io.BytesIO(zip_bytes(q, data)), sign(p), keys=keys)


def test_expiry_does_not_invalidate_an_already_installed_inventory(bundle):
    p, sign, keys, _ = bundle
    p = copy.deepcopy(p)
    p['expires_at'] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        verify_portable_inventory(sign(p), keys=keys)
    assert verify_installed_inventory(sign(p), keys=keys).version == '1.2.3'


@pytest.mark.skipif(os.name != 'posix', reason='Native POSIX modes and symbolic links required')
def test_native_stage_copy_initial_provision_and_tamper(bundle, tmp_path):
    p, sign, keys, data = bundle
    source = tmp_path / 'update.zip'
    source.write_bytes(zip_bytes(p, data))
    slot = stage_archive(source, sign(p), tmp_path / 'staged', keys=keys)
    inv = inventory(p)
    verify_tree(slot / 'files', inv)
    assert (slot / 'files/NEXUS-Linux-x64/runtime-link').is_symlink()
    root = tmp_path / 'managed'
    sentinel = tmp_path / 'world.dat'
    sentinel.write_bytes(b'player data')
    assert provision_directory(root, slot / 'files', sign(p), platform='linux', arch='x64',
                               version='1.2.3', keys=keys)
    assert not provision_directory(root, slot / 'files', sign(p), platform='linux', arch='x64',
                                   version='1.2.3', keys=keys)
    assert sentinel.read_bytes() == b'player data'
    (slot / 'files' / p['entrypoint']).chmod(0o644)
    with pytest.raises(ValueError, match='mode'):
        verify_tree(slot / 'files', inv)


def test_distinct_literal_platform_feeds():
    linux, mac = feed('linux', 'x64'), feed('macos', 'arm64')
    assert linux != mac and linux.endswith('posix-envelope-linux-x64.json')
    assert mac.endswith('posix-envelope-macos-arm64.json')
    assert '/v1.2.3-preview.1/' in feed('linux', 'x64', version='1.2.3')
    for args in [('windows', 'x64'), ('linux', 'arm64')]:
        with pytest.raises(ValueError):
            feed(*args)
    with pytest.raises(ValueError):
        feed('linux', 'x64', version='../other')


def test_child_environment_does_not_reuse_old_bundle(monkeypatch):
    from nexus_launcher.posix_bootstrap_process import child_environment
    monkeypatch.setenv('LD_LIBRARY_PATH', '/old/_internal')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/user/runtime')
    monkeypatch.setenv('_PYI_ARCHIVE_FILE', '/old/archive')
    monkeypatch.setenv('NEXUS_POSIX_BOOTSTRAP_FDS', '3,4,5')
    e = child_environment()
    assert e['LD_LIBRARY_PATH'] == '/user/runtime'
    assert e['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
    assert '_PYI_ARCHIVE_FILE' not in e and 'NEXUS_POSIX_BOOTSTRAP_FDS' not in e


@pytest.mark.skipif(os.name != 'posix', reason='Actual inherited POSIX descriptors required')
def test_native_private_ipc_and_lease_survive_parent_close(tmp_path):
    from nexus_launcher.posix_bootstrap_process import PosixLaunchLease, PosixProcessAdapter
    from nexus_launcher.portable_bootstrap import HealthChallenge, valid_health_ack
    # This adapter tests IPC and lease ownership only, not executable qualification.
    class FixtureAdapter(PosixProcessAdapter):
        def _validate(self, executable, cwd):
            pass
        def _argv(self, executable):
            return [str(executable), '-c',
                    'from nexus_launcher.posix_bootstrap_process import PosixChildSession; '
                    'import time; s=PosixChildSession.receive(); s.ready(); time.sleep(30)']
    lease = PosixLaunchLease(tmp_path)
    adapter = FixtureAdapter(lease, health_timeout=5, stop_timeout=1)
    challenge = HealthChallenge('a' * 32, 'b' * 64, 'c' * 64)
    child = adapter.launch(Path(sys.executable), Path.cwd(), challenge)
    try:
        ack = adapter.await_health(child, challenge)
        assert valid_health_ack(ack, challenge, child.pid)
        lease.close()
        with pytest.raises(OSError):
            PosixLaunchLease(tmp_path)
    finally:
        assert adapter.stop_and_wait(child)
        lease.close()
    with PosixLaunchLease(tmp_path):
        pass
