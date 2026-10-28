"""Real temporary-file recovery parity; no game installation or external IO."""

import hashlib
import json

import pytest

from nexus_launcher import file_transaction as tx


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    core = tx._native
    if request.param == "rust":
        if core is None or getattr(core, "TRANSACTION_API_VERSION", None) != 1:
            pytest.skip("Native transaction extension is not installed")
    else:
        monkeypatch.setattr(tx, "_native", None)
    return request.param


def generation(tmp_path):
    root, stage = tmp_path / "game", tmp_path / "stage"
    (root / "mods").mkdir(parents=True)
    (stage / "mods").mkdir(parents=True)
    (root / ".nexus-launcher").mkdir()
    (root / "mods/a.jar").write_bytes(b"old-a")
    (root / "mods/b.jar").write_bytes(b"old-b")
    (root / ".nexus-launcher/pack.json").write_text('{"version":"old"}')
    (stage / "mods/a.jar").write_bytes(b"new-a")
    record = {"path": "mods/a.jar", "sha256": hashlib.sha256(b"new-a").hexdigest()}
    return root, stage, record


def journal_fixture(root, phase="prepared"):
    operation = root / tx.OPERATION
    (operation / "backup").mkdir(parents=True)
    items = []
    for i, path in enumerate(["mods/a.jar", "mods/b.jar", ".nexus-launcher/pack.json"]):
        old = (root / path).read_bytes()
        (operation / "backup" / str(i)).write_bytes(old)
        items.append({"path": path, "existed": True, "sha256": hashlib.sha256(old).hexdigest()})
    state = {"phase": phase, "files": items}
    (operation / "journal.json").write_text(json.dumps(state))
    return operation, state


def assert_old(root):
    assert (root / "mods/a.jar").read_bytes() == b"old-a"
    assert (root / "mods/b.jar").read_bytes() == b"old-b"
    assert json.loads((root / ".nexus-launcher/pack.json").read_text()) == {"version": "old"}


def test_apply_tuple_inputs_and_repeated_recovery(tmp_path, backend):
    root, stage, record = generation(tmp_path)
    tx.apply(root, stage, (record,), ("mods/b.jar",), ".nexus-launcher/pack.json", {"version": "new"})
    assert (root / "mods/a.jar").read_bytes() == b"new-a"
    assert not (root / "mods/b.jar").exists()
    assert json.loads((root / ".nexus-launcher/pack.json").read_text())["version"] == "new"
    assert not (root / tx.OPERATION).exists()
    tx.recover(root)
    tx.recover(root)
    assert (root / "mods/a.jar").read_bytes() == b"new-a"


def test_corrupt_later_backup_blocks_all_restoration(tmp_path, backend):
    root, _, _ = generation(tmp_path)
    operation, _ = journal_fixture(root)
    (root / "mods/a.jar").write_bytes(b"partially-new-a")
    (root / "mods/b.jar").write_bytes(b"partially-new-b")
    (operation / "backup/1").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Corrupt transaction backup"):
        tx.recover(root)
    assert (root / "mods/a.jar").read_bytes() == b"partially-new-a"
    assert (root / "mods/b.jar").read_bytes() == b"partially-new-b"
    assert json.loads((operation / "journal.json").read_text())["phase"] == "prepared"


def test_prepared_recovers_old_and_deletes_new_file(tmp_path, backend):
    root, _, _ = generation(tmp_path)
    operation, state = journal_fixture(root)
    state["files"].append({"path": "mods/new.jar", "existed": False})
    (operation / "journal.json").write_text(json.dumps(state))
    (root / "mods/new.jar").write_bytes(b"new")
    (root / "mods/a.jar").write_bytes(b"partially-new")
    tx.recover(root)
    assert_old(root)
    assert not (root / "mods/new.jar").exists()
    assert not operation.exists()


@pytest.mark.parametrize("phase", ["preparing", "committed"])
def test_non_prepared_does_not_restore_backups(tmp_path, backend, phase):
    root, _, _ = generation(tmp_path)
    operation, _ = journal_fixture(root, phase)
    (operation / "backup/0").write_bytes(b"corrupt")
    tx.recover(root)
    assert_old(root)
    assert not operation.exists()


@pytest.mark.parametrize("invalid", ["phase", "empty", "bool", "duplicate", "traversal", "foreign"])
def test_invalid_journal_does_not_modify_installation(tmp_path, backend, invalid):
    root, _, _ = generation(tmp_path)
    operation, state = journal_fixture(root)
    if invalid == "phase":
        state["phase"] = "unknown"
    elif invalid == "empty":
        state["files"] = []
    elif invalid == "bool":
        state["files"][0]["existed"] = 1
    elif invalid == "duplicate":
        state["files"].append({"path": "MODS/A.JAR", "existed": False})
    elif invalid == "traversal":
        state["files"][0]["path"] = "../escape"
    else:
        state["files"][0]["path"] = "saves/world.dat"
    raw = json.dumps(state)
    (operation / "journal.json").write_text(raw)
    with pytest.raises(ValueError):
        tx.recover(root)
    assert_old(root)
    assert (operation / "journal.json").read_text() == raw


