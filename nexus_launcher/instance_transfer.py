from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from nexus_launcher.resource_limits import MAX_FILE_BYTES, copy_limited, digest_limited, ensure_space, read_limited, validate_archive
from nexus_launcher.safe_paths import checked_path, relative_parts
from nexus_launcher.user_instances import InstalledMod, InstanceService, UserInstance, safe_filename
from nexus_launcher.native_zip import open_zip_entry, write_zip_data, write_zip_file

MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_FILES = 50_000
ALLOWED_IMPORT_ROOTS = {
    "mods",
    "config",
    "resourcepacks",
    "shaderpacks",
    "saves",
    "screenshots",
    "options.txt",
    "servers.dat",
    "instance.json",
    "disabled_mods",
    "defaultconfigs",
    "kubejs",
    "scripts",
    "datapacks",
}


def _safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    relative_parts(normalized.rstrip("/"))
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Небезопасный путь в архиве: {name}")
    if ":" in path.parts[0]:
        raise ValueError(f"Небезопасный путь в архиве: {name}")
    return path


class InstanceTransferService:
    def __init__(self, instances: InstanceService):
        self.instances = instances

    def analyze_zip(self, archive: Path):
        with zipfile.ZipFile(archive) as source:
            total = validate_archive(source)
            entries = source.infolist()
            for entry in entries:
                _safe_member(entry.filename)
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Архив содержит символическую ссылку")
            metadata = next((e for e in entries if _safe_member(e.filename).name == "instance.json"), None)
            raw = {}
            if metadata:
                with source.open(metadata) as stream:
                    raw = json.loads(read_limited(stream))
                if not isinstance(raw, dict):
                    raise ValueError("Некорректные метаданные сборки")
            return {"minecraft": raw.get("minecraft_version"), "loader": raw.get("loader"),
                    "mods": sum(e.filename.endswith(".jar") and "mods" in _safe_member(e.filename).parts for e in entries),
                    "bytes": total, "files": len(entries)}

    def analyze_folder(self, folder: Path):
        from nexus_launcher.creator_services import safe_files
        folder = checked_path(folder.parent, folder.name)
        if not folder.is_dir():
            raise ValueError("Папка не найдена")
        files = list(safe_files(folder, tuple(name for name in ALLOWED_IMPORT_ROOTS if "." not in name)))
        metadata = checked_path(folder, "instance.json")
        raw = {}
        if metadata.is_file():
            with metadata.open("rb") as stream:
                raw = json.loads(read_limited(stream))
        if not isinstance(raw, dict):
            raise ValueError("Некорректные метаданные сборки")
        return {"minecraft": raw.get("minecraft_version"), "loader": raw.get("loader"),
                "loader_version": raw.get("loader_version", ""),
                "mods": sum(name.startswith("mods/") and name.endswith(".jar") for name, _ in files),
                "bytes": sum(path.stat().st_size for _, path in files), "files": len(files)}

    def import_folder(self, folder: Path, name, minecraft, loader, loader_version="", progress=lambda *_: None):
        from nexus_launcher.creator_services import safe_files
        summary = self.analyze_folder(folder)
        ensure_space(self.instances.root, summary["bytes"])
        instance = self.instances.create(name, minecraft, loader, loader_version)
        instance.state = "importing"
        self.instances.save(instance)
        try:
            root = self.instances.path_for(instance.id)
            files = list(safe_files(folder, tuple(n for n in ALLOWED_IMPORT_ROOTS if "." not in n)))
            for index, (relative, source) in enumerate(files, 1):
                progress(relative, index, len(files))
                target = checked_path(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    copy_limited(incoming, outgoing)
            for relative in ("options.txt", "servers.dat"):
                source = checked_path(folder, relative)
                if source.is_file():
                    with source.open("rb") as incoming, checked_path(root, relative).open("xb") as outgoing:
                        copy_limited(incoming, outgoing)
            instance = self.instances.load(instance.id)
            instance.state = "ready"
            self.instances.save(instance)
            return self.instances.load(instance.id)
        except Exception:
            self.instances.delete(instance.id)
            raise

    def import_jar(self, instance_id: str, source: Path) -> Path:
        source = source.resolve()
        if not source.is_file() or source.suffix.lower() != ".jar":
            raise ValueError("Выберите существующий .jar файл")
        name = safe_filename(source.name)
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("JAR exceeds size limit")
        root = self.instances.path_for(instance_id)
        ensure_space(root, source.stat().st_size)
        destination = checked_path(root, "mods/" + name)
        fd, temporary = tempfile.mkstemp(prefix="import-", suffix=".part", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
                copy_limited(stream, output)
            os.replace(temporary, checked_path(root, "mods/" + name))
        finally:
            Path(temporary).unlink(missing_ok=True)
        instance = self.instances.load(instance_id)
        with destination.open("rb") as written_file:
            digest = digest_limited(written_file, "sha512")
        instance.installed_mods = [mod for mod in instance.installed_mods if mod.filename != name]
        instance.installed_mods.append(InstalledMod(f"local:{name}", f"local:{digest[:16]}", source.stem, name, digest))
        self.instances.save(instance)
        self.instances.audit(instance_id, "local_mod_added", {"filename": name})
        return destination

    def import_zip(self, archive: Path, name: str = "") -> UserInstance:
        self.analyze_zip(archive)
        archive = archive.resolve()
        if not archive.is_file() or archive.suffix.lower() != ".zip":
            raise ValueError("Нужен ZIP-архив")
        with zipfile.ZipFile(archive) as source:
            ensure_space(self.instances.root, validate_archive(source))
            members = source.infolist()
            if len(members) > MAX_FILES or sum(item.file_size for item in members) > MAX_ARCHIVE_BYTES:
                raise ValueError("Архив превышает безопасные ограничения")
            manifest_entry = next(
                (item for item in members if _safe_member(item.filename).name == "instance.json"), None
            )
            raw = {}
            if manifest_entry:
                with source.open(manifest_entry) as stream:
                    raw = json.loads(read_limited(stream).decode("utf-8"))
                minecraft = str(raw.get("minecraft_version", "1.21.1"))
                loader = str(raw.get("loader", "fabric"))
                loader_version = str(raw.get("loader_version", ""))
                display_name = name.strip() or str(raw.get("name", archive.stem))
            else:
                minecraft, loader, loader_version = "1.21.1", "fabric", ""
                display_name = name.strip() or archive.stem
            instance = self.instances.create(display_name, minecraft, loader, loader_version)
            instance.state = "importing"
            self.instances.save(instance)
            destination = self.instances.path_for(instance.id)
            try:
                for item in members:
                    member = _safe_member(item.filename)
                    if item.is_dir():
                        continue
                    parts = list(member.parts)
                    # Common archives contain one outer directory; discard it.
                    if len(parts) > 1 and parts[0] not in ALLOWED_IMPORT_ROOTS:
                        parts = parts[1:]
                    if not parts or parts[0] not in ALLOWED_IMPORT_ROOTS or parts[-1] == "instance.json":
                        continue
                    target = checked_path(destination, "/".join(parts))
                    if destination not in target.parents:
                        raise ValueError("Файл архива выходит за каталог сборки")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open_zip_entry(source, item) as input_stream, target.open("wb") as output_stream:
                        copy_limited(input_stream, output_stream, item.file_size)
                if raw:
                    imported_manifest = UserInstance.from_dict(raw)
                    instance.memory_mb = imported_manifest.memory_mb
                    instance.min_memory_mb = imported_manifest.min_memory_mb
                    # Archives are untrusted: JVM agents and argument files may
                    # execute extra code. Advanced arguments must be set locally.
                    instance.jvm_args = []
                    if imported_manifest.jvm_args:
                        self.instances.audit(instance.id, "imported_jvm_arguments_ignored")
                    instance.installed_mods = [
                        mod
                        for mod in imported_manifest.installed_mods
                        if (
                            destination / ("mods" if mod.enabled else "disabled_mods") / safe_filename(mod.filename)
                        ).is_file()
                    ]
                    self.instances.save(instance)
                instance = self.instances.load(instance.id)
                instance.state = "ready"
                self.instances.save(instance)
                self.instances.audit(instance.id, "zip_imported", {"archive": archive.name})
                return self.instances.load(instance.id)
            except Exception:
                self.instances.delete(instance.id)
                raise

    def export_zip(self, instance_id: str, destination: Path) -> Path:
        instance = self.instances.load(instance_id)
        root = self.instances.path_for(instance_id)
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(suffix=".zip.part", dir=destination.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary_name, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                write_zip_data(archive,
                    "instance.json",
                    json.dumps(
                        {**instance.__dict__, "java_path": "", "jvm_args": [], "install_path": "", "icon": "", "banner": "", "installed_mods": [mod.__dict__ for mod in instance.installed_mods]},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                from nexus_launcher.creator_services import safe_files
                for relative, path in safe_files(root, ("mods", "disabled_mods", "config", "resourcepacks", "shaderpacks", "defaultconfigs", "kubejs", "scripts", "datapacks")):
                    write_zip_file(archive, path, relative)
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        self.instances.audit(instance_id, "zip_exported", {"file": destination.name})
        return destination
