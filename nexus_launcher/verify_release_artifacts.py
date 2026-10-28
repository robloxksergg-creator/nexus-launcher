"""Isolated local installer-component checks using the built, real payload."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from nexus_launcher.release_metadata import CURRENT_VERSION


def main():
    root = Path(__file__).resolve().parents[2] / "work" / f"release-{CURRENT_VERSION}-candidate"
    metadata = json.loads((root / "manifest.draft.json").read_text(encoding="utf-8"))
    sandbox = Path(tempfile.mkdtemp(prefix="artifact-check-", dir=root))
    results = []
    old = root / "NexusLauncher-0.9.23.reference.exe"
    old_hash = "0b3056fa9729efe6899761f74d565a0594245563852e343d6d9c9725f28baf39"
    with old.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == old_hash
    for scenario in ("clean", "real-0.9.23"):
        directory = sandbox / scenario
        directory.mkdir()
        config = directory / "launcher.json"
        saved = b'{"java_path":"C:/Java/bin/java.exe","install_root":"D:/packs","memory":4096}'
        config.write_bytes(saved)
        if scenario != "clean":
            shutil.copyfile(old, directory / "NexusLauncher.exe")
        environment = dict(
            os.environ,
            APPDATA=str(directory),
            LOCALAPPDATA=str(directory),
            NEXUS_DISABLE_SELF_UPDATE="1",
            QT_QPA_PLATFORM="offscreen",
        )
        subprocess.run(
            [str(root / "NexusSetup.exe"), "--install-dir", str(directory)], env=environment, timeout=120, check=True
        )
        installed = directory / "NexusLauncher.exe"
        with installed.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == metadata["sha256"]
        if scenario != "clean":
            backups = list(directory.glob("nexus-setup-*/previous.exe"))
            assert len(backups) == 1
            with backups[0].open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == old_hash
        process = subprocess.run([str(installed), "--smoke-test"], env=environment, timeout=30, check=True)
        assert config.read_bytes() == saved
        results.append({"scenario": scenario, "smoke_exit": process.returncode, "config_preserved": True})
    report = {
        "version": CURRENT_VERSION,
        "sha256": metadata["sha256"],
        "checks": results,
        "limitations": (
            "Real Setup EXE replaced the hash-verified published 0.9.23 EXE; new EXE smoke-tested. "
            "Old EXE not launched (no isolated account backend); no 0.9.23 self-update support. "
            "GUI wizard, account/game login and power-loss end-to-end not tested."
        ),
    }
    (root / "artifact-checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
