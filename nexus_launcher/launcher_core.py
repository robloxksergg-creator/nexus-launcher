from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

import minecraft_launcher_lib
from nexus_launcher.platform_support import find_java
from nexus_launcher.release_metadata import CURRENT_VERSION
from nexus_launcher.runtime_settings import required_java, validate_java

NEOFORGE_VERSION = "21.1.235"
Log = Callable[[str], None]
Progress = Callable[[int, int], None]

# minecraft-launcher-lib 8.0 installs Mojang's JVM even when executablePath
# points to a validated local Java. Scope the override to this preparation
# context, including nested Forge/NeoForge/Fabric vanilla installations.
_external_java = ContextVar("nexus_external_java", default=False)
_install_bundled_java = minecraft_launcher_lib.install.install_jvm_runtime


def _install_runtime_if_needed(*args, **kwargs):
    if not _external_java.get():
        return _install_bundled_java(*args, **kwargs)


minecraft_launcher_lib.install.install_jvm_runtime = _install_runtime_if_needed


def _with_external_java(method):
    @wraps(method)
    def prepare(self, *args, **kwargs):
        # Never suppress the fallback JVM unless a working Java 21 is verified.
        self._java()
        token = _external_java.set(True)
        try:
            return method(self, *args, **kwargs)
        finally:
            _external_java.reset(token)

    return prepare


def valid_username(value: str) -> bool:
    from nexus_launcher.process_utils import launch_username_valid
    return launch_username_valid(value)


def offline_uuid(username: str) -> str:
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode(), usedforsecurity=False).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def java_major(java: str) -> int:
    result = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=10, **hidden_process_kwargs())
    match = re.search(r'version "(?:1\.)?(\d+)', result.stderr or result.stdout)
    if result.returncode or not match:
        raise RuntimeError("Не удалось определить версию Java")
    return int(match.group(1))


