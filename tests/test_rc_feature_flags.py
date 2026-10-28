import json
import re

import nexus_launcher.feature_flags as feature_flags


def test_player_rc_disables_unfinished_cloud_controls(monkeypatch):
    monkeypatch.delenv("NEXUS_ENVIRONMENT", raising=False)
    assert feature_flags.feature_enabled("creatorCloudPublishing") is False
    assert feature_flags.feature_enabled("controlCenter") is False


def test_staging_keeps_capability_gated_cloud_tools(monkeypatch):
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "staging")
    assert feature_flags.feature_enabled("creatorCloudPublishing") is True
    assert feature_flags.feature_enabled("controlCenter") is True


def test_unknown_feature_fails_closed(monkeypatch):
    monkeypatch.delenv("NEXUS_ENVIRONMENT", raising=False)
    assert feature_flags.feature_enabled("doesNotExist") is False


def test_packaged_feature_flags_are_boolean():
    path = feature_flags.ROOT / "assets/rc-feature-flags.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert all(type(value) is bool for channel in ("playerRc", "staging") for value in data[channel].values())


def test_tester_build_does_not_enable_operator_cloud_tools(monkeypatch):
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "staging")
    monkeypatch.setattr(feature_flags.build_channel, "TESTER_BUILD", True)
    assert not feature_flags.feature_enabled("creatorCloudPublishing")
    assert not feature_flags.feature_enabled("controlCenter")


def test_environment_cannot_disable_tester_build_restriction(monkeypatch):
    monkeypatch.setattr(feature_flags.build_channel, "TESTER_BUILD", True)
    monkeypatch.setenv("TESTER_BUILD", "false")
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "staging")
    assert not feature_flags.feature_enabled("controlCenter")


def test_tester_release_identity_preserves_update_trust_metadata(monkeypatch):
    import importlib.util
    import nexus_launcher.release_metadata as release_metadata
    spec = importlib.util.spec_from_file_location('synthetic_release_metadata', release_metadata.__file__)
    monkeypatch.setattr(feature_flags.build_channel, 'TESTER_BUILD', True)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stable = json.loads((release_metadata.ROOT / 'assets/release.json').read_text(encoding='utf-8'))
    tester = json.loads((release_metadata.ROOT / 'assets/tester-release.json').read_text(encoding='utf-8'))
    assert module.CURRENT_VERSION == tester['version']
    assert module.METADATA['channel'] == tester['channel'] == 'beta'
    assert module.METADATA['status'] == tester['status']
    beta_keys = tester['trusted_update_keys']
    assert isinstance(beta_keys, dict) and beta_keys
    assert all(isinstance(key_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key_id)
               and isinstance(public, str) and re.fullmatch(r'[0-9a-f]{64}', public)
               for key_id, public in beta_keys.items())
    assert module.METADATA['trusted_update_keys'] == beta_keys
    assert set(beta_keys).isdisjoint(stable['trusted_update_keys'])
    assert set(beta_keys.values()).isdisjoint(stable['trusted_update_keys'].values())
    for key, value in stable.items():
        if key not in {'version', 'channel', 'status', 'trusted_update_keys'}:
            assert module.METADATA[key] == value
    # Reload the same implementation in stable mode: the tester overlay must
    # neither replace nor merge any part of the stable release metadata.
    monkeypatch.setattr(feature_flags.build_channel, 'TESTER_BUILD', False)
    stable_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stable_module)
    assert stable_module.METADATA == stable
    assert stable_module.METADATA['trusted_update_keys'] == stable['trusted_update_keys']
