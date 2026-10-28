"""Local-only compiled helper -> next compiled launcher acceptance test.

Never uploads artifacts. Uses an isolated app-data directory and null keyring.
The test-only next release must not be published.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from nexus_launcher.launcher_update_job import digest, start_update
from nexus_launcher.release_metadata import METADATA
from nexus_launcher.signed_release import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidate = root.parent / "work/release-0.9.24-candidate"
    sandbox = Path(tempfile.mkdtemp(prefix="frozen-update-", dir=root.parent / "work"))
    source = sandbox / "source"
    source.mkdir()
    shutil.copytree(root / "nexus_launcher", source / "nexus_launcher")
    shutil.copytree(root / "packaging", source / "packaging")
    shutil.copytree(root / "assets", source / "assets")
    metadata = {**METADATA, "version": "0.9.25", "status": "LOCAL-TEST-ONLY-DO-NOT-PUBLISH"}
    (source / "assets/release.json").write_text(json.dumps(metadata), encoding="utf-8")
    with (sandbox / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--distpath",
                str(sandbox / "next"),
                "--workpath",
                str(sandbox / "build"),
                str(source / "packaging" / "specs" / "NexusLauncher.spec"),
            ],
            cwd=source,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=600,
        )
    binary = sandbox / "next/NexusLauncher.exe"
    key = load_pem_private_key(args.private_key.read_bytes(), password=None)
    key_id = "nexus-launcher-updates-2026-01"
    assert key.public_key().public_bytes_raw().hex() == METADATA["trusted_update_keys"][key_id]
    now = datetime.now(UTC)
    payload = {
        "version": "0.9.25",
        "channel": "stable",
        "platform": "windows",
        "arch": "x64",
        "url": "https://nexusmc.flux-productions.com/LOCAL-TEST-ONLY.exe",
        "sha256": digest(binary),
        "size": binary.stat().st_size,
        "available": True,
        "notes": "LOCAL TEST ONLY - DO NOT PUBLISH",
        "published_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=2)).isoformat(),
    }
    envelope = {
        "schema": 2,
        "key_id": key_id,
        "release": payload,
        "signature": base64.b64encode(key.sign(canonical(payload))).decode(),
    }
    appdata = sandbox / "appdata"
    updates = appdata / ".nexus-launcher/updates"
    operation = updates / "release-e2e"
    operation.mkdir(parents=True)
    shutil.copyfile(binary, operation / "payload.exe")
    (operation / "manifest.json").write_text(json.dumps(envelope), encoding="utf-8")
    install = sandbox / "installed"
    install.mkdir()
    target = install / "NexusLauncher.exe"
    shutil.copyfile(candidate / "NexusLauncher.exe", target)
    before = digest(target)
    config = install / "user-data-sentinel.txt"
    config.write_bytes(b"preserve user data")
    os.environ.update(
        APPDATA=str(appdata),
        LOCALAPPDATA=str(appdata),
        NEXUS_DISABLE_SELF_UPDATE="1",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        QT_QPA_PLATFORM="offscreen",
        HTTPS_PROXY="http://127.0.0.1:9",
        HTTP_PROXY="http://127.0.0.1:9",
    )
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    helper = None
    job = {}
    try:
        helper = start_update(updates, operation / "payload.exe", target, parent.pid)
        helper.wait(timeout=150)
        job = json.loads((operation / "job.json").read_text())
        assert helper.returncode == 0, f"Helper failed: {helper.returncode}, phase={job.get('phase')}"
        assert job["phase"] == "complete", job["phase"]
        assert digest(target) == payload["sha256"]
        assert digest(operation / "original.exe") == before
        assert config.read_bytes() == b"preserve user data"
        report = {
            "from": "0.9.24",
            "to": "0.9.25 (LOCAL TEST ONLY)",
            "result": "passed",
            "source_sha256": before,
            "target_sha256": digest(target),
            "health_marker": True,
            "backup_preserved": True,
            "user_data_preserved": True,
            "scope": "Real frozen helper, executable replacement and real new Launcher UI health. "
            "Payload staged locally; HTTPS transport covered separately by regressions. "
            "No real account or game login.",
        }
        (sandbox / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(sandbox / "result.json"), **report}))
    finally:
        if parent.poll() is None:
            parent.terminate()
        parent.wait(timeout=10)
        if helper is not None and helper.poll() is None:
            helper.terminate()
            helper.wait(timeout=10)
        if not job and (operation / "job.json").exists():
            job = json.loads((operation / "job.json").read_text())
        pid = job.get("launched_pid")
        if type(pid) is int and pid > 0:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15, check=False)


if __name__ == "__main__":
    main()
