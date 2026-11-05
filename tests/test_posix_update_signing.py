"""Offline signing tests use ephemeral keys, never the owner's DPAPI key."""
import hashlib
from pathlib import Path
import runpy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.test_posix_updates import bundle, zip_bytes
from nexus_launcher import public_update_identity as identity
from nexus_launcher.signed_release import verify_envelope

build = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/sign_posix_update.py'))['build_envelope']


@pytest.fixture
def signing_inputs(bundle, tmp_path, monkeypatch):
    p, _, _, data = bundle
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(identity, 'PUBLIC_KEY', key.public_key().public_bytes_raw().hex())
    monkeypatch.setattr(identity, 'VERSION', p['version'])
    raw = zip_bytes(p, data)
    archive = tmp_path / 'fixture.zip'
    archive.write_bytes(raw)
    fields = ('format', 'platform', 'arch', 'version', 'entrypoint', 'files')
    metadata = {k: p[k] for k in fields}
    metadata.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    url = 'https://github.com/robloxksergg-creator/nexus-launcher/releases/download/fixture/update.zip'
    return archive, metadata, url, key


def test_offline_signature_covers_posix_modes_links_and_exact_archive(signing_inputs):
    archive, metadata, url, key = signing_inputs
    signed = build(archive, metadata, url, key)
    p = verify_envelope(signed, keys={identity.KEY_ID: identity.PUBLIC_KEY})
    assert p['files'] == metadata['files'] and p['sha256'] == metadata['sha256']
    assert p['available'] is True and p['platform'] == 'linux' and p['url'] == url


@pytest.mark.parametrize('field,value', [('size', 1), ('sha256', '0' * 64), ('version', '9.9.9')])
def test_build_identity_or_archive_mismatch_refuses_signing(signing_inputs, field, value):
    archive, metadata, url, key = signing_inputs
    with pytest.raises(ValueError):
        build(archive, {**metadata, field: value}, url, key)


def test_unrelated_host_and_wrong_signer_refused(signing_inputs):
    archive, metadata, url, key = signing_inputs
    with pytest.raises(ValueError):
        build(archive, metadata, 'https://untrusted.invalid/update.zip', key)
    with pytest.raises(ValueError):
        build(archive, metadata, url, Ed25519PrivateKey.generate())


def test_unsigned_metadata_cannot_supply_grants_or_expiry(signing_inputs):
    archive, metadata, url, key = signing_inputs
    with pytest.raises(ValueError):
        build(archive, {**metadata, 'available': True}, url, key)
