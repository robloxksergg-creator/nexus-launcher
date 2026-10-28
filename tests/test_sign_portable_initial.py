import hashlib

import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nexus_launcher.sign_portable_initial import sign_initial
from nexus_launcher.signed_release import METADATA
from tests.test_portable_package import fixture


def candidate(tmp_path, monkeypatch):
    monkeypatch.setitem(METADATA, 'channel', 'beta')
    archive, envelope, keys, key = fixture()
    path = tmp_path/'initial.zip'
    path.write_bytes(archive.getvalue())
    draft = {**envelope['release'], 'channel':'beta', 'available':False, 'platform':'windows', 'arch':'x64',
             'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'size':path.stat().st_size}
    return path, draft, keys, key


def test_offline_signing_authenticates_full_archive_without_publication(tmp_path, monkeypatch):
    path, draft, keys, key = candidate(tmp_path, monkeypatch)
    result = sign_initial(path, draft, key, key_id='fixture', trusted_keys=keys)
    assert result['release']['available'] is True
    assert result['release']['distribution'] == 'private-bootstrap-initial'
    assert draft['available'] is False


@pytest.mark.parametrize('fault', ['archive', 'file-inventory', 'key', 'stable-channel'])
def test_operator_signer_refuses_wrong_package_or_trust(tmp_path, monkeypatch, fault):
    path, draft, keys, key = candidate(tmp_path, monkeypatch)
    if fault == 'archive': path.write_bytes(b'corrupted')
    if fault == 'file-inventory': draft['files'][0]['sha256'] = '0'*64
    if fault == 'key': key = Ed25519PrivateKey.generate()
    if fault == 'stable-channel': draft['channel'] = 'stable'
    with pytest.raises(ValueError):
        sign_initial(path, draft, key, key_id='fixture', trusted_keys=keys)
