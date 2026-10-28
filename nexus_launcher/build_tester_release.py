"""Local, fail-closed beta packaging. Never uploads or changes stable metadata."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import PySide6
from pathlib import Path
from urllib.parse import urlsplit


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "assets/tester-release.json").read_text(encoding="utf-8"))
    version = config["version"]
    parsed = urlsplit(config["api"])
    if (config["channel"] != "beta" or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-beta\.[0-9]+", version)
            or parsed.scheme != "https" or parsed.hostname != "nexusmc-control-plane-staging.robloxksergg.workers.dev"
            or parsed.username or parsed.query or parsed.fragment):
        raise ValueError("Missing or unsafe tester release configuration")
    output = root.parent / "tester-releases" / version
    output.mkdir(parents=True, exist_ok=True)
    assets = output / "staged-assets"
    shutil.copytree(root / "assets", assets, dirs_exist_ok=True)
    metadata = json.loads((assets / "release.json").read_text(encoding="utf-8"))
    metadata.update(version=version, channel="beta", status="private-test-candidate")
    (assets / "release.json").write_text(json.dumps(metadata), encoding="utf-8")
    info = (root / "packaging" / "metadata" / "version_info.txt").read_text(encoding="utf-8").replace("u'1.0.0'", f"u'{version}'").replace("u'NEXUS Launcher'", "u'NEXUS'").replace("u'NEXUS Launcher.exe'", "u'NexusLauncher.exe'").replace("flags=0x0", "flags=0x2")
    info = info.replace("StringStruct(u'FileDescription', u'NEXUS')", "StringStruct(u'FileDescription', u'NEXUS — open your world')")
    version_file = output / "version_info.txt"
    version_file.write_text(info, encoding="utf-8")
    environment = dict(os.environ, NEXUS_TESTER_ASSET_ROOT=str(assets), NEXUS_TESTER_VERSION_INFO=str(version_file))
    subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--distpath",str(output),"--workpath",str(output / "build-client"),str(root / "packaging" / "specs" / "NexusTester.spec")],cwd=root,env=environment,check=True)
    executable = output / "NexusLauncher.exe"
    payload = output / "installer-payload.json"
    payload.write_text(json.dumps({"version":version,"sha256":digest(executable),"size":executable.stat().st_size}),encoding="utf-8")
    qt_root = Path(PySide6.__file__).parent
    runtime_binaries = []
    for name in ("concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        path = qt_root / name
        if path.is_file():
            runtime_binaries.extend(["--add-binary", f"{path};."])
    setup_name = f"NEXUS-Setup-{version}"
    subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--onefile","--windowed","--disable-windowed-traceback","--name",setup_name,"--distpath",str(output),"--workpath",str(output / "build-setup"),"--specpath",str(output),"--paths",str(root),"--icon",str(root / "assets/icon.ico"),"--version-file",str(version_file),"--runtime-hook",str(root / "nexus_launcher" / "pyi_rth_qt_dll_path.py"),*runtime_binaries,"--add-data",f"{executable};.","--add-data",f"{payload};.",str(root / "nexus_launcher" / "installer_main.py")],cwd=root,check=True)
    portable = output / f"NEXUS-Portable-{version}.exe"
    shutil.copy2(executable, portable)
    artifacts = [portable,output / f"{setup_name}.exe"]
    manifest = {"version":version,"channel":"beta","available":False,"status":"awaiting-staging-and-mailbox-acceptance","api":config["api"],"signed":False,"artifacts":[{"file":p.name,"sha256":digest(p),"size":p.stat().st_size} for p in artifacts]}
    (output / "manifest.draft.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
