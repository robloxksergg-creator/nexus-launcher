from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from nexus_launcher.projects import canonical_server_id

CONFIG_VERSION = 2


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("Не удалось прочитать настройки. Исходный файл сохранён; восстановите его из резервной копии.") from error
    if not isinstance(value, dict):
        raise ValueError("Настройки должны содержать JSON-объект. Исходный файл не изменён.")
    return value


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name, suffix=".part", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def migrate_private_config(path: Path, official_world_ids: list[str]) -> dict:
    """Add platform state without renaming or removing any legacy setting."""
    config = _read(path)
    old_version = config.get("configVersion", 1)
    if type(old_version) is not int or old_version < 1:
        raise ValueError("Некорректная версия настроек. Исходный файл не изменён.")
    if old_version > CONFIG_VERSION:
        raise ValueError(f"Конфигурация версии {old_version} новее поддерживаемой {CONFIG_VERSION}")
    if old_version < CONFIG_VERSION and path.is_file():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.stem}.v{old_version}.{stamp}.backup.json")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    config.setdefault("pinnedWorlds", list(dict.fromkeys(official_world_ids)))
    config.setdefault("recentWorlds", [])
    config.setdefault("selectedWorld", official_world_ids[0] if official_world_ids else "")
    config.setdefault("videoMuted", True)
    config.setdefault("videoBackgrounds", True)
    config.setdefault("reducedMotion", False)
    config.setdefault("creatorMode", False)
    config.setdefault("backupRetention", 5)
    developer = config.setdefault("developer", {})
    if not isinstance(developer, dict):
        developer = {}
        config["developer"] = developer
    developer.setdefault("showPerformanceOverlay", False)
    config.setdefault("launcherAfterLaunch", "keep_open")
    config.setdefault("worldsFeedUrl", "")
    config["configVersion"] = CONFIG_VERSION
    atomic_write(path, config)
    return config



def canonical_world_preferences(config: dict) -> dict:
    """Project known world aliases in memory; never open or write a config file."""
    result = dict(config)
    if isinstance(result.get("selectedWorld"), str):
        result["selectedWorld"] = canonical_server_id(result["selectedWorld"])
    for key in ("pinnedWorlds", "recentWorlds"):
        if isinstance(result.get(key), list):
            values, seen = [], set()
            for value in result[key]:
                if isinstance(value, str):
                    value = canonical_server_id(value)
                    if value in seen:
                        continue
                    seen.add(value)
                values.append(value)
            result[key] = values
    return result


def remember_world(config: dict, world_id: str, limit: int = 8) -> None:
    config.update(canonical_world_preferences(config))
    world_id = canonical_server_id(world_id)
    recent = [item for item in config.get("recentWorlds", []) if isinstance(item, str) and item != world_id]
    config["recentWorlds"] = [world_id, *recent][:limit]
    config["selectedWorld"] = world_id
