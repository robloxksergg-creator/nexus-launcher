"""Local creator operations. No official publication or signing authority."""
from __future__ import annotations

from nexus_launcher.resource_limits import digest_file

import hashlib
import json
import os
import re
import zipfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from nexus_launcher.safe_paths import checked_path
from nexus_launcher.native_zip import write_zip_data, write_zip_entry
from nexus_launcher.user_instances import InstanceService, atomic_json, utc_now


@dataclass(frozen=True)
class Capabilities:
    mode: str = "player"
    authenticated_authority: bool = False

    @property
    def can_create_instance(self): return True
    @property
    def can_use_studio(self): return self.mode == "creator" or (self.mode in {"reviewer", "nexus_launcher.admin"} and self.authenticated_authority)
    @property
    def can_edit_project(self): return self.can_use_studio
    @property
    def can_export_client(self): return self.can_use_studio
    @property
    def can_export_server(self): return self.can_use_studio
    @property
    def can_validate_project(self): return self.can_use_studio
    @property
    def can_build_release(self): return self.can_use_studio
    @property
    def can_prepare_submission(self): return self.can_use_studio
    @property
    def can_review_submission(self): return self.authenticated_authority and self.mode in {"reviewer", "nexus_launcher.admin"}
    @property
    def can_mark_official(self): return self.authenticated_authority and self.mode == "nexus_launcher.admin"
    @property
    def can_suspend_world(self): return self.authenticated_authority and self.mode == "nexus_launcher.admin"

    def require_creator(self):
        # Team/admin require a future authenticated authority, never a local flag.
        if not self.can_use_studio:
            raise PermissionError("Включите Creator Mode в дополнительных настройках")

    def require(self, capability):
        if not getattr(self, capability, False):
            raise PermissionError("Операция недоступна для текущей роли")

    @property
    def can_publish(self):
        # Publication always belongs to the future authenticated backend/CI.
        return False


TEMPLATES = {
    "Empty": {"loader": "vanilla", "memory_mb": 4096},
    "Vanilla": {"loader": "vanilla", "memory_mb": 4096},
    "Fabric Performance": {"loader": "fabric", "memory_mb": 4096},
    "NeoForge Tech": {"loader": "neoforge", "memory_mb": 6144},
    "RPG Base": {"loader": "fabric", "memory_mb": 6144},
}
SIDES = {"unknown", "client", "server", "both", "optional-client"}
PACK_DIRS = ("mods", "config", "resourcepacks", "shaderpacks", "defaultconfigs", "kubejs", "scripts", "datapacks")


def safe_files(root: Path, directories=PACK_DIRS):
    """Reject reparse points at every level, including directory junctions."""
    for name in directories:
        base = checked_path(root, name)
        if not base.exists():
            continue
        for folder, dirs, files in os.walk(base, followlinks=False):
            for entry in dirs + files:
                checked_path(root, (Path(folder) / entry).relative_to(root).as_posix())
            for filename in sorted(files):
                path = Path(folder) / filename
                yield path.relative_to(root).as_posix(), path


def digest(path):
    return digest_file(path)


def mod_metadata(path):
    """Only interpret explicit mod metadata; unknown JARs do not imply a loader."""
    import tomllib
    result = {"ids": set(), "loaders": set(), "requires": set(), "nested": False, "side": "unknown"}
    if not zipfile.is_zipfile(path):
        return result
    with zipfile.ZipFile(path) as archive:
        result["nested"] = "META-INF/jarjar/metadata.json" in archive.namelist()
        for name, loader in (("fabric.mod.json", "fabric"), ("META-INF/neoforge.mods.toml", "neoforge"), ("META-INF/mods.toml", "forge")):
            if name not in archive.namelist():
                continue
            entry = archive.getinfo(name)
            if entry.file_size > 4 * 1024 * 1024:
                raise ValueError("Слишком большие метаданные мода: " + path.name)
            raw = archive.read(entry).decode("utf-8")
            data = json.loads(raw) if loader == "fabric" else tomllib.loads(raw)
            result["loaders"].add(loader)
            if loader == "fabric":
                result["nested"] = result["nested"] or bool(data.get("jars"))
                result["ids"].add(data["id"])
                result["ids"].update(data.get("provides", []))
                result["requires"].update(data.get("depends", {}).keys())
                environment = data.get("environment", "*")
                result["side"] = {"client": "client", "server": "server", "*": "both"}.get(environment, "unknown")
            else:
                result["ids"].update(m["modId"] for m in data.get("mods", []))
                for dependencies in data.get("dependencies", {}).values():
                    result["requires"].update(d["modId"] for d in dependencies if d.get("mandatory") is True or d.get("type") == "required")
    return result


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    message: str
    action: str = ""


