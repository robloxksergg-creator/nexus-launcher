from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from nexus_launcher.loader_providers import loader_provider
from nexus_launcher.safe_paths import checked_path, replace_file, remove_owned_tree

SCHEMA_VERSION = 2
INSTANCE_DIRS = (
    "mods",
    "disabled_mods",
    "config",
    "resourcepacks",
    "shaderpacks",
    "saves",
    "screenshots",
    "logs",
    ".nexus/cache/downloads",
    ".nexus/backups",
)
VALID_LOADERS = {"vanilla", "fabric", "forge", "neoforge"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def safe_filename(value: str) -> str:
    name = Path(value).name
    if name != value or name in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9._+()\- ]+", name):
        raise ValueError("Недопустимое имя файла")
    return name


def atomic_json(path: Path, data: dict) -> None:
    from nexus_launcher.safe_paths import checked_path, pinned_directory

    checked_path(path.parent, path.name)
    with pinned_directory(path.parent, create=True):
        _atomic_json(path, data)


def _atomic_json(path: Path, data: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass
class InstalledMod:
    project_id: str
    version_id: str
    name: str
    filename: str
    sha512: str
    enabled: bool = True
    required_by: list[str] = field(default_factory=list)


@dataclass
class UserInstance:
    id: str
    name: str
    minecraft_version: str
    loader: str
    loader_version: str = ""
    memory_mb: int = 4096
    min_memory_mb: int = 1024
    java_path: str = ""
    jvm_args: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    icon: str = ""
    state: str = "ready"
    installed_mods: list[InstalledMod] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    java_major: int = 0
    install_path: str = ""
    banner: str = ""
    instance_type: str = "custom"
    last_launch: str = ""
    last_exit_code: int | None = None
    last_game_duration: float | None = None
    last_test_launch: str = ""
    last_test_exit_code: int | None = None
    last_test_duration: float | None = None
    resolution_width: int = 0
    resolution_height: int = 0

    @classmethod
    def from_dict(cls, raw: dict) -> UserInstance:
        version = int(raw.get("schema_version", raw.get("schemaVersion", 1)))
        if version > SCHEMA_VERSION:
            raise ValueError(f"Схема сборки {version} новее поддерживаемой {SCHEMA_VERSION}")
        mods = [InstalledMod(**item) for item in raw.get("installed_mods", raw.get("installedMods", []))]
        data = dict(raw)
        data.pop("schemaVersion", None)
        data.pop("installedMods", None)
        if version < 2:
            data.setdefault("install_path", "")
            data.setdefault("banner", "")
            data.setdefault("instance_type", "custom")
        data["schema_version"] = SCHEMA_VERSION
        data["installed_mods"] = mods
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})


