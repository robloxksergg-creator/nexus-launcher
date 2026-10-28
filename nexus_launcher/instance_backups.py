"""File snapshots, restored into a new instance without overwriting a running game."""
import json
import uuid
import zipfile
import re
import tempfile
import os
from dataclasses import asdict
from pathlib import Path

from nexus_launcher.creator_services import safe_files
from nexus_launcher.resource_limits import validate_archive, ensure_space, copy_limited, MAX_FILE_BYTES, MAX_EXTRACTED_BYTES, MAX_ARCHIVE_ENTRIES
from nexus_launcher.safe_paths import checked_path
from nexus_launcher.user_instances import atomic_json, utc_now

DIRECTORIES = ("mods", "disabled_mods", "config", "resourcepacks", "shaderpacks", "saves")
SINGLE_FILES = ("options.txt", "servers.dat", ".nexus/project.json")


class BackupService:
    def __init__(self, instances):
        self.instances = instances

    def folder(self, identifier):
        path = checked_path(self.instances.path_for(identifier), ".nexus/backups")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def list(self, identifier):
        return sorted(self.folder(identifier).glob("snapshot-*.zip"), key=lambda p: p.name, reverse=True)

    def create(self, identifier, retain=5, label="manual"):
        instance = self.instances.load(identifier)
        root = self.instances.path_for(identifier)
        files = list(safe_files(root, DIRECTORIES))
        for name in SINGLE_FILES:
            path = checked_path(root, name)
            if path.is_file():
                files.append((name, path))
        sizes = [path.stat().st_size for _, path in files]
        if len(files) + 1 > MAX_ARCHIVE_ENTRIES or any(size > MAX_FILE_BYTES for size in sizes) or sum(sizes) > MAX_EXTRACTED_BYTES - 4 * 1024 * 1024:
            raise ValueError("Копия превышает безопасный предел: 4 ГБ суммарно, 1 ГБ на файл")
        ensure_space(root, sum(sizes))
        label = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-") or "manual"
        name = "snapshot-" + label + "-" + utc_now().replace(":", "-") + "-" + uuid.uuid4().hex[:8] + ".zip"
        destination = checked_path(self.folder(identifier), name)
        fd, temporary_name = tempfile.mkstemp(prefix=name + ".", suffix=".part", dir=destination.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("instance.json", json.dumps(asdict(instance), ensure_ascii=False))
                for relative, path in files:
                    checked_path(root, relative)
                    archive.write(path, relative)
            os.replace(temporary, destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        for old in self.list(identifier)[max(1, int(retain)):]:
            checked_path(self.folder(identifier), old.name).unlink()
        return destination

    def restore_copy(self, identifier, filename):
        source = checked_path(self.folder(identifier), filename)
        with zipfile.ZipFile(source) as archive:
            total = validate_archive(archive)
            seen = set()
            for info in archive.infolist():
                checked_path(self.folder(identifier), info.filename)
                if info.filename.casefold() in seen or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Небезопасная резервная копия")
                seen.add(info.filename.casefold())
                if info.filename != "instance.json" and info.filename not in SINGLE_FILES and info.filename.split("/")[0] not in DIRECTORIES:
                    raise ValueError("Файл вне области резервной копии")
            metadata = archive.getinfo("instance.json")
            if metadata.file_size > 4 * 1024 * 1024:
                raise ValueError("Слишком большие метаданные")
            raw = json.loads(archive.read(metadata))
            ensure_space(self.instances.root, total)
            from datetime import datetime
            restored = self.instances.create(raw["name"] + " — restored " + datetime.now().strftime("%Y-%m-%d"), raw["minecraft_version"], raw["loader"], raw.get("loader_version", ""))
            restored.state = "restoring"
            self.instances.save(restored)
            try:
                root = self.instances.path_for(restored.id)
                for info in archive.infolist():
                    if info.filename == "instance.json" or info.is_dir():
                        continue
                    target = checked_path(root, info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as incoming, target.open("xb") as output:
                        copy_limited(incoming, output, info.file_size)
                restored.memory_mb = max(1024, min(32768, int(raw.get("memory_mb", 4096))))
                # Never restore executable paths/JVM arguments from an imported archive.
                from nexus_launcher.user_instances import InstalledMod
                restored.installed_mods = [InstalledMod(**item) for item in raw.get("installed_mods", [])]
                restored.state = "ready"
                self.instances.save(restored)
                return restored
            except Exception:
                self.instances.delete(restored.id)
                raise

    def delete(self, identifier, filename):
        path = checked_path(self.folder(identifier), filename)
        if not filename.startswith("snapshot-") or not filename.endswith(".zip"):
            raise ValueError("Это не резервная копия")
        path.unlink()