@dataclass(frozen=True)
class ExportSummary:
    server: bool
    included_mods: int
    excluded_mods: int
    unknown_mods: int
    configs: int
    datapacks: int
    excluded_shaders: int
    total_bytes: int


class StudioService:
    def __init__(self, instances: InstanceService, capabilities: Capabilities):
        self.instances = instances
        self.capabilities = capabilities

    def load(self, identifier):
        self.capabilities.require_creator()
        instance = self.instances.load(identifier)
        path = checked_path(self.instances.path_for(identifier), ".nexus/project.json")
        if path.exists():
            if path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Слишком большие метаданные проекта")
            project = json.loads(path.read_text(encoding="utf-8"))
            self.check_metadata(project)
            return project
        return {"name": instance.name, "kind": "modpack", "version": "0.1.0",
                "channel": "dev", "description": "", "changelog": "",
                "presentation": {"icon": instance.icon, "banner": instance.banner},
                "mod_sides": {}, "baseline": {}, "status": "draft"}

    @staticmethod
    def check_metadata(project):
        if not isinstance(project, dict):
            raise ValueError("Некорректные метаданные проекта")
        for field in ("name", "version", "kind", "description", "changelog"):
            if not isinstance(project.get(field, ""), str):
                raise ValueError("Некорректное поле: " + field)
        if project.get("channel", "dev") not in {"dev", "beta", "stable"}:
            raise ValueError("Неизвестный канал")
        if not isinstance(project.get("mod_sides", {}), dict) or not isinstance(project.get("baseline", {}), dict):
            raise ValueError("Некорректный список файлов")
        if not isinstance(project.get("presentation", {}), dict):
            raise ValueError("Некорректная презентация")
        if not isinstance(project.get("metadata", {}), dict) or any(not isinstance(v, str) for v in project.get("metadata", {}).values()):
            raise ValueError("Некорректные метаданные мира")
        for key, value in project.get("presentation", {}).items():
            if not isinstance(value, str):
                raise ValueError("Некорректное поле презентации: " + key)

    def save(self, identifier, project):
        self.capabilities.require("can_edit_project")
        self.instances.load(identifier)
        self.check_metadata(project)
        if project.get("kind") not in {"modpack", "server", "world"}:
            raise ValueError("Неизвестный тип проекта")
        if any(side not in SIDES for side in project.get("mod_sides", {}).values()):
            raise ValueError("Неизвестная классификация мода")
        project = dict(project, status="draft", updated_at=utc_now())
        atomic_json(checked_path(self.instances.path_for(identifier), ".nexus/project.json"), project)

    def inventory(self, identifier):
        self.capabilities.require_creator()
        root = self.instances.path_for(identifier)
        return {name: digest(path) for name, path in safe_files(root)}

    def changes(self, identifier):
        previous = self.load(identifier).get("baseline", {})
        current = self.inventory(identifier)
        return {"added": sorted(current.keys() - previous.keys()),
                "removed": sorted(previous.keys() - current.keys()),
                "changed": sorted(k for k in current.keys() & previous.keys() if current[k] != previous[k])}

    def statistics(self, identifier):
        project = self.load(identifier)
        files = list(safe_files(self.instances.path_for(identifier)))
        sides = project.get("mod_sides", {})
        mods = self.instances.load(identifier).installed_mods
        counts = {side: sum(m.enabled and sides.get(m.filename, "unknown") == side for m in mods) for side in SIDES}
        return {"files": len(files), "bytes": sum(p.stat().st_size for _, p in files), "mods": len(mods), "sides": counts}

    def auto_classify(self, identifier):
        project, instance = self.load(identifier), self.instances.load(identifier)
        sides = project.setdefault("mod_sides", {})
        root = self.instances.path_for(identifier)
        for mod in instance.installed_mods:
            if sides.get(mod.filename, "unknown") != "unknown":
                continue
            path = checked_path(root, ("mods/" if mod.enabled else "disabled_mods/") + mod.filename)
            if path.is_file():
                side = mod_metadata(path)["side"]
                if side != "unknown": sides[mod.filename] = side
        self.save(identifier, project)
        return sides

    def classify(self, identifier, filenames, side):
        if side not in SIDES: raise ValueError("Неизвестная классификация")
        project = self.load(identifier)
        known = {m.filename for m in self.instances.load(identifier).installed_mods}
        for filename in filenames:
            if filename not in known: raise ValueError("Мод не найден: " + filename)
            project.setdefault("mod_sides", {})[filename] = side
        self.save(identifier, project)

    def export_summary(self, identifier, server=False):
        project, instance = self.load(identifier), self.instances.load(identifier)
        sides = project.get("mod_sides", {})
        enabled = [m for m in instance.installed_mods if m.enabled]
        excluded = {"client", "optional-client"} if server else {"server"}
        files = list(safe_files(self.instances.path_for(identifier)))
        return ExportSummary(server, sum(sides.get(m.filename, "unknown") not in excluded for m in enabled),
            sum(sides.get(m.filename, "unknown") in excluded for m in enabled),
            sum(sides.get(m.filename, "unknown") == "unknown" for m in enabled) if server else 0,
            sum(n.startswith(("config/", "defaultconfigs/")) for n, _ in files),
            sum(n.startswith("datapacks/") for n, _ in files),
            sum(n.startswith("shaderpacks/") for n, _ in files) if server else 0,
            sum(p.stat().st_size for _, p in files))

    def validation_report(self, identifier, server=False):
        errors = self.validate(identifier, server)
        instance = self.instances.load(identifier)
        issues = [ValidationIssue("ERROR", value, "Открыть настройки или состав пакета") for value in errors]
        if not errors:
            issues.append(ValidationIssue("INFO", f"Minecraft {instance.minecraft_version} · {instance.loader.title()} готов к тестовому запуску"))
        root = self.instances.path_for(identifier)
        for mod in instance.installed_mods:
            path = checked_path(root, ("mods/" if mod.enabled else "disabled_mods/") + mod.filename)
            if path.is_file() and mod_metadata(path)["nested"]:
                issues.append(ValidationIssue("WARNING", f"{mod.filename}: вложенные зависимости не проверены полностью", "Открыть файл мода"))
            if not mod.project_id:
                issues.append(ValidationIssue("WARNING", f"{mod.filename}: источник и лицензия неизвестны", "Проверить metadata перед review"))
        video = Path(self.load(identifier).get("presentation", {}).get("video", ""))
        if video.is_file() and video.stat().st_size > 256 * 1024 * 1024:
            issues.append(ValidationIssue("WARNING", f"Видео презентации большое: {video.stat().st_size / 1048576:.0f} МБ", "Проверить размер и длительность"))
        presentation = self.load(identifier).get("presentation", {})
        from PySide6.QtGui import QImageReader
        for key, preferred_ratio in (("icon", 1.0), ("banner", 16 / 9), ("poster", 16 / 9)):
            path = Path(presentation.get(key, ""))
            if not path.is_file():
                continue
            size = QImageReader(str(path)).size()
            if size.width() > 0 and size.height() > 0:
                ratio = size.width() / size.height()
                if abs(ratio - preferred_ratio) / preferred_ratio > 0.22:
                    issues.append(ValidationIssue("WARNING", f"{key}: нестандартное соотношение сторон {size.width()}×{size.height()}", "Проверить preview"))
        return issues

    def validate(self, identifier, server=False):
        self.capabilities.require("can_validate_project")
        project = self.load(identifier)
        instance = self.instances.load(identifier)
        problems = []
        from nexus_launcher.runtime_settings import required_java
        try:
            required = required_java(instance.minecraft_version)
            if instance.java_major and instance.java_major != required:
                problems.append(f"Для Minecraft {instance.minecraft_version} требуется Java {required}")
        except ValueError as error:
            problems.append(str(error))
        if instance.loader not in {"vanilla", "fabric", "forge", "neoforge"}:
            problems.append("Неизвестный загрузчик")
        if not project.get("name", "").strip() or not project.get("version", "").strip():
            problems.append("Название и версия обязательны")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", project.get("version", "")):
            problems.append("Версия проекта должна иметь формат 1.2.3")
        metadata = project.get("metadata", {})
        if metadata.get("accent") and not re.fullmatch(r"#[0-9a-fA-F]{6}", metadata["accent"]):
            problems.append("Акцент должен иметь формат #RRGGBB")
        if metadata.get("max_players") and (not metadata["max_players"].isdigit() or not 1 <= int(metadata["max_players"]) <= 100000):
            problems.append("Некорректное число игроков")
        for key, value in project.get("presentation", {}).items():
            if key in {"icon", "banner", "poster", "video"} and value:
                asset = Path(value)
                allowed = {".mp4", ".webm"} if key == "video" else {".png", ".jpg", ".jpeg", ".webp"}
                if asset.suffix.lower() not in allowed or not asset.is_file():
                    problems.append("Некорректный ресурс: " + key)
                elif key != "video" and asset.stat().st_size > 32 * 1024 * 1024:
                    problems.append("Слишком большой ресурс: " + key)
                elif key == "video" and asset.stat().st_size == 0:
                    problems.append("Видео пустое или не читается")
                elif key != "video":
                    from PySide6.QtGui import QImageReader
                    reader = QImageReader(str(asset))
                    size = reader.size()
                    if not reader.canRead() or size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 100_000_000:
                        problems.append("Изображение повреждено или слишком велико: " + key)
        if instance.loader != "vanilla" and not instance.loader_version:
            problems.append("Не указана версия загрузчика")
        if instance.java_path and (not Path(instance.java_path).is_file() or Path(instance.java_path).name.lower() not in {"java", "java.exe", "javaw.exe"}):
            problems.append("Указанный Java executable не найден")
        root = self.instances.path_for(identifier)
        seen = set()
        declared = {"minecraft", "java", "fabricloader", "forge", "neoforge"}
        requirements = []
        has_nested = False
        for mod in instance.installed_mods:
            if not mod.enabled:
                continue
            path = checked_path(root, "mods/" + mod.filename)
            if not path.is_file():
                problems.append("Нет файла: " + mod.filename)
            elif project.get("mod_sides", {}).get(mod.filename, "unknown") not in ({"client", "optional-client"} if server else {"server"}):
                try:
                    metadata = mod_metadata(path)
                    has_nested = has_nested or metadata["nested"]
                    duplicate = metadata["ids"] & declared
                    if duplicate:
                        problems.append("Дублирующийся mod ID: " + ", ".join(sorted(duplicate)))
                    declared.update(metadata["ids"])
                    requirements.append((mod.filename, metadata["requires"]))
                    # NeoForge supports some legacy mods.toml metadata; do not infer incompatibility from it.
                    if metadata["loaders"] == {"fabric"} and instance.loader != "fabric":
                        problems.append("Fabric-мод в другой сборке: " + mod.filename)
                    if metadata["loaders"] == {"neoforge"} and instance.loader != "neoforge":
                        problems.append("NeoForge-мод в другой сборке: " + mod.filename)
                except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
                    problems.append("Повреждены метаданные " + mod.filename + ": " + str(error))
            if mod.project_id in seen:
                problems.append("Дубликат проекта: " + mod.name)
            seen.add(mod.project_id)
            if server and project.get("mod_sides", {}).get(mod.filename, "unknown") == "unknown":
                problems.append("Укажите сторону мода: " + mod.filename)
        for filename, required_ids in requirements:
            missing = required_ids - declared
            if missing and not has_nested:
                problems.append(filename + " — отсутствуют зависимости: " + ", ".join(sorted(missing)))
        self.inventory(identifier)  # Also validates traversal/reparse safety.
        return problems

    def export(self, identifier, destination: Path, server=False):
        self.capabilities.require("can_export_server" if server else "can_export_client")
        errors = self.validate(identifier, server)
        if errors:
            raise ValueError("\n".join(errors))
        project = self.load(identifier)
        root = self.instances.path_for(identifier)
        instance = self.instances.load(identifier)
        selected = {m.filename for m in instance.installed_mods if m.enabled and
                    project.get("mod_sides", {}).get(m.filename, "unknown") not in
                    ({"client", "optional-client"} if server else {"server"})}
        files = [(name, path) for name, path in safe_files(root)
                 if (not name.startswith("mods/") or name[5:] in selected)
                 and (not server or not name.startswith(("resourcepacks/", "shaderpacks/")))]
        presentation = {}
        for key, value in project.get("presentation", {}).items():
            if key in {"icon", "banner", "poster", "video"} and value:
                asset = Path(value)
                path = checked_path(asset.parent, asset.name)
                relative = "nexus-presentation/" + key + path.suffix.lower()
                files.append((relative, path))
                presentation[key] = relative
        destination = checked_path(destination.parent, destination.name)
        if destination.is_relative_to(root):
            raise ValueError("Экспортируйте пакет за пределы папки проекта")
        # Never silently overwrite a previous release or any source file.
        if destination.exists(): raise FileExistsError(destination)
        from nexus_launcher.resource_limits import ensure_space
        ensure_space(destination.parent, sum(path.stat().st_size for _, path in files))
        fd, temporary_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".part", dir=destination.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                hashes = {}
                for name, path in files:
                    if not name.startswith("nexus-presentation/"):
                        checked_path(root, name)
                    checksum = hashlib.sha256()
                    from nexus_launcher.resource_limits import copy_limited
                    with path.open("rb") as incoming, write_zip_entry(archive, name) as outgoing:
                        copy_limited(incoming, outgoing, digest=checksum)
                    hashes[name] = checksum.hexdigest()
                write_zip_data(archive, "nexus-local-manifest.json", json.dumps({
                    "schema": 1, "official": False, "signed": False,
                    "name": project["name"], "version": project["version"],
                    "channel": project.get("channel", "dev"), "scope": "local", "minecraft": instance.minecraft_version,
                    "loader": instance.loader, "loader_version": instance.loader_version,
                    "presentation": presentation, "metadata": project.get("metadata", {}),
                    "changelog": project.get("changelog", ""), "sha256": hashes,
                }, ensure_ascii=False, indent=2))
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination
