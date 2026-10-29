import hashlib
from pathlib import Path
import runpy
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nexus_launcher import public_update_identity as identity
from nexus_launcher.portable_package import verify_portable_archive

build = runpy.run_path(str(Path(__file__).parents[1] / 'packaging/sign_public_update.py'))['build_envelope']
URL = 'https://github.com/robloxksergg-creator/nexus-launcher/releases/download/v1.0.1/package.zip'


def package(tmp_path, extra=None):
    path = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in {'NEXUS Managed Launcher.exe': b'NOT EXECUTABLE',
                           '_internal/runtime.dll': b'SYNTHETIC', **(extra or {})}.items():
            archive.writestr(name, data)
    return path


def test_synthetic_signing_binds_exact_archive_inventory_version_and_repository(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(identity, 'PUBLIC_KEY', key.public_key().public_bytes_raw().hex())
    archive = package(tmp_path)
    before = archive.read_bytes()
    envelope = build(archive, URL, key)
    assert envelope['release']['sha256'] == hashlib.sha256(before).hexdigest()
    assert envelope['release']['size'] == len(before)
    assert envelope['release']['version'] == identity.VERSION
    assert envelope['release']['url'] == URL
    assert len(verify_portable_archive(archive, envelope, keys={identity.KEY_ID: identity.PUBLIC_KEY}).files) == 2
    assert archive.read_bytes() == before


def test_wrong_signer_cannot_create_a_release_envelope(tmp_path):
    with pytest.raises(ValueError, match='signer'):
        build(package(tmp_path), URL, Ed25519PrivateKey.generate())


def test_even_owner_signed_package_cannot_include_user_data(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(identity, 'PUBLIC_KEY', key.public_key().public_bytes_raw().hex())
    with pytest.raises(ValueError, match='User data'):
        build(package(tmp_path, {'data/world.txt': b'USER FIXTURE'}), URL, key)
