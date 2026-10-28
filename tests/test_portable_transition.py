import json

import pytest

from nexus_launcher.portable_package import stage_portable_archive
from nexus_launcher.portable_transition import prepare_transition, recover_transition, resolve_transition as actual_resolve_transition
from tests.test_portable_package import fixture, resign


def environment(tmp_path):
    archive, envelope, keys, key = fixture()
    root = tmp_path / "portable-fixture"
    root.mkdir()
    slots = root / "slots"
    slots.mkdir()
    source = tmp_path / "fixture.zip"
    source.write_bytes(archive.getvalue())
    envelope["release"].update(version="1.0.0", platform="windows", arch="x64", available=True)
    resign(envelope, key)
    old = stage_portable_archive(source, envelope, slots, keys=keys)
    envelope["release"]["version"] = "2.0.0"
    resign(envelope, key)
    new = stage_portable_archive(source, envelope, slots, keys=keys)
    (root / "active.json").write_text(json.dumps({"slot": old.name}))
    (root / "user-data.json").write_text("unchanged synthetic data")
    return root, old, new, keys, envelope, key, source


def prepare(root, old, new, keys):
    return prepare_transition(root, new.name, old.name, platform="windows", arch="x64", keys=keys)


def resolve_transition(root, result, *, keys):
    journal = json.loads((root / "transition.json").read_text())
    return actual_resolve_transition(root, result, keys=keys, operation_id=journal["operation_id"],
                                     candidate_identity=journal["candidate_identity"])


@pytest.mark.parametrize("result,phase", [("HEALTHY", "COMPLETE"), ("FAILED", "ROLLED_BACK")])
def test_verified_switch_or_failure_preserves_versions_and_user_data(tmp_path, result, phase):
    root, old, new, keys, *_ = environment(tmp_path)
    prepare(root, old, new, keys)
    assert json.loads((root / "active.json").read_text())["slot"] == old.name
    assert resolve_transition(root, result, keys=keys)["phase"] == phase
    assert json.loads((root / "active.json").read_text())["slot"] == (new.name if result == "HEALTHY" else old.name)
    assert old.exists() and new.exists()
    assert (root / "user-data.json").read_text() == "unchanged synthetic data"


def test_unknown_and_restart_block_new_mutations_until_explicit_resolution(tmp_path):
    root, old, new, keys, *_ = environment(tmp_path)
    prepare(root, old, new, keys)
    assert recover_transition(root)["phase"] == "UNKNOWN"
    with pytest.raises(RuntimeError, match="Unresolved"):
        prepare(root, old, new, keys)
    assert resolve_transition(root, "UNKNOWN", keys=keys)["phase"] == "UNKNOWN"
    assert resolve_transition(root, "FAILED", keys=keys)["phase"] == "ROLLED_BACK"


@pytest.mark.parametrize("point", ["COMMITTING", "active", "COMPLETE"])
def test_interrupted_commit_never_blindly_repeats_and_can_rollback(tmp_path, monkeypatch, point):
    import nexus_launcher.portable_transition as transition

    root, old, new, keys, *_ = environment(tmp_path)
    prepare(root, old, new, keys)
    original = transition.atomic_json
    def interrupted(path, data):
        if (path.name == "active.json" and point == "active") or data.get("phase") == point:
            raise OSError("synthetic interruption")
        return original(path, data)
    with monkeypatch.context() as patch:
        patch.setattr(transition, "atomic_json", interrupted)
        with pytest.raises(OSError):
            resolve_transition(root, "HEALTHY", keys=keys)
    assert recover_transition(root)["phase"] == "UNKNOWN"
    resolve_transition(root, "FAILED", keys=keys)
    assert json.loads((root / "active.json").read_text()) == {"slot": old.name}


def test_candidate_tamper_or_corrupt_previous_never_replaces_pointer(tmp_path):
    root, old, new, keys, *_ = environment(tmp_path)
    prepare(root, old, new, keys)
    (new / "files/launcher.exe").write_bytes(b"tamper")
    with pytest.raises(ValueError):
        resolve_transition(root, "HEALTHY", keys=keys)
    (old / "files/launcher.exe").write_bytes(b"corrupt backup")
    with pytest.raises(ValueError):
        resolve_transition(root, "FAILED", keys=keys)
    assert json.loads((root / "active.json").read_text()) == {"slot": old.name}


def test_wrong_platform_or_active_id_refused_before_journal(tmp_path):
    root, old, new, keys, *_ = environment(tmp_path)
    with pytest.raises(ValueError):
        prepare_transition(root, new.name, old.name, platform="linux", arch="x64", keys=keys)
    with pytest.raises(ValueError):
        prepare_transition(root, new.name, "foreign-slot", platform="windows", arch="x64", keys=keys)
    assert not (root / "transition.json").exists()


def test_rollback_retains_signed_highest_version_and_refuses_lower_candidate(tmp_path):
    root, old, new, keys, envelope, key, source = environment(tmp_path)
    prepare(root, old, new, keys)
    resolve_transition(root, "FAILED", keys=keys)
    envelope["release"]["version"] = "1.5.0"
    resign(envelope, key)
    lower = stage_portable_archive(source, envelope, root / "slots", keys=keys)
    with pytest.raises(ValueError, match="rollback"):
        prepare(root, old, lower, keys)


def test_foreign_pointer_change_or_replayed_health_does_not_switch(tmp_path):
    root, old, new, keys, *_ = environment(tmp_path)
    prepare(root, old, new, keys)
    (root / "active.json").write_text(json.dumps({"slot": "foreign"}))
    with pytest.raises(ValueError, match="conflict"):
        resolve_transition(root, "HEALTHY", keys=keys)
    assert json.loads((root / "active.json").read_text())["slot"] == "foreign"


@pytest.mark.parametrize("wrong", ["operation", "candidate"])
def test_stale_health_cannot_confirm_another_operation(tmp_path, wrong):
    root, old, new, keys, *_ = environment(tmp_path)
    journal = prepare(root, old, new, keys)
    with pytest.raises(ValueError, match="health"):
        actual_resolve_transition(root, "HEALTHY", keys=keys,
                                  operation_id="old-operation" if wrong == "operation" else journal["operation_id"],
                                  candidate_identity="wrong-package" if wrong == "candidate" else journal["candidate_identity"])
    assert json.loads((root / "active.json").read_text()) == {"slot": old.name}
    assert json.loads((root / "transition.json").read_text())["phase"] == "PREPARED"