class MinecraftLauncher:
    def __init__(self, game_dir: Path, log: Log = print, progress: Progress = lambda *_: None):
        self.game_dir = game_dir.resolve()
        self.log = log
        self.progress = progress
        self._maximum = 1
        self._current = 0
        self._preferred_java = ""
        self._required_java = 21

    def _java(self, windowed: bool = False, preferred: str = "") -> str:
        java = preferred.strip() or self._preferred_java or find_java(self._required_java)
        if not java:
            raise RuntimeError(f"Java не найдена. Для сборки требуется Java {self._required_java} x64.")
        java = validate_java(java, self._required_java)
        executable = str(Path(java).with_name("javaw.exe")) if windowed and os.name == "nt" else java
        if windowed and os.name == "nt" and not Path(executable).is_file():
            executable = java
        self.log(f"Java {self._required_java} найдена ({executable})")
        return executable

    def _callback(self) -> dict:
        def set_status(value: str) -> None:
            if value == "Install java runtime" and _external_java.get():
                value = "Используется установленная Java 21 — загрузка Java не требуется"
            self.log(str(value))

        def set_max(value: int) -> None:
            self._maximum = max(1, int(value))
            self.progress(self._current, self._maximum)

        def set_progress(value: int) -> None:
            self._current = int(value)
            self.progress(self._current, self._maximum)

        return {"setStatus": set_status, "setMax": set_max, "setProgress": set_progress}

    def available_versions(self, limit: int = 100) -> list[str]:
        versions = minecraft_launcher_lib.utils.get_version_list()
        return [entry["id"] for entry in versions if entry["type"] == "release"][:limit]

    @_with_external_java
    def install(self, version: str) -> dict:
        self.game_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"Подготовка Minecraft {version}…")
        minecraft_launcher_lib.install.install_minecraft_version(version, str(self.game_dir), callback=self._callback())
        metadata = self.game_dir / "versions" / version / f"{version}.json"
        return json.loads(metadata.read_text(encoding="utf-8"))

    def ensure_neoforge(self, minecraft_version: str = "1.21.1", neoforge_version: str = NEOFORGE_VERSION) -> str:
        java = self._java()
        loader = minecraft_launcher_lib.mod_loader.get_mod_loader("neoforge")
        installed = loader.get_installed_version(minecraft_version, neoforge_version)
        profile = self.game_dir / "versions" / installed / f"{installed}.json"
        if not profile.is_file():
            self.log(f"Установка NeoForge {neoforge_version}…")
            installed = self._install_loader(
                loader,
                minecraft_version,
                str(self.game_dir),
                loader_version=neoforge_version,
                callback=self._callback(),
                java=java,
            )
        return installed

    def ensure_fabric(self, minecraft_version: str, loader_version: str) -> str:
        loader = minecraft_launcher_lib.mod_loader.get_mod_loader("fabric")
        installed = loader.get_installed_version(minecraft_version, loader_version)
        profile = self.game_dir / "versions" / installed / f"{installed}.json"
        if profile.is_file():
            self.log(f"Fabric {loader_version} уже установлен")
            return installed
        self.log(f"Устанавливаю Fabric {loader_version}…")
        return self._install_loader(
            loader,
            minecraft_version,
            str(self.game_dir),
            loader_version=loader_version or None,
            callback=self._callback(),
            java=self._java(),
        )

    def ensure_forge(self, minecraft_version: str, loader_version: str) -> str:
        loader = minecraft_launcher_lib.mod_loader.get_mod_loader("forge")
        installed = loader.get_installed_version(minecraft_version, loader_version)
        profile = self.game_dir / "versions" / installed / f"{installed}.json"
        if profile.is_file():
            self.log(f"Forge {loader_version} уже установлен")
            return installed
        self.log(f"Устанавливаю Forge {loader_version}…")
        return self._install_loader(
            loader,
            minecraft_version,
            str(self.game_dir),
            loader_version=loader_version or None,
            callback=self._callback(),
            java=self._java(),
        )

    @_with_external_java
    def _install_loader(self, loader, *args, **kwargs):
        return loader.install(*args, **kwargs)

    def _merge_profile(self, base: dict, child: dict) -> dict:
        merged = dict(base)
        merged.update({key: value for key, value in child.items() if key not in {"libraries", "arguments"}})
        merged["libraries"] = base.get("libraries", []) + child.get("libraries", [])
        merged["arguments"] = {
            "jvm": base.get("arguments", {}).get("jvm", []) + child.get("arguments", {}).get("jvm", []),
            "game": base.get("arguments", {}).get("game", []) + child.get("arguments", {}).get("game", []),
        }
        return merged

    def launch(
        self,
        version: str,
        username: str,
        memory_mb: int,
        server: str = "",
        loader: str = "neoforge",
        loader_version: str = NEOFORGE_VERSION,
        java_path: str = "",
        min_memory_mb: int = 1024,
        jvm_args: list[str] | None = None,
        game_ticket: str = "",
        java_required_major: int = 0,
        resolution_width: int = 0,
        resolution_height: int = 0,
        ticket_supplier: Callable[[], str] | None = None,
    ) -> subprocess.Popen:
        if not valid_username(username):
            raise ValueError("Ник: 3–16 символов, только латиница, цифры и _")
        if (resolution_width or resolution_height) and (type(resolution_width) is not int or type(resolution_height) is not int or not (320 <= resolution_width <= 7680 and 240 <= resolution_height <= 4320)):
            raise ValueError("Недопустимое разрешение игры")
        self._preferred_java = java_path.strip()
        self._required_java = required_java(version, java_required_major)
        java = self._java(windowed=True, preferred=java_path)
        self.install(version)
        if loader == "neoforge":
            launch_version = self.ensure_neoforge(version, loader_version)
        elif loader == "fabric":
            launch_version = self.ensure_fabric(version, loader_version)
        elif loader == "forge":
            launch_version = self.ensure_forge(version, loader_version)
        elif loader == "vanilla":
            launch_version = version
        else:
            raise ValueError(f"Неизвестный загрузчик: {loader}")
        options: dict = {
            "username": username,
            "uuid": offline_uuid(username).replace("-", ""),
            "token": "0",
            "executablePath": java,
            "jvmArguments": [
                f"-Xms{int(min_memory_mb)}M",
                f"-Xmx{int(memory_mb)}M",
                "-Dfile.encoding=UTF-8",
                *(jvm_args or []),
            ],
            "launcherName": "NEXUS Launcher",
            "launcherVersion": CURRENT_VERSION,
            "gameDirectory": str(self.game_dir),
            "enableLoggingConfig": True,
        }
        if resolution_width or resolution_height:
            options.update(customResolution=True, resolutionWidth=str(resolution_width), resolutionHeight=str(resolution_height))
        if server.strip():
            host, separator, port = server.strip().partition(":")
            options["server"] = host
            if separator and port:
                options["port"] = port
        from nexus_launcher.native_minecraft import get_minecraft_command
        command = get_minecraft_command(launch_version, str(self.game_dir), options)
        # Obtain the short-lived credential only after all installation work.
        if ticket_supplier is not None:
            game_ticket = ticket_supplier()
            if not isinstance(game_ticket, str) or not re.fullmatch(r"[a-f0-9]{64}", game_ticket):
                raise PermissionError("Сервер не выдал действительный игровой пропуск.")
        logs = self.game_dir / ".nexus-launcher" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        output = (logs / "minecraft-launch.log").open("a", encoding="utf-8")
        self.log(f"Запуск Minecraft {version}, {loader} {loader_version}…")
        from nexus_launcher.process_utils import redact_launch_command
        safe_command = redact_launch_command(command)
        self.log("Команда Java: " + " ".join(safe_command))
        from nexus_launcher.process_utils import game_environment
        clean_environment = game_environment(os.environ, game_ticket)
        process = subprocess.Popen(
            command,
            cwd=self.game_dir,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            env=clean_environment,
            **hidden_process_kwargs(),
        )
        process._nexus_log_handle = output  # type: ignore[attr-defined]
        return process
from nexus_launcher.process_utils import hidden_process_kwargs
