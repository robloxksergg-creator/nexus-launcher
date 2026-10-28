import base64
import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nexus_launcher.portable_package import verify_portable_archive, verify_portable_inventory
from nexus_launcher.signed_release import METADATA, canonical


def fixture(files=None):
    files = files if files is not None else {"launcher.exe": b"fixture-not-executable", "_internal/runtime.dll": b"fixture"}
    key = Ed25519PrivateKey.generate()
    now = datetime.now(UTC)
    payload = {"format": "nexus-portable-zip-v1", "version": "99.0.0", "entrypoint": "launcher.exe",
               "channel": METADATA["channel"], "published_at": (now-timedelta(minutes=1)).isoformat(),
               "expires_at": (now+timedelta(hours=1)).isoformat(),
               "files": [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                         for name, data in files.items()]}
    envelope = {"schema": 2, "key_id": "fixture", "release": payload,
                "signature": base64.b64encode(key.sign(canonical(payload))).decode()}
    keys = {"fixture": key.public_key().public_bytes_raw().hex()}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    archive.seek(0)
    return archive, envelope, keys, key


def resign(envelope, key):
    envelope["signature"] = base64.b64encode(key.sign(canonical(envelope["release"]))).decode()


def test_complete_package_verifies_without_extraction():
    archive, envelope, keys, _ = fixture()
    result = verify_portable_archive(archive, envelope, keys=keys)
    assert result.entrypoint == "launcher.exe"
    assert len(result.files) == 2


def test_unsigned_or_modified_inventory_is_rejected():
    archive, envelope, keys, _ = fixture()
    envelope["release"]["files"][0]["sha256"] = "a" * 64
    with pytest.raises(ValueError, match="Подпись"):
        verify_portable_archive(archive, envelope, keys=keys)
    with pytest.raises(ValueError):
        verify_portable_inventory(None, keys=keys)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "a\\b", "data/session.json",
                                  "updates/pending.exe", "CON", "trailing."])
def test_even_signed_unsafe_paths_are_rejected(name):
    _, envelope, keys, key = fixture()
    envelope["release"]["files"].append({"path": name, "size": 0, "sha256": hashlib.sha256(b"").hexdigest()})
    resign(envelope, key)
    with pytest.raises(ValueError):
        verify_portable_inventory(envelope, keys=keys)


