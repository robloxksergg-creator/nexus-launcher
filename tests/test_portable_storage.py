import json
from datetime import UTC, datetime, timedelta

import pytest

from nexus_launcher.portable_storage import managed_portable_data_root
from nexus_launcher.portable_transition import prepare_transition, resolve_transition
from tests.test_portable_package import resign
from tests.test_portable_transition import environment


def test_versions_share_stable_data_root_without_copy_or_migration(tmp_path):
    root, old, new, keys, *_ = environment(tmp_path)
    data = root / "data"
    data.mkdir()
    (data / "settings.json").write_text("unchanged synthetic settings")
    assert managed_portable_data_root(old / "files/launcher.exe", keys=keys) == data
    journal = prepare_transition(root, new.name, old.name, platform="windows", arch="x64", keys=keys)
    journal["phase"] = "LAUNCHING"
    (root / "transition.json").write_text(json.dumps(journal))
    assert managed_portable_data_root(new / "files/launcher.exe", keys=keys) == data
    resolve_transition(root, "HEALTHY", operation_id=journal["operation_id"],
                       candidate_identity=journal["candidate_identity"], keys=keys)
    assert managed_portable_data_root(new / "files/launcher.exe", keys=keys) == data
    assert (data / "settings.json").read_text() == "unchanged synthetic settings"
    assert not (old / "files/data").exists() and not (new / "files/data").exists()


@pytest.mark.parametrize("change", ["unselected", "unknown", "tamper", "wrong-entry", "fake-ready"])
def test_untrusted_launch_cannot_select_storage(tmp_path, change):
    root, old, new, keys, *_ = environment(tmp_path)
    executable = old / "files/launcher.exe"
    if change == "unselected":
        executable = new / "files/launcher.exe"
    elif change == "unknown":
        (root / "transition.json").write_text(json.dumps({"phase": "UNKNOWN"}))
    elif change == "tamper":
        executable.write_bytes(b"corrupt")
    elif change == "wrong-entry":
        executable = old / "files/unlisted.exe"
        executable.write_bytes(b"fixture")
    else:
        (old / "journal.json").write_text(json.dumps({"schema": 1, "phase": "READY", "approved": True}))
    with pytest.raises(ValueError):
        managed_portable_data_root(executable, keys=keys)
    assert not (root / "data").exists()


def test_installed_expired_metadata_does_not_disable_existing_data_access(tmp_path):
    root, old, _new, keys, _envelope, key, _source = environment(tmp_path)
    envelope = json.loads((old / "envelope.json").read_text())
    envelope["release"]["expires_at"] = (datetime.now(UTC)-timedelta(minutes=1)).isoformat()
    resign(envelope, key)
    (old / "envelope.json").write_text(json.dumps(envelope))
    assert managed_portable_data_root(old / "files/launcher.exe", keys=keys) == root / "data"


def test_expired_pending_candidate_is_not_treated_as_installed(tmp_path):
    root, old, new, keys, _envelope, key, _source = environment(tmp_path)
    journal = prepare_transition(root, new.name, old.name, platform="windows", arch="x64", keys=keys)
    journal["phase"] = "LAUNCHING"
    (root / "transition.json").write_text(json.dumps(journal))
    envelope = json.loads((new / "envelope.json").read_text())
    envelope["release"]["expires_at"] = (datetime.now(UTC)-timedelta(minutes=1)).isoformat()
    resign(envelope, key)
    (new / "envelope.json").write_text(json.dumps(envelope))
    with pytest.raises(ValueError):
        managed_portable_data_root(new / "files/launcher.exe", keys=keys)


def test_portable_entrypoint_does_not_trust_ambient_data_override(tmp_path, monkeypatch):
    from nexus_launcher.portable_main import portable_data_root

    executable = tmp_path / "normal" / "launcher.exe"
    monkeypatch.setattr("sys.executable", str(executable))
    monkeypatch.setenv("NEXUS_PORTABLE_DATA", str(tmp_path / "foreign"))
    assert portable_data_root() == executable.parent / "data"


def test_managed_entrypoint_uses_verified_storage_resolver(tmp_path, monkeypatch):
    from nexus_launcher.portable_main import portable_data_root

    executable = tmp_path / "slots/portable-stage-fixture/files/launcher.exe"
    monkeypatch.setattr("sys.executable", str(executable))
    calls = []
    def resolved(path):
        calls.append(path)
        return tmp_path / "data"
    monkeypatch.setattr("nexus_launcher.portable_storage.managed_portable_data_root", resolved)
    assert portable_data_root() == tmp_path / "data"
    assert calls == [executable]


def test_entrypoint_holds_data_pin_while_starting_fixture_not_real_gui(tmp_path, monkeypatch):
    import sys
    import types
    from contextlib import contextmanager
    import nexus_launcher.safe_paths as safe_paths
    from nexus_launcher.portable_main import main

    executable = tmp_path / "portable" / "launcher.exe"
    monkeypatch.setattr(sys, "executable", str(executable))
    pinned = []
    original = safe_paths.pinned_directory
    @contextmanager
    def observed(path, **kwargs):
        with original(path, **kwargs):
            pinned.append(path)
            try:
                yield path
            finally:
                pinned.pop()
    monkeypatch.setattr(safe_paths, "pinned_directory", observed)
    preview = types.ModuleType("nexus_launcher.preview_prototype")
    calls = []
    def synthetic_run():
        import os
        assert pinned == [executable.parent / "data"]
        assert os.environ["NEXUS_PORTABLE_DATA"] == str(executable.parent / "data")
        calls.append("fixture started")
    preview.main = synthetic_run
    monkeypatch.setitem(sys.modules, "nexus_launcher.preview_prototype", preview)
    main()
    assert calls == ["fixture started"] and not pinned
