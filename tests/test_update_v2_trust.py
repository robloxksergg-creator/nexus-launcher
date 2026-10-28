"""Synthetic TUF repositories only. Ephemeral keys are NEVER serialized."""
import ast
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path

import pytest
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root, Targets, Snapshot, Timestamp, MetaFile
from tuf.api.exceptions import ExpiredMetadataError

import nexus_launcher.update_v2_anchor as update_v2_anchor
import nexus_launcher.update_v2_trust as trust
from nexus_launcher.build_v2_anchor import render_public_anchor


def sign(md, keys):
    md.signatures.clear()
    for key in keys:
        md.sign(key, append=True)
    return md.to_bytes()


def repository(version=1):
    keys = {role: [CryptoSigner.generate_ed25519() for _ in range(count)]
            for role, count in {'root': 3, 'targets': 2, 'timestamp': 1, 'snapshot': 1}.items()}
    root = Root(version=version, expires=datetime.now(UTC) + timedelta(days=365))
    for role, signers in keys.items():
        for signer in signers:
            root.add_key(signer.public_key, role)
        root.roles[role].threshold = 2 if role in {'root', 'targets'} else 1
    return Metadata(root), keys


def bundle(keys, version=1, *, expires=None):
    end = expires or datetime.now(UTC) + timedelta(days=1)
    targets = sign(Metadata(Targets(version=version, expires=end)), keys['targets'])
    snapshot = sign(Metadata(Snapshot(version=version, expires=end, meta={
        'targets.json': MetaFile(version=version, length=len(targets),
                                 hashes={'sha256': hashlib.sha256(targets).hexdigest()})})), keys['snapshot'])
    timestamp = sign(Metadata(Timestamp(version=version, expires=end,
        snapshot_meta=MetaFile(version=version, length=len(snapshot),
                               hashes={'sha256': hashlib.sha256(snapshot).hexdigest()}))), keys['timestamp'])
    return dict(timestamp=timestamp, snapshot=snapshot, targets=targets)


@pytest.fixture
def env(tmp_path, monkeypatch):
    root, keys = repository()
    raw = sign(root, keys['root'][:2])
    monkeypatch.setattr(update_v2_anchor, 'ROOT_JSON', raw)
    monkeypatch.setattr(update_v2_anchor, 'ROOT_SHA256', hashlib.sha256(raw).hexdigest())
    store = trust.TrustStore.initialize(tmp_path/'trust-v2')
    return store, root, keys


def test_default_anchor_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(update_v2_anchor, 'ROOT_JSON', None)
    with pytest.raises(trust.TrustError):
        trust.TrustStore.initialize(tmp_path/'unprovisioned')
    assert not (tmp_path/'unprovisioned').exists()


def test_valid_bundle_and_restart(env):
    store, _, keys = env
    store.accept_bundle(**bundle(keys))
    assert trust.TrustStore(store.directory).inspect()['metadata_versions'] == dict.fromkeys(trust.ROLES, 1)
    store.accept_bundle(**bundle(keys, 2))
    assert store.inspect()['metadata_versions']['targets'] == 2


@pytest.mark.parametrize('mode', ['one', 'duplicate', 'foreign', 'corrupt'])
def test_bad_root_signature(env, mode):
    store, _, keys = env
    new, newkeys = repository(2)
    raw = sign(new, keys['root'][:2] + newkeys['root'][:2])
    obj = json.loads(raw)
    if mode == 'one':
        raw = sign(new, keys['root'][:1] + newkeys['root'][:2])
    elif mode == 'duplicate':
        raw = sign(new, keys['root'][:1] + newkeys['root'][:2])
        obj = json.loads(raw)
        obj['signatures'].append(obj['signatures'][0])
        raw = json.dumps(obj).encode()
    elif mode == 'foreign':
        raw = sign(new, [CryptoSigner.generate_ed25519()] + newkeys['root'][:2])
    else:
        obj['signed']['expires'] = '2099-01-01T00:00:00Z'
        raw = json.dumps(obj).encode()
    before = (store.directory/'trust-state.json').read_bytes()
    with pytest.raises(Exception):
        store.rotate_root(raw)
    assert (store.directory/'trust-state.json').read_bytes() == before


@pytest.mark.parametrize('mode', ['no-old', 'no-new', 'skip', 'downgrade', 'replay', 'role'])
def test_rotation_refusals(env, mode):
    store, root, keys = env
    new, newkeys = repository(3 if mode == 'skip' else 2)
    if mode in {'replay', 'downgrade'}:
        if mode == 'downgrade':
            store.rotate_root(sign(new, keys['root'][:2]+newkeys['root'][:2]))
        raw = sign(root, keys['root'][:2])
    elif mode == 'role':
        raw = bundle(keys)['targets']
    else:
        signers = (newkeys['root'][:2] if mode == 'no-old' else
                   keys['root'][:2] if mode == 'no-new' else keys['root'][:2]+newkeys['root'][:2])
        raw = sign(new, signers)
    with pytest.raises(Exception):
        store.rotate_root(raw)


