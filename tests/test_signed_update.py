import base64
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nexus_launcher.launcher_update_job import apply_update, recover_update
from nexus_launcher.platform_support import architecture_id, platform_id
from nexus_launcher.self_update import LauncherRelease, SelfUpdater
from nexus_launcher.signed_release import METADATA, canonical, verify_envelope


@pytest.mark.parametrize("marker_is_directory", [True, False])
def test_onedir_update_refused_before_job_or_helper(tmp_path, monkeypatch, marker_is_directory):
    from nexus_launcher.launcher_update_job import start_update, _start_update

    target = tmp_path / "launcher.exe"
    target.write_bytes(b"original fixture")
    marker = tmp_path / "_internal"
    if marker_is_directory:
        marker.mkdir()
        (marker / "runtime.dll").write_bytes(b"runtime fixture")
    else:
        marker.write_bytes(b"ambiguous layout")
    calls = []
    monkeypatch.setattr("nexus_launcher.launcher_update_job.subprocess.Popen", lambda *a, **k: calls.append(a))
    root = tmp_path / "updates"
    for entry in (start_update, _start_update):
        with pytest.raises(RuntimeError, match="onedir"):
            entry(root, root / "missing.exe", target, 0)
    assert calls == []
    assert not root.exists()
    assert target.read_bytes() == b"original fixture"
    if marker_is_directory:
        assert (marker / "runtime.dll").read_bytes() == b"runtime fixture"


def test_onedir_apply_refused_before_wait_or_replace(tmp_path, monkeypatch):
    from nexus_launcher.launcher_update_job import _apply_update

    target = tmp_path / "launcher.exe"
    target.write_bytes(b"original fixture")
    (tmp_path / "_internal").mkdir()
    operation = tmp_path / "updates" / "release-fixture"
    operation.mkdir(parents=True)
    job = {"target": str(target), "phase": "pending"}
    (operation / "job.json").write_text(json.dumps(job))
    calls = []
    monkeypatch.setattr("nexus_launcher.launcher_update_job.replace_file", lambda *a, **k: calls.append("replace"))
    for entry in (apply_update, _apply_update):
        with pytest.raises(RuntimeError, match="onedir"):
            entry(operation, wait=lambda *_: calls.append("wait"), launch=lambda *_: calls.append("launch"))
    assert calls == []
    assert target.read_bytes() == b"original fixture"
    assert json.loads((operation / "job.json").read_text(encoding="utf-8")) == job
    assert not (operation / "original.exe").exists()


def test_unreadable_layout_fails_closed(tmp_path, monkeypatch):
    from pathlib import Path
    from nexus_launcher.launcher_update_job import require_exe_only_layout

    def unreadable(_path):
        raise PermissionError("synthetic access refusal")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", unreadable)
        with pytest.raises(RuntimeError, match="формат"):
            require_exe_only_layout(tmp_path / "launcher.exe")


