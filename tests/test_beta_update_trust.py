import importlib.util
import json
from pathlib import Path
import sys

import pytest
import nexus_launcher.build_channel as build_channel

_ABSENT = object()


def load(tmp_path, monkeypatch, *, tester, keys=_ABSENT):
    assets = tmp_path/'assets'
    assets.mkdir()
    (assets/'release.json').write_text(json.dumps({'version':'1.0.0','channel':'stable',
                                                  'trusted_update_keys':{'stable-key':'a'*64}}))
    config = {'version':'1.0.0-beta.2','channel':'beta','status':'private'}
    if keys is not _ABSENT:
        config['trusted_update_keys'] = keys
    (assets/'tester-release.json').write_text(json.dumps(config))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(build_channel, 'TESTER_BUILD', tester)
    spec = importlib.util.spec_from_file_location(
        'isolated_test_metadata',
        Path(__file__).resolve().parents[1] / 'nexus_launcher' / 'release_metadata.py',
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_beta_and_stable_trust_stores_stay_separate(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch, tester=True, keys={'beta-key':'b'*64})
    assert module.METADATA['channel'] == 'beta'
    assert module.METADATA['trusted_update_keys'] == {'beta-key':'b'*64}


def test_stable_ignores_tester_trust_even_if_malformed(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch, tester=False, keys={'bad':'invalid'})
    assert module.METADATA['trusted_update_keys'] == {'stable-key':'a'*64}


def test_missing_beta_trust_preserves_legacy_inheritance(tmp_path, monkeypatch):
    # Compatibility only: omission differs from an explicitly empty/invalid
    # beta store, which must still fail closed in the existing tests below.
    module = load(tmp_path, monkeypatch, tester=True)
    assert module.METADATA['channel'] == 'beta'
    assert module.METADATA['trusted_update_keys'] == {'stable-key':'a'*64}


@pytest.mark.parametrize('keys', [{}, {'beta-key':'invalid'}, {'../key':'b'*64}, ['b'*64]])
def test_invalid_beta_trust_is_rejected(tmp_path, monkeypatch, keys):
    with pytest.raises(ValueError, match='trust store'):
        load(tmp_path, monkeypatch, tester=True, keys=keys)
