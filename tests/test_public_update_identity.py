import importlib.util
import json
from pathlib import Path

import pytest

import nexus_launcher.build_channel as channel
from nexus_launcher import public_update_identity as identity


def load_identity():
    path = Path(__file__).parents[1] / 'nexus_launcher/release_metadata.py'
    spec = importlib.util.spec_from_file_location('_isolated_public_release_identity', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_identity_has_only_new_public_key_and_keeps_legacy_file(monkeypatch):
    path = Path(__file__).parents[1] / 'assets/release.json'
    before = path.read_bytes()
    monkeypatch.setattr(channel, 'PUBLIC_PREVIEW_BUILD', True)
    monkeypatch.setattr(channel, 'TESTER_BUILD', False)
    monkeypatch.setattr(channel, 'STAGING_BUILD', False)
    module = load_identity()
    assert module.METADATA['trusted_update_keys'] == {identity.KEY_ID: identity.PUBLIC_KEY}
    assert module.CURRENT_VERSION == '1.0.1'
    assert module.METADATA['channel'] == 'stable'
    assert path.read_bytes() == before
    assert identity.KEY_ID not in json.loads(before)['trusted_update_keys']


@pytest.mark.parametrize('flag', ['TESTER_BUILD', 'STAGING_BUILD'])
def test_public_identity_rejects_mixed_environment(monkeypatch, flag):
    monkeypatch.setattr(channel, 'PUBLIC_PREVIEW_BUILD', True)
    monkeypatch.setattr(channel, flag, True)
    with pytest.raises(ValueError, match='Public preview'):
        load_identity()


def test_default_identity_remains_legacy(monkeypatch):
    monkeypatch.setattr(channel, 'PUBLIC_PREVIEW_BUILD', False)
    monkeypatch.setattr(channel, 'TESTER_BUILD', False)
    module = load_identity()
    assert 'nexus-launcher-updates-2026-01' in module.METADATA['trusted_update_keys']
    assert identity.KEY_ID not in module.METADATA['trusted_update_keys']