@pytest.mark.parametrize("change", ["duplicate-case", "bool-size", "missing-runtime", "unknown-format", "expired"])
def test_signed_invalid_contract_is_rejected(change):
    _, envelope, keys, key = fixture()
    p = envelope["release"]
    if change == "duplicate-case":
        p["files"].append({**p["files"][0], "path": "LAUNCHER.EXE"})
    elif change == "bool-size":
        p["files"][0]["size"] = True
    elif change == "missing-runtime":
        p["files"] = p["files"][:1]
    elif change == "unknown-format":
        p["format"] = "exe-only"
    else:
        p["expires_at"] = (datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    resign(envelope, key)
    with pytest.raises(ValueError):
        verify_portable_inventory(envelope, keys=keys)


@pytest.mark.parametrize("change", ["extra", "tamper", "link"])
def test_archive_bytes_or_unexpected_member_are_rejected(change):
    _, envelope, keys, _ = fixture()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("launcher.exe", b"fixture-not-executable")
        if change == "link":
            entry = zipfile.ZipInfo("_internal/runtime.dll")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            z.writestr(entry, b"fixture")
        else:
            z.writestr("_internal/runtime.dll", b"changed" if change == "tamper" else b"fixture")
        if change == "extra":
            z.writestr("extra.txt", b"unexpected")
    output.seek(0)
    with pytest.raises(ValueError):
        verify_portable_archive(output, envelope, keys=keys)


def test_signed_file_directory_collision_is_rejected():
    _, envelope, keys, key = fixture()
    envelope["release"]["files"].append({"path": "_INTERNAL", "size": 0,
                                       "sha256": hashlib.sha256(b"").hexdigest()})
    resign(envelope, key)
    with pytest.raises(ValueError, match="parent directory"):
        verify_portable_inventory(envelope, keys=keys)


def test_signed_expanded_size_budget_is_enforced():
    from nexus_launcher.portable_package import MAX_TOTAL_BYTES

    _, envelope, keys, key = fixture()
    envelope["release"]["files"][0]["size"] = MAX_TOTAL_BYTES
    resign(envelope, key)
    with pytest.raises(ValueError, match="oversized"):
        verify_portable_inventory(envelope, keys=keys)


def staged_fixture(tmp_path):
    archive, envelope, keys, _ = fixture()
    source = tmp_path / "candidate.zip"
    source.write_bytes(archive.getvalue())
    root = tmp_path / "staging"
    root.mkdir()
    return source, envelope, keys, root


def test_staging_prepares_complete_inactive_slot_and_preserves_other_versions(tmp_path):
    from nexus_launcher.portable_package import stage_portable_archive, verify_staged_portable

    source, envelope, keys, root = staged_fixture(tmp_path)
    old = tmp_path / "working.exe"
    old.write_bytes(b"unchanged working fixture")
    first = stage_portable_archive(source, envelope, root, keys=keys)
    second = stage_portable_archive(source, envelope, root, keys=keys)
    assert first != second
    assert verify_staged_portable(first, keys=keys).entrypoint == "launcher.exe"
    assert verify_staged_portable(second, keys=keys).version == "99.0.0"
    assert (first / "files/_internal/runtime.dll").read_bytes() == b"fixture"
    assert old.read_bytes() == b"unchanged working fixture"


@pytest.mark.parametrize("point", ["space", "copy", "receipt"])
def test_staging_failure_never_marks_ready(tmp_path, monkeypatch, point):
    import json
    import nexus_launcher.resource_limits as resource_limits
    import nexus_launcher.user_instances as user_instances
    from nexus_launcher.portable_package import stage_portable_archive, verify_staged_portable

    source, envelope, keys, root = staged_fixture(tmp_path)
    if point == "space":
        monkeypatch.setattr(resource_limits, "ensure_space", lambda *a: (_ for _ in ()).throw(OSError("fixture no space")))
    elif point == "copy":
        monkeypatch.setattr(resource_limits, "copy_limited", lambda *a, **k: (_ for _ in ()).throw(OSError("fixture write interrupted")))
    else:
        original = user_instances.atomic_json
        def fail_receipt(path, data):
            if data.get("phase") == "READY":
                raise OSError("fixture receipt interrupted")
            return original(path, data)
        monkeypatch.setattr(user_instances, "atomic_json", fail_receipt)
    with pytest.raises(OSError):
        stage_portable_archive(source, envelope, root, keys=keys)
    for slot in root.iterdir():
        assert json.loads((slot / "journal.json").read_text())["phase"] == "PREPARING"
        with pytest.raises(ValueError, match="not ready"):
            verify_staged_portable(slot, keys=keys)
    assert source.exists()


@pytest.mark.parametrize("change", ["tamper", "extra", "missing", "fake-receipt"])
def test_staged_slot_revalidated_before_future_activation(tmp_path, change):
    import json
    from nexus_launcher.portable_package import stage_portable_archive, verify_staged_portable

    source, envelope, keys, root = staged_fixture(tmp_path)
    slot = stage_portable_archive(source, envelope, root, keys=keys)
    target = slot / "files/_internal/runtime.dll"
    if change == "tamper":
        target.write_bytes(b"tampered")
    elif change == "extra":
        (slot / "files/extra.exe").write_bytes(b"unexpected")
    elif change == "missing":
        target.unlink()
    else:
        (slot / "journal.json").write_text(json.dumps({"schema": 1, "phase": "READY", "trusted": True}))
    with pytest.raises(ValueError):
        verify_staged_portable(slot, keys=keys)


def test_corrupt_archive_fails_before_creating_slot(tmp_path):
    from nexus_launcher.portable_package import stage_portable_archive

    source, envelope, keys, root = staged_fixture(tmp_path)
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("launcher.exe", b"fixture-not-executable")
        z.writestr("_internal/runtime.dll", b"changed")
    with pytest.raises(ValueError):
        stage_portable_archive(source, envelope, root, keys=keys)
    assert list(root.iterdir()) == []


def test_mutation_during_staging_cannot_get_ready_receipt(tmp_path, monkeypatch):
    import json
    import nexus_launcher.resource_limits as resource_limits
    from nexus_launcher.portable_package import stage_portable_archive

    source, envelope, keys, root = staged_fixture(tmp_path)
    original = resource_limits.copy_limited
    calls = []
    def copy_then_tamper(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            slot = next(root.iterdir())
            (slot / "files/launcher.exe").write_bytes(b"X" * len(b"fixture-not-executable"))
        return result
    monkeypatch.setattr(resource_limits, "copy_limited", copy_then_tamper)
    with pytest.raises(ValueError, match="integrity"):
        stage_portable_archive(source, envelope, root, keys=keys)
    assert json.loads((next(root.iterdir()) / "journal.json").read_text())["phase"] == "PREPARING"
