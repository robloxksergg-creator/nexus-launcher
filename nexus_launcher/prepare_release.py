"""Build local candidate artifacts only. No credentials, uploads or deployment."""

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    release = json.loads((root / "assets/release.json").read_text(encoding="utf-8"))
    version = release["version"]
    output = root.parent / "work" / f"release-{version}-candidate"
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(output),
            "--workpath",
            str(output / "build-launcher"),
            str(root / "packaging" / "specs" / "NexusLauncher.spec"),
        ],
        cwd=root,
        check=True,
    )
    executable = output / "NexusLauncher.exe"
    payload_metadata = {"version": version, "sha256": sha256(executable), "size": executable.stat().st_size}
    write_json(output / "installer-payload.json", payload_metadata)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--windowed",
            "--name",
            "NexusSetup",
            "--distpath",
            str(output),
            "--workpath",
            str(output / "build-installer"),
            "--specpath",
            str(output),
            "--paths",
            str(root),
            "--version-file",
            str(root / "packaging" / "metadata" / "version_info.txt"),
            "--add-data",
            f"{executable};.",
            "--add-data",
            f"{output / 'installer-payload.json'};.",
            str(root / "nexus_launcher" / "installer_main.py"),
        ],
        cwd=root,
        check=True,
    )
    archive = output / f"NEXUS-Launcher-v{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.write(executable, "NexusLauncher.exe")
    candidate = {
        **release,
        **payload_metadata,
        "available": False,
        "published_at": None,
        "url": f"https://nexusmc.flux-productions.com/api/launcher/download/NexusLauncher-{version}.exe",
        "zip": {"file": archive.name, "size": archive.stat().st_size, "sha256": sha256(archive)},
        "installer": {
            "file": "NexusSetup.exe",
            "size": (output / "NexusSetup.exe").stat().st_size,
            "sha256": sha256(output / "NexusSetup.exe"),
        },
        "migration": (
            "Пользователям 0.9.23 нужна одна ручная установка. "
            "Автообновления следующих версий требуют настройки ключа подписи перед публикацией."
        ),
        "notes": [
            "Выбор Java и папки сборок",
            "Проверка загружаемых файлов",
            "Улучшения входа и восстановления пароля",
            "Подготовка подписанных автообновлений с резервной копией",
        ],
    }
    write_json(output / "manifest.draft.json", candidate)
    write_json(root.parent / "website_NexusMC/app/launcher-candidate.json", candidate)
    print(json.dumps({"directory": str(output), **payload_metadata}))


if __name__ == "__main__":
    main()
