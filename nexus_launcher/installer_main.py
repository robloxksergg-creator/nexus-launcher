"""Manual bootstrap installer. No registry/keyring/config/instance deletion."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from nexus_launcher.resource_limits import ensure_space
from nexus_launcher.safe_paths import atomic_copy, checked_path, replace_file


def install_payload(payload: Path, directory: Path, sha256: str) -> Path:
    if not directory.is_absolute():
        raise ValueError("Выберите полный путь установки")
    target = checked_path(directory, "NexusLauncher.exe")
    with payload.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != sha256:
            raise ValueError("Установщик повреждён: SHA-256 не совпадает")
    directory.mkdir(parents=True, exist_ok=True)
    ensure_space(directory, payload.stat().st_size * 2)
    operation = Path(tempfile.mkdtemp(prefix="nexus-setup-", dir=directory))
    stage = checked_path(operation, "new.exe")
    if target.exists():
        atomic_copy(target, checked_path(operation, "previous.exe"))
    atomic_copy(payload, stage, expected_sha256=sha256)
    target = checked_path(directory, target.name)
    replace_file(stage, target, expected_sha256=sha256)
    # Keep previous.exe for recovery. Never recursively clean an installation.
    return target


def main():
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("NEXUS Setup")
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    metadata = json.loads((root / "installer-payload.json").read_text(encoding="utf-8"))
    if "--smoke-test" in sys.argv:
        with (root / "NexusLauncher.exe").open("rb") as source:
            return 0 if hashlib.file_digest(source, "sha256").hexdigest() == metadata["sha256"] else 2
    if "--install-dir" in sys.argv:
        parser = argparse.ArgumentParser(description="Install the bundled launcher in an explicit directory")
        parser.add_argument("--install-dir", required=True, type=Path)
        args = parser.parse_args()
        try:
            install_payload(root / "NexusLauncher.exe", args.install_dir, metadata["sha256"])
        except (OSError, ValueError):
            return 1
        return 0
    directory = QFileDialog.getExistingDirectory(
        None,
        f"Установка NEXUS {metadata['version']}: выберите папку",
        str(Path(os.environ.get("LOCALAPPDATA", Path.home()))),
    )
    if not directory:
        return 0
    try:
        target = install_payload(root / "NexusLauncher.exe", Path(directory), metadata["sha256"])
    except (OSError, ValueError) as error:
        QMessageBox.critical(
            None,
            "Установка не выполнена",
            f"{error}\nЗакройте лаунчер и повторите установку. Данные сборок не удалялись.",
        )
        return 1
    QMessageBox.information(None, "NEXUS установлен", f"Запустите {target}\nАккаунт, настройки и сборки сохранены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