def test_rotation_and_revocation(env):
    store, _, keys = env
    store.accept_bundle(**bundle(keys))
    new, newkeys = repository(2)
    raw = sign(new, keys['root'][:2]+newkeys['root'][:2])
    store.rotate_root(raw)
    assert trust.TrustStore(store.directory).inspect()['root_version'] == 2
    with pytest.raises(Exception):
        store.accept_bundle(**bundle(keys, 2))
    store.accept_bundle(**bundle(newkeys, 2))
    assert store.inspect()['metadata_versions']['targets'] == 2


@pytest.mark.parametrize('role', trust.ROLES)
def test_foreign_role_signer_and_substituted_key(env, role):
    store, _, keys = env
    data = bundle(keys)
    md = Metadata.from_bytes(data[role])
    data[role] = sign(md, [CryptoSigner.generate_ed25519()])
    with pytest.raises(Exception):
        store.accept_bundle(**data)
    assert store.inspect()['metadata_versions'] is None


def test_freshness_keys_cannot_authorize_release(env):
    store, _, keys = env
    data = bundle(keys)
    data['targets'] = sign(Metadata.from_bytes(data['targets']), keys['timestamp']+keys['snapshot'])
    with pytest.raises(Exception):
        store.accept_bundle(**data)


def test_replay_equivocation_and_expiry(env):
    store, _, keys = env
    # TUF serializes expiry to whole seconds. Re-generating a bundle using
    # now() can produce identical bytes, which are a permitted replay.
    now = datetime.now(UTC).replace(microsecond=0)
    expiry = now + timedelta(days=1)
    data = bundle(keys, 2, expires=expiry)
    store.accept_bundle(**data)
    store.accept_bundle(**data)  # identical replay is idempotent, not reinstall
    cases = (
        (bundle(keys, 1, expires=expiry), trust.TrustError, 'Metadata rollback refused'),
        (bundle(keys, 2, expires=expiry + timedelta(hours=1)),
         trust.TrustError, 'Metadata equivocation refused'),
        (bundle(keys, 3, expires=now - timedelta(days=1)),
         ExpiredMetadataError, None),
    )
    # The equivocation fixture MUST differ in signed content for every role,
    # even when the entire test runs within a single clock second.
    for role in trust.ROLES:
        assert (Metadata.from_bytes(cases[1][0][role]).signed_bytes
                != Metadata.from_bytes(data[role]).signed_bytes)
    state_path = store.directory/'trust-state.json'
    before = state_path.read_bytes()
    for bad, error, message in cases:
        with pytest.raises(error, match=message):
            store.accept_bundle(**bad)
        assert state_path.read_bytes() == before
    assert store.inspect()['metadata_versions']['timestamp'] == 2


def test_mixed_snapshot_rejected(env):
    store, _, keys = env
    data = bundle(keys)
    data['targets'] = bundle(keys, 2)['targets']
    with pytest.raises(Exception):
        store.accept_bundle(**data)


@pytest.mark.parametrize('damage', ['json', 'digest', 'missing', 'schema'])
def test_corrupt_state_never_resets(env, damage):
    store, _, _ = env
    path = store.directory/'trust-state.json'
    if damage == 'missing':
        path.unlink()
    elif damage == 'json':
        path.write_bytes(b'{')
    else:
        data = json.loads(path.read_bytes())
        data['sha256' if damage == 'digest' else 'state'] = 'damaged'
        path.write_text(json.dumps(data))
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(Exception):
        store.inspect()
    with pytest.raises(FileExistsError):
        trust.TrustStore.initialize(store.directory)
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize('after', [False, True])
def test_interrupted_atomic_rotation_reopens_consistent_state(env, monkeypatch, after):
    store, _, keys = env
    new, newkeys = repository(2)
    raw = sign(new, keys['root'][:2]+newkeys['root'][:2])
    real = trust.replace_file
    def interrupt(src, dst):
        if after:
            real(src, dst)
        raise OSError('synthetic power interruption')
    monkeypatch.setattr(trust, 'replace_file', interrupt)
    with pytest.raises(OSError):
        store.rotate_root(raw)
    assert trust.TrustStore(store.directory).inspect()['root_version'] == (2 if after else 1)


def test_public_build_anchor_and_pin(env, monkeypatch):
    store, root, keys = env
    raw = sign(root, keys['root'][:2])
    generated = {}
    exec(render_public_anchor(raw), generated)
    assert generated['ROOT_JSON'] == raw
    monkeypatch.setattr(update_v2_anchor, 'ROOT_JSON', raw+b' ')
    with pytest.raises(trust.TrustError):
        store.inspect()


def test_duplicate_public_material_cannot_count_as_independent(env):
    _, root, keys = env
    root.signed.keys[keys['root'][1].public_key.keyid].keyval['public'] = keys['root'][0].public_key.keyval['public']
    with pytest.raises(trust.TrustError):
        trust.validate_root(sign(root, keys['root'][:2]))


def test_client_has_no_private_key_or_legacy_dependency():
    source = Path(trust.__file__).read_text()
    tree = ast.parse(source)
    imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(x.startswith(('nexus_launcher.signed_release', 'nexus_launcher.release_metadata', 'securesystemslib.signer',
                                  'cryptography', 'keyring', 'nexus_launcher.offline_sign_release')) for x in imports)
    assert not any(x in source for x in ('load_pem_private_key', 'Ed25519PrivateKey', '.private.pem'))
    assert 'generate_ed25519' not in source
