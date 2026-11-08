"""Separate build-time feed; no runtime opt-in changes to existing installations."""
import base64
from pathlib import Path
import runpy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nexus_launcher import public_update_identity, signed_release
from nexus_launcher.installer_location import default_directory


def test_isolated_tester_variant_leaves_source_and_public_feed_unchanged(tmp_path):
    root = Path(__file__).parents[1]
    source = tmp_path / 'source'
    (source/'nexus_launcher').mkdir(parents=True)
    (source/'packaging/metadata').mkdir(parents=True)
    (source/'assets').mkdir()
    before = (root/'nexus_launcher/public_update_identity.py').read_bytes()
    (source/'nexus_launcher/public_update_identity.py').write_bytes(before)
    for name in ('LICENSE', 'COPYRIGHT.md'):
        (source/name).write_text('synthetic')
    for name in ('public_version_info.txt', 'public_bootstrap_version_info.txt'):
        (source/'packaging/metadata'/name).write_text('filevers=(1, 0, 1, 0)')
    prepare = runpy.run_path(str(root/'packaging/prepare_public_variant.py'))['prepare']
    result = prepare(source, tmp_path/'testers', '1.0.11', audience='testers')
    identity = runpy.run_path(str(result/'nexus_launcher/public_update_identity.py'))
    assert identity['CHANNEL'] == 'beta'
    assert identity['VERSION'] == '1.0.11'
    assert identity['FEED'].endswith('/updates-testers/portable-envelope.json')
    assert identity['PUBLIC_KEY'] == public_update_identity.PUBLIC_KEY
    assert (source/'nexus_launcher/public_update_identity.py').read_bytes() == before
    assert public_update_identity.CHANNEL == 'stable'
    assert '/updates-preview/' in public_update_identity.FEED


@pytest.mark.parametrize('installed,incoming', [('stable', 'beta'), ('beta', 'stable')])
def test_correct_signature_cannot_cross_update_channels(monkeypatch, installed, incoming):
    key = Ed25519PrivateKey.generate()
    payload = {'channel': incoming, 'version': '1.0.11'}
    envelope = {'schema': 2, 'key_id': 'synthetic', 'release': payload,
                'signature': base64.b64encode(key.sign(signed_release.canonical(payload))).decode()}
    monkeypatch.setitem(signed_release.METADATA, 'channel', installed)
    with pytest.raises(ValueError, match='канал'):
        signed_release.verify_signature(envelope, keys={'synthetic':key.public_key().public_bytes_raw().hex()})


def test_tester_default_install_directory_is_separate(monkeypatch, tmp_path):
    monkeypatch.setattr(public_update_identity, 'CHANNEL', 'beta')
    assert default_directory(tmp_path/'Setup.exe') == tmp_path/'NEXUS Testers'


def test_tester_sessions_are_separate_without_reading_or_migrating_stable_tokens(monkeypatch):
    import nexus_launcher.build_channel as channel
    from nexus_launcher.nexus_account import NexusAccountClient
    monkeypatch.setattr(channel, 'PUBLIC_PREVIEW_BUILD', True)
    monkeypatch.setattr(channel, 'STAGING_BUILD', False)
    monkeypatch.setattr(public_update_identity, 'CHANNEL', 'stable')
    stable = NexusAccountClient()
    monkeypatch.setattr(public_update_identity, 'CHANNEL', 'beta')
    beta = NexusAccountClient()
    assert beta.keyring_service == stable.keyring_service + ' / tester-updates'
    assert beta.base_url == stable.base_url