def test_failed_commit_journal_rolls_back_and_reraises(tmp_path, backend, monkeypatch):
    root, stage, record = generation(tmp_path)
    original = tx.atomic_json
    failed = False

    def writing(path, state):
        nonlocal failed
        if path.name == "journal.json" and state["phase"] == "committed" and not failed:
            failed = True
            raise OSError("synthetic journal write failure")
        return original(path, state)

    monkeypatch.setattr(tx, "atomic_json", writing)
    with pytest.raises(OSError, match="synthetic journal write failure"):
        tx.apply(root, stage, [record], ["mods/b.jar"], ".nexus-launcher/pack.json", {"version": "new"})
    assert failed
    assert_old(root)
    assert not (root / tx.OPERATION).exists()


def test_bad_staging_does_not_create_transaction(tmp_path, backend):
    root, stage, record = generation(tmp_path)
    record["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Staging hash mismatch"):
        tx.apply(root, stage, [record], [], ".nexus-launcher/pack.json", {})
    assert_old(root)
    assert not (root / tx.OPERATION).exists()


def test_invalid_staging_argument_does_not_begin_recovery(tmp_path, backend):
    root, _, _ = generation(tmp_path)
    operation, _ = journal_fixture(root)
    journal = (operation / "journal.json").read_bytes()
    with pytest.raises(TypeError):
        tx.apply(root, None, [], [], ".nexus-launcher/pack.json", {})
    assert (operation / "journal.json").read_bytes() == journal
    assert_old(root)


def test_none_records_are_not_treated_as_empty_inventory(tmp_path, backend):
    root, stage, _ = generation(tmp_path)
    with pytest.raises(TypeError):
        tx.apply(root, stage, None, [], ".nexus-launcher/pack.json", {})
    assert_old(root)
    assert not (root / tx.OPERATION).exists()


def test_orphan_without_journal_is_cleaned(tmp_path, backend):
    root, _, _ = generation(tmp_path)
    operation = root / tx.OPERATION
    operation.mkdir()
    (operation / "partial").write_bytes(b"partial")
    tx.recover(root)
    assert_old(root)
    assert not operation.exists()


def test_interruption_keeps_prepared_journal_for_later_recovery(tmp_path, backend, monkeypatch):
    root, stage, record = generation(tmp_path)

    def interruption(phase):
        if phase == "prepared":
            raise KeyboardInterrupt("synthetic interruption")

    monkeypatch.setattr(tx, "checkpoint", interruption)
    with pytest.raises(KeyboardInterrupt):
        tx.apply(root, stage, [record], [], ".nexus-launcher/pack.json", {})
    assert json.loads((root / tx.OPERATION / "journal.json").read_text())["phase"] == "prepared"
    assert_old(root)
    tx.recover(root)
    assert not (root / tx.OPERATION).exists()


def test_recovery_failure_retains_journal_and_original_error_context(tmp_path, backend, monkeypatch):
    root, stage, record = generation(tmp_path)
    original = tx.atomic_copy

    def copying(source, destination, **kwargs):
        if source == stage / "mods/a.jar":
            (root / tx.OPERATION / "backup/1").write_bytes(b"corrupt")
            raise OSError("synthetic replacement failure")
        return original(source, destination, **kwargs)

    monkeypatch.setattr(tx, "atomic_copy", copying)
    with pytest.raises(ValueError, match="Corrupt transaction backup") as failure:
        tx.apply(root, stage, [record], [], ".nexus-launcher/pack.json", {})
    assert isinstance(failure.value.__context__, OSError)
    assert str(failure.value.__context__) == "synthetic replacement failure"
    assert json.loads((root / tx.OPERATION / "journal.json").read_text())["phase"] == "prepared"
    assert_old(root)


def test_incompatible_api_and_native_failure_do_not_fall_back(tmp_path, monkeypatch):
    import types
    from unittest.mock import Mock
    fallback = Mock()
    monkeypatch.setattr(tx, "_recover_python", fallback)
    monkeypatch.setattr(tx, "_native", types.SimpleNamespace(TRANSACTION_API_VERSION=999))
    with pytest.raises(ImportError):
        tx.recover(tmp_path)
    core = types.SimpleNamespace(TRANSACTION_API_VERSION=1,
                                 transaction_recover=Mock(side_effect=OSError("native failure")))
    monkeypatch.setattr(tx, "_native", core)
    with pytest.raises(OSError, match="native failure"):
        tx.recover(tmp_path)
    fallback.assert_not_called()


def test_older_extension_without_transaction_api_keeps_python_path(tmp_path, monkeypatch):
    import types
    from unittest.mock import Mock
    fallback = Mock()
    monkeypatch.setattr(tx, "_recover_python", fallback)
    monkeypatch.setattr(tx, "_native", types.SimpleNamespace(CORE_API_VERSION=1))
    tx.recover(tmp_path)
    fallback.assert_called_once_with(tmp_path)
