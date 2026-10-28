"""Opt-in demo launch: installed binaries read-only, fresh disposable game directory.

Does not install/repair versions, read accounts, load mods or open personal worlds.
This checks the client runtime only, not the install pipeline or Microsoft login.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

import minecraft_launcher_lib

from nexus_launcher.platform_support import find_java
from nexus_launcher.process_utils import hidden_process_kwargs
from nexus_launcher.runtime_settings import validate_java


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--seconds", type=int, default=45)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", args.version) or ".." in args.version:
        parser.error("Invalid installed version identifier")
    source = Path(os.environ["APPDATA"]) / ".minecraft"
    profile = source / "versions" / args.version / (args.version + ".json")
    metadata = json.loads(profile.read_text(encoding="utf-8"))
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    major = metadata.get("javaVersion", {}).get("majorVersion", 8)
    executable = find_java(major)
    if not executable:
        print(json.dumps({"version": args.version, "status": "missing_java", "required_java": major}))
        return
    executable = validate_java(executable, major)
    with tempfile.TemporaryDirectory(prefix="nexus-minecraft-smoke-") as temporary:
        root = Path(temporary)
        natives = root / "natives"
        existing = profile.parent / "natives"
        if existing.is_dir():
            shutil.copytree(existing, natives)
        else:
            natives.mkdir()
        options = minecraft_launcher_lib.utils.generate_test_options()
        options.update(
            executablePath=executable, gameDirectory=str(root), nativesDirectory=str(natives),
            demo=True, disableMultiplayer=True, disableChat=True,
            customResolution=True, resolutionWidth="960", resolutionHeight="540",
            jvmArguments=["-Xms512M", "-Xmx2048M"],
        )
        command = minecraft_launcher_lib.command.get_minecraft_command(args.version, str(source), options)
        output = root / "smoke.log"
        with output.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                       **hidden_process_kwargs())
            try:
                process.wait(timeout=max(5, min(args.seconds, 90)))
                alive = False
            except subprocess.TimeoutExpired:
                alive = True
            finally:
                if process.poll() is None:
                    process.terminate()  # Only the exact test-owned process.
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
        text = output.read_text(encoding="utf-8", errors="replace")
        after = hashlib.sha256(profile.read_bytes()).hexdigest()
        report = {
            "version": args.version, "java": major, "alive_at_timeout": alive,
            "render_thread": "Render thread" in text,
            "backend_initialized": "Backend library:" in text,
            "manifest_unchanged": before == after,
            "fatal": any(word in text for word in ("Exception in thread", "Could not find or load main class", "GLFW error")),
            "mode": "isolated demo; no install/auth test",
        }
        print(json.dumps(report))
        if not alive or report["fatal"]:
            print("\n".join(text.splitlines()[-15:]))
        assert before == after, "Installed manifest was changed"


if __name__ == "__main__":
    main()