@pytest.fixture
def signed(monkeypatch):
    key = Ed25519PrivateKey.generate()  # Ephemeral test key; never production material.
    monkeypatch.setitem(METADATA, "trusted_update_keys", {"fixture": key.public_key().public_bytes_raw().hex()})

    def make(binary=b"new fixture executable", version="99.0.0"):
        now = datetime.now(UTC)
        payload = {
            "version": version,
            "url": "https://nexusmc.flux-productions.com/launcher.exe",
            "sha256": hashlib.sha256(binary).hexdigest(),
            "size": len(binary),
            "channel": "stable",
            "platform": platform_id(),
            "arch": architecture_id(),
            "minimum_supported_version": "0.9.24",
            "published_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }
        envelope = {
            "schema": 2,
            "key_id": "fixture",
            "release": payload,
            "signature": base64.b64encode(key.sign(canonical(payload))).decode(),
        }
        return LauncherRelease(
            payload["version"], payload["url"], payload["sha256"], size=len(binary), envelope=envelope
        )

    return make


def test_persistent_anti_rollback_and_equivocation(tmp_path, signed):
    from nexus_launcher.update_state import remember_release, update_lock

    newer = signed(version="99.0.1")
    with update_lock(tmp_path):
        remember_release(tmp_path, newer.envelope)
    # A fresh lock/reader simulates another process/restart.
    with update_lock(tmp_path):
        with pytest.raises(ValueError, match="Откат"):
            remember_release(tmp_path, signed(version="99.0.0").envelope)
        with pytest.raises(ValueError, match="подмена"):
            remember_release(tmp_path, signed(b"other", version="99.0.1").envelope)
        remember_release(tmp_path, newer.envelope)  # Same package retry is allowed.
    data = json.loads((tmp_path / "highest-release.json").read_text())
    data["release"]["version"] = "0.0.0"
    (tmp_path / "highest-release.json").write_text(json.dumps(data))
    with update_lock(tmp_path), pytest.raises(ValueError, match="Подпись"):
        remember_release(tmp_path, newer.envelope)


def test_concurrent_update_guard_released_on_failure(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from nexus_launcher.update_state import update_lock

    def attempt():
        try:
            with update_lock(tmp_path):
                return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        with update_lock(tmp_path):
            assert not any(pool.map(lambda _: attempt(), range(24)))
        assert pool.submit(attempt).result() is True


def test_concurrent_update_starts_only_one_helper(tmp_path, signed, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from nexus_launcher.launcher_update_job import start_update

    root = tmp_path / "updates"
    operation = root / "release-test"
    operation.mkdir(parents=True)
    payload = operation / "next.exe"
    payload.write_bytes(b"new fixture executable")
    (operation / "manifest.json").write_text(json.dumps(signed().envelope))
    executable = tmp_path / "launcher.exe"
    executable.write_bytes(b"old")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def spawn(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(5)
        return "helper"

    monkeypatch.setattr("nexus_launcher.launcher_update_job.subprocess.Popen", spawn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(start_update, root, payload, executable, 1)
        assert entered.wait(5)
        with pytest.raises(RuntimeError):
            start_update(root, payload, executable, 1)
        release.set()
        assert first.result() == "helper"
    assert len(calls) == 1
    assert executable.read_bytes() == b"old"


@pytest.mark.parametrize("point", ["prepared", "replace", "committed"])
def test_real_process_exit_and_recovery(tmp_path, signed, point):
    import os
    import subprocess
    import sys
    from pathlib import Path

    target = tmp_path / "NexusLauncher.exe"
    target.write_bytes(b"working old fixture")
    operation = tmp_path / "release-process-crash"
    operation.mkdir()
    release = signed()
    (operation / "payload.exe").write_bytes(b"new fixture executable")
    (operation / "manifest.json").write_text(json.dumps(release.envelope))
    (operation / "job.json").write_text(
        json.dumps(
            {
                "target": str(target),
                "source": "payload.exe",
                "phase": "pending",
                "parent_pid": 0,
                "existed_before": True,
                "old_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    )
    script = """
import json, os, sys
from pathlib import Path
import nexus_launcher.launcher_update_job as job
from nexus_launcher.signed_release import METADATA
METADATA["trusted_update_keys"] = json.loads(sys.argv[3])
operation, point = Path(sys.argv[1]), sys.argv[2]
original_json, original_replace = job.atomic_json, job.replace_file
def save(path, data):
    original_json(path, data)
    if path.name == "job.json" and data.get("phase") == point:
        os._exit(73)
def replace(source, target, **kwargs):
    original_replace(source, target, **kwargs)
    if point == "replace" and Path(target).suffix == ".exe":
        os._exit(73)
job.atomic_json, job.replace_file = save, replace
job.apply_update(operation, launch=lambda *_: None, wait=lambda _: None)
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    process = subprocess.run(
        [sys.executable, "-c", script, str(operation), point, json.dumps(METADATA["trusted_update_keys"])],
        env=environment,
        capture_output=True,
        timeout=20,
    )
    assert process.returncode == 73, process.stderr.decode(errors="replace")
    recover_update(operation)
    assert target.read_bytes() == b"working old fixture"
    assert json.loads((operation / "job.json").read_text(encoding="utf-8"))["phase"] == "rolled_back"


@pytest.mark.parametrize("target_is_old", [True, False])
def test_corrupt_backup_never_overwrites_surviving_executable(tmp_path, signed, target_is_old):
    operation = tmp_path / "release-corrupt-backup"
    operation.mkdir()
    target = tmp_path / "NexusLauncher.exe"
    old = b"old fixture"
    surviving = old if target_is_old else b"new fixture executable"
    target.write_bytes(surviving)
    (operation / "original.exe").write_bytes(b"corrupt backup")
    (operation / "manifest.json").write_text(json.dumps(signed().envelope))
    (operation / "job.json").write_text(
        json.dumps(
            {
                "target": str(target),
                "phase": "committed",
                "existed_before": True,
                "old_sha256": hashlib.sha256(old).hexdigest(),
            }
        )
    )
    if target_is_old:
        recover_update(operation)
    else:
        with pytest.raises(ValueError, match="Backup"):
            recover_update(operation)
    assert target.read_bytes() == surviving


def test_signed_download_and_hash_failure(tmp_path, monkeypatch, signed):
    binary = b"new fixture executable"
    release = signed(binary)

    class Reply(io.BytesIO):
        headers = {"Content-Length": str(len(binary))}

    monkeypatch.setattr("nexus_launcher.self_update.open_release_url", lambda *a, **k: Reply(binary))
    updater = SelfUpdater()
    updater.update_dir = tmp_path
    target = updater.download(release)
    assert target.read_bytes() == binary
    assert json.loads((target.parent / "manifest.json").read_text()) == release.envelope
    monkeypatch.setattr("nexus_launcher.self_update.open_release_url", lambda *a, **k: Reply(b"wrong fixture executable"))
    with pytest.raises(ValueError):
        updater.download(release)
    assert not list(tmp_path.rglob("*.part"))


def test_modified_and_unknown_signatures_rejected(signed):
    release = signed()
    release.authenticated()
    release.envelope["release"]["size"] += 1
    with pytest.raises(ValueError, match="Подпись"):
        release.authenticated()
    with pytest.raises(ValueError, match="ключа"):
        verify_envelope(signed().envelope, keys={})


def test_unpublished_signed_candidate_is_not_offered(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setitem(METADATA, "trusted_update_keys", {"fixture": key.public_key().public_bytes_raw().hex()})
    now = datetime.now(UTC)
    payload = {
        "available": False,
        "channel": "stable",
        "published_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }
    envelope = {
        "schema": 2,
        "key_id": "fixture",
        "release": payload,
        "signature": base64.b64encode(key.sign(canonical(payload))).decode(),
    }
    monkeypatch.setattr("nexus_launcher.self_update.open_release_url", lambda *a, **k: io.BytesIO(json.dumps(envelope).encode()))
    assert SelfUpdater().check() is None


@pytest.mark.parametrize("fails", [False, True])
def test_update_commit_and_rollback_preserve_data(tmp_path, signed, fails):
    binary = b"new fixture executable"
    release = signed(binary)
    operation = tmp_path / "release-fixture"
    operation.mkdir()
    target = tmp_path / "NexusLauncher.exe"
    target.write_bytes(b"original fixture")
    config = tmp_path / "launcher.json"
    config.write_bytes(b"unchanged config")
    (operation / "payload.exe").write_bytes(binary)
    (operation / "manifest.json").write_text(json.dumps(release.envelope))
    job = {
        "target": str(target),
        "source": "payload.exe",
        "old_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "parent_pid": 123,
        "phase": "pending",
        "existed_before": True,
    }
    (operation / "job.json").write_text(json.dumps(job))

    def launch(path, folder):
        assert path.read_bytes() == binary
        if fails:
            raise OSError("fixture launch failed")

    if fails:
        with pytest.raises(OSError):
            apply_update(operation, launch=launch, wait=lambda _: None)
        assert target.read_bytes() == b"original fixture"
    else:
        apply_update(operation, launch=launch, wait=lambda _: None)
        assert target.read_bytes() == binary
    assert (operation / "original.exe").read_bytes() == b"original fixture"
    assert config.read_bytes() == b"unchanged config"
    assert not list(tmp_path.glob(".nexus-*.exe"))
    assert json.loads((operation / "job.json").read_text(encoding="utf-8"))["phase"] == ("rolled_back" if fails else "complete")


@pytest.mark.parametrize("phase", ["pending", "prepared", "committed"])
def test_crash_recovery_does_not_delete_untouched_original(tmp_path, signed, phase):
    target = tmp_path / "NexusLauncher.exe"
    original = b"original fixture"
    target.write_bytes(original)
    operation = tmp_path / "release-recovery"
    operation.mkdir()
    release = signed()
    (operation / "manifest.json").write_text(json.dumps(release.envelope))
    job = {
        "target": str(target),
        "phase": phase,
        "existed_before": True,
        "old_sha256": hashlib.sha256(original).hexdigest(),
    }
    (operation / "job.json").write_text(json.dumps(job))
    if phase != "pending":
        (operation / "original.exe").write_bytes(original)
    if phase == "committed":
        target.write_bytes(b"new fixture executable")
    recover_update(operation)
    assert target.read_bytes() == original
