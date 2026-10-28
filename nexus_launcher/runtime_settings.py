"""Validation shared by settings and launches; never migrates existing instances."""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from nexus_launcher.process_utils import hidden_process_kwargs
from nexus_launcher.resource_limits import ensure_space
from nexus_launcher.safe_paths import checked_path


def required_java(minecraft: str, override: int = 0) -> int:
    if override:
        if type(override) is not int or not 8 <= override <= 99:
            raise ValueError("Некорректная требуемая версия Java")
        return override
    if not re.fullmatch(r"1\.\d+(?:\.\d+)?", minecraft):
        raise ValueError("Для этой версии Minecraft укажите java_major в профиле сборки")
    version = tuple(map(int, minecraft.split(".")))
    if version >= (1, 20, 5):
        return 21
    if version >= (1, 18):
        return 17
    if version >= (1, 17):
        return 16
    return 8


def validate_java(value: str, major: int = 0) -> str:
    path = Path(value)
    if path.name.lower() == "javaw.exe":
        path = path.with_name("java.exe")
    if not path.is_absolute() or not path.is_file():
        raise ValueError(
            "Выбранная Java не найдена. Выберите существующий java.exe/java или включите автоматический выбор."
        )
    if path.name.lower() not in {"java", "java.exe"}:
        raise ValueError("Выберите исполняемый файл java, а не установщик или папку.")
    try:
        result = subprocess.run(
            [str(path), "-XshowSettings:properties", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **hidden_process_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Не удалось запустить выбранную Java для проверки.") from error
    output = result.stderr + result.stdout
    match = re.search(r'version\s+"(?:1\.)?(\d+)', output)
    architecture = re.search(r"os\.arch\s*=\s*(\S+)", output)
    if result.returncode or not match or not architecture:
        raise ValueError("Выбранный файл не вернул корректные сведения Java.")
    if major and int(match[1]) != major:
        raise ValueError(f"Для сборки нужна Java {major}; выбрана Java {match[1]}.")
    if architecture[1].lower() not in {"amd64", "x86_64", "aarch64", "arm64"}:
        raise ValueError("Нужна 64-битная Java для игровых сборок NEXUS.")
    return str(path)


def validate_storage(value: str) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("Укажите полный путь к папке сборок.")
    # Do not silently fall back to another disk when the selected disk is offline.
    if not Path(root.anchor).exists():
        raise OSError("Диск с папкой сборок недоступен.")
    checked_path(root, "instances")
    root.mkdir(parents=True, exist_ok=True)
    ensure_space(root, 0)
    fd, name = tempfile.mkstemp(prefix="nexus-write-check-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"NEXUS")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        checked_path(root, Path(name).name).unlink(missing_ok=True)
    for name in ("instances", "user-instances"):
        checked_path(root, name).mkdir(exist_ok=True)
    return root