class InstanceService:
    """Owns user instances only. Official NEXUS worlds never enter this root."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def registry_path(self) -> Path:
        return self.root / "registry.json"

    def _registry(self) -> dict[str, str]:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            values = payload.get("instances", {}) if isinstance(payload, dict) else {}
            return {str(key): str(value) for key, value in values.items() if isinstance(value, str)}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_registry(self, registry: dict[str, str]) -> None:
        atomic_json(self.registry_path, {"version": 1, "instances": registry})

    def _custom_target(self, value: str | Path) -> Path:
        target = Path(value).expanduser()
        if not target.is_absolute():
            raise ValueError("Для сборки требуется полный путь к папке")
        target = target.absolute()
        anchor = Path(target.anchor)
        home = Path.home().absolute()
        system_roots: set[Path] = set()
        if os.name == "nt":
            for variable in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)"):
                if os.getenv(variable):
                    system_roots.add(Path(os.environ[variable]).absolute())
        launcher_root = Path(__file__).resolve().parents[1]
        if target in {anchor, home, self.root, launcher_root} or self.root in target.parents or target in self.root.parents or launcher_root in target.parents or target in launcher_root.parents or any(target == root or root in target.parents for root in system_roots):
            raise ValueError("Нельзя использовать системную или домашнюю папку целиком")
        target.parent.mkdir(parents=True, exist_ok=True)
        checked_path(target.parent, target.name)
        return target

    def _ensure_no_instance_overlap(self, target: Path, exclude_id=""):
        for identifier, registered in self._registry().items():
            if identifier == exclude_id: continue
            other = Path(registered).absolute()
            if target == other or target in other.parents or other in target.parents:
                raise ValueError("Папка не должна совпадать или пересекаться с другой сборкой")

    def path_for(self, instance_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f\-]{36}", instance_id):
            raise ValueError("Некорректный ID сборки")
        custom = self._registry().get(instance_id, "")
        if custom:
            return self._custom_target(custom)
        target = (self.root / instance_id).resolve()
        if self.root not in target.parents:
            raise ValueError("Путь выходит за каталог сборок")
        return target

    def list(self) -> list[UserInstance]:
        result = []
        hidden = self._hidden_ids()
        registry = self._registry()
        manifests = [path for path in self.root.glob("*/instance.json") if path.parent.name not in registry]
        for instance_id, value in registry.items():
            if re.fullmatch(r"[0-9a-f\-]{36}", instance_id):
                try:
                    manifests.append(self._custom_target(value) / "instance.json")
                except (OSError, ValueError):
                    continue
        for manifest in dict.fromkeys(manifests):
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8"))
                item = UserInstance.from_dict(raw)
                if item.id in hidden:
                    continue
                if int(raw.get("schema_version", raw.get("schemaVersion", 1))) < SCHEMA_VERSION:
                    self.save(item)
                result.append(item)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(result, key=lambda item: item.updated_at, reverse=True)

    def _hidden_ids(self) -> set[str]:
        try:
            return set(json.loads((self.root / "hidden.json").read_text(encoding="utf-8"))["ids"])
        except (OSError, ValueError, KeyError, TypeError):
            return set()

    def forget(self, instance_id: str) -> None:
        self.load(instance_id)
        atomic_json(self.root / "hidden.json", {"ids": sorted(self._hidden_ids() | {instance_id})})

    def load(self, instance_id: str) -> UserInstance:
        manifest = checked_path(self.path_for(instance_id), "instance.json")
        instance = UserInstance.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
        if instance.id != instance_id:
            raise ValueError("Идентификатор сборки не совпадает с каталогом")
        return self._discover_local_mods(instance)

    def _discover_local_mods(self, instance: UserInstance) -> UserInstance:
        """Register JARs copied into mods folders outside the launcher UI."""
        root = self.path_for(instance.id)
        known = {mod.filename for mod in instance.installed_mods}
        changed = False
        for directory, enabled in (("mods", True), ("disabled_mods", False)):
            folder = checked_path(root, directory)
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.jar"), key=lambda item: item.name.lower()):
                if path.name in known:
                    continue
                path = checked_path(root, directory + "/" + path.name)
                checksum = hashlib.sha512()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(block)
                digest = checksum.hexdigest()
                instance.installed_mods.append(
                    InstalledMod(
                        f"local:{path.name}",
                        f"local:{digest[:16]}",
                        path.stem,
                        path.name,
                        digest,
                        enabled,
                    )
                )
                known.add(path.name)
                changed = True
        if changed:
            self.save(instance)
            self.audit(instance.id, "local_mods_discovered")
        return instance

    def save(self, instance: UserInstance) -> None:
        instance.updated_at = utc_now()
        root = self.path_for(instance.id)
        root.mkdir(parents=True, exist_ok=True)
        instance.install_path = str(root) if root.parent != self.root else ""
        instance.schema_version = SCHEMA_VERSION
        data = asdict(instance)
        atomic_json(root / "instance.json", data)

    def audit(self, instance_id: str, action: str, details: dict | None = None) -> None:
        entry = {"time": utc_now(), "action": action, "details": details or {}}
        path = self.path_for(instance_id) / ".nexus" / "operations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def backup_manifest(self, instance_id: str, label: str = "manual") -> Path:
        root = self.path_for(instance_id)
        manifest = root / "instance.json"
        if not manifest.is_file():
            raise FileNotFoundError(manifest)
        safe_label = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-") or "backup"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = root / ".nexus" / "backups" / f"{stamp}-{safe_label}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest, target)
        self.audit(instance_id, "manifest_backup", {"file": target.name})
        return target

    def create(
        self,
        name: str,
        minecraft_version: str,
        loader: str,
        loader_version: str = "",
        install_path: str = "",
    ) -> UserInstance:
        name = name.strip()
        loader = loader.lower().strip()
        if not name or len(name) > 64:
            raise ValueError("Название сборки должно содержать 1–64 символа")
        if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", minecraft_version):
            raise ValueError("Некорректная версия Minecraft")
        if loader not in VALID_LOADERS:
            raise ValueError("Неизвестный загрузчик")
        loader_version = loader_provider(loader).normalize(minecraft_version, loader_version)
        if loader != "vanilla" and not loader_version:
            raise ValueError("Для этой версии требуется указать версию загрузчика")
        instance = UserInstance(str(uuid.uuid4()), name, minecraft_version, loader, loader_version)
        if install_path:
            target = self._custom_target(install_path)
            self._ensure_no_instance_overlap(target)
            if target.exists() and any(target.iterdir()):
                raise ValueError("Выбранная папка уже содержит файлы")
            registry = self._registry()
            registry[instance.id] = str(target)
            self._save_registry(registry)
        root = self.path_for(instance.id)
        root.mkdir(parents=True, exist_ok=True)
        for relative in INSTANCE_DIRS:
            (root / relative).mkdir(parents=True, exist_ok=True)
        self.save(instance)
        self.audit(instance.id, "instance_created", {"name": instance.name})
        return instance

    def relocate(self, instance_id: str, destination: str | Path, move_files: bool) -> UserInstance:
        """Move an instance transactionally or start a new install without deleting old files."""
        instance = self.load(instance_id)
        source = self.path_for(instance_id)
        target = self._custom_target(destination)
        self._ensure_no_instance_overlap(target, instance_id)
        if source.absolute() == target.absolute():
            return instance
        if source in target.parents or target in source.parents:
            raise ValueError("Новая и старая папки не должны находиться одна внутри другой")
        if target.exists() and any(target.iterdir()):
            raise ValueError("Новая папка уже содержит файлы")
        self.backup_manifest(instance_id, "before-path-change")
        registry = self._registry()
        if move_files:
            staging = target.with_name(target.name + ".nexus-moving-" + uuid.uuid4().hex)
            if staging.exists():
                raise FileExistsError(staging)
            try:
                shutil.copytree(source, staging)
                source_files = {
                    path.relative_to(source).as_posix(): path.stat().st_size
                    for path in source.rglob("*") if path.is_file() and not path.is_symlink()
                }
                copied_files = {
                    path.relative_to(staging).as_posix(): path.stat().st_size
                    for path in staging.rglob("*") if path.is_file() and not path.is_symlink()
                }
                if source_files != copied_files:
                    raise OSError("Проверка скопированных файлов не пройдена")
                staging.replace(target)
                registry[instance_id] = str(target)
                self._save_registry(registry)
                shutil.rmtree(source)
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise
        else:
            target.mkdir(parents=True, exist_ok=True)
            registry[instance_id] = str(target)
            self._save_registry(registry)
            for relative in INSTANCE_DIRS:
                (target / relative).mkdir(parents=True, exist_ok=True)
            instance.installed_mods = []
            instance.state = "ready"
            self.save(instance)
        instance = self.load(instance_id)
        self.save(instance)
        self.audit(instance_id, "instance_path_changed", {"from": str(source), "to": str(target), "moved": move_files})
        return instance

    def rename(self, instance_id: str, name: str) -> UserInstance:
        instance = self.load(instance_id)
        if not name.strip() or len(name.strip()) > 64:
            raise ValueError("Название сборки должно содержать 1–64 символа")
        instance.name = name.strip()
        self.backup_manifest(instance_id, "before-rename")
        self.save(instance)
        self.audit(instance_id, "instance_renamed", {"name": instance.name})
        return instance

    def duplicate(self, instance_id: str, name: str = "") -> UserInstance:
        source_instance = self.load(instance_id)
        duplicate = self.create(
            name.strip() or f"{source_instance.name} — копия",
            source_instance.minecraft_version,
            source_instance.loader,
            source_instance.loader_version,
        )
        source = self.path_for(instance_id)
        target = self.path_for(duplicate.id)
        try:
            for relative in (*INSTANCE_DIRS, "options.txt", "servers.dat"):
                origin = checked_path(source, relative)
                if origin.is_symlink() or not origin.exists():
                    continue
                destination = checked_path(target, relative.replace("\\", "/"))
                if origin.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(origin, destination)
                    continue
                for file in origin.rglob("*"):
                    file = checked_path(source, file.relative_to(source).as_posix())
                    if not file.is_file() or file.is_symlink():
                        continue
                    member = file.relative_to(source).as_posix()
                    output = checked_path(target, member)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, output)
            duplicate.memory_mb = source_instance.memory_mb
            duplicate.min_memory_mb = source_instance.min_memory_mb
            duplicate.java_path = source_instance.java_path
            duplicate.jvm_args = list(source_instance.jvm_args)
            duplicate.icon = source_instance.icon
            duplicate.banner = source_instance.banner
            duplicate.resolution_width = source_instance.resolution_width
            duplicate.resolution_height = source_instance.resolution_height
            duplicate.installed_mods = [InstalledMod(**asdict(mod)) for mod in source_instance.installed_mods]
            self.save(duplicate)
            self.audit(duplicate.id, "instance_duplicated", {"source": instance_id})
            return duplicate
        except Exception:
            self.delete(duplicate.id)
            raise

    def delete(self, instance_id: str) -> None:
        target = self.path_for(instance_id)
        if target == self.root or target in {Path(target.anchor), Path.home().resolve()}:
            raise ValueError("Нельзя удалить корневую папку")
        for other in self.list():
            other_path = self.path_for(other.id)
            if other.id != instance_id and (target in other_path.parents or other_path in target.parents):
                raise ValueError("Папки сборок не должны быть вложены друг в друга")
        if target.exists():
            remove_owned_tree(target.parent, target.name)
        registry = self._registry()
        if instance_id in registry:
            registry.pop(instance_id)
            self._save_registry(registry)

    def disk_summary(self, instance_id):
        root = self.path_for(instance_id)
        total, saves = 0, 0
        for folder, dirs, files in os.walk(root, followlinks=False):
            for entry in dirs + files:
                checked_path(root, (Path(folder) / entry).relative_to(root).as_posix())
            for filename in files:
                path = checked_path(root, (Path(folder) / filename).relative_to(root).as_posix())
                total += path.stat().st_size
        saves_root = checked_path(root, "saves")
        if saves_root.is_dir(): saves = sum(path.is_dir() for path in saves_root.iterdir())
        return {"path": root, "bytes": total, "saves": saves}

    def set_mod_enabled(self, instance_id: str, filename: str, enabled: bool) -> UserInstance:
        instance = self.load(instance_id)
        self.backup_manifest(instance_id, "before-mod-toggle")
        filename = safe_filename(filename)
        root = self.path_for(instance_id)
        source_dir = root / ("disabled_mods" if enabled else "mods")
        destination_dir = root / ("mods" if enabled else "disabled_mods")
        source = source_dir / filename
        if not source.is_file():
            raise FileNotFoundError(filename)
        destination_dir.mkdir(parents=True, exist_ok=True)
        replace_file(source, destination_dir / filename)
        for mod in instance.installed_mods:
            if mod.filename == filename:
                mod.enabled = enabled
        self.save(instance)
        self.audit(instance_id, "mod_toggled", {"filename": filename, "enabled": enabled})
        return instance

    def remove_mod(self, instance_id: str, filename: str) -> UserInstance:
        instance = self.load(instance_id)
        self.backup_manifest(instance_id, "before-mod-remove")
        filename = safe_filename(filename)
        root = self.path_for(instance_id)
        for directory in ("mods", "disabled_mods"):
            target = root / directory / filename
            if target.is_file():
                target.unlink()
        instance.installed_mods = [mod for mod in instance.installed_mods if mod.filename != filename]
        self.save(instance)
        self.audit(instance_id, "mod_removed", {"filename": filename})
        return instance
