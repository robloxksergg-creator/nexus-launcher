from __future__ import annotations

from nexus_launcher.resource_limits import digest_file

import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

SCOPES = {"SERVER", "CLIENT", "BOTH"}
MODES = {"REQUIRED", "OPTIONAL", "PRESERVE"}
ALLOWED_ROOTS = {"mods", "config", "defaultconfigs", "kubejs", "resourcepacks", "shaderpacks", "tacz"}


def sha256(path: Path) -> str:
    return digest_file(path)


@dataclass
class ManagedFile:
    path: str
    scope: str
    mode: str
    size: int
    sha256: str
    stored_name: str
    mod_id: str = ""
    mod_version: str = ""
    dependencies: list[str] = field(default_factory=list)
    display_name: str = ""
    description: str = ""
    category: str = "other"
    default_enabled: bool = False
    recommended: bool = False
    performance_impact: str = ""
    conflicts: list[str] = field(default_factory=list)


@dataclass
class BuildMetadata:
    pack_name: str = "GearMorph"
    display_name: str = "Tech & Magick"
    season_name: str = "Season 2"
    pack_version: str = "1.0.0"
    minecraft_version: str = "1.21.1"
    loader: str = "neoforge"
    loader_version: str = "21.1.248"
    description: str = ""
    logo: str = ""
    background: str = ""
    server_address: str = "playgearmorph.bisquitmc.net"
    maintenance: bool = False
    minimum_launcher_version: str = "0.9.6"


class BuildManager:
    """Local draft/release repository with atomic current-pointer publication."""

    def __init__(self, root: Path, public_base_url: str = ""):
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self.draft_dir = root / "draft"
        self.releases_dir = root / "releases"
        self.current_dir = root / "current"
        self.audit_file = root / "audit.jsonl"
        for directory in (self.draft_dir / "files", self.releases_dir, self.current_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if not (self.draft_dir / "metadata.json").exists():
            self.save_metadata(BuildMetadata())
            self._write_json(self.draft_dir / "files.json", [])

    def metadata(self) -> BuildMetadata:
        return BuildMetadata(**self._read_json(self.draft_dir / "metadata.json", {}))

    def save_metadata(self, metadata: BuildMetadata, actor: str = "SYSTEM") -> None:
        self._write_json_atomic(self.draft_dir / "metadata.json", asdict(metadata))
        self.audit("BUILD_METADATA_CHANGED", actor, {"version": metadata.pack_version})

    def files(self) -> list[ManagedFile]:
        return [ManagedFile(**item) for item in self._read_json(self.draft_dir / "files.json", [])]

    def add_file(
        self, source: Path, destination: str, scope: str, mode: str, actor: str = "SYSTEM", **optional
    ) -> ManagedFile:
        source = source.resolve()
        scope, mode = scope.upper(), mode.upper()
        safe = PurePosixPath(destination.replace("\\", "/").lstrip("/"))
        if not source.is_file() or ".." in safe.parts or not safe.parts or safe.parts[0] not in ALLOWED_ROOTS:
            raise ValueError("Invalid managed file or destination")
        if scope not in SCOPES or mode not in MODES:
            raise ValueError("Invalid scope or mode")
        stored = f"{sha256(source)[:16]}-{source.name}"
        shutil.copy2(source, self.draft_dir / "files" / stored)
        mod_id, mod_version, dependencies = self._inspect_mod(source)
        entry = ManagedFile(
            safe.as_posix(),
            scope,
            mode,
            source.stat().st_size,
            sha256(source),
            stored,
            mod_id,
            mod_version,
            dependencies,
            str(optional.get("display_name", "")),
            str(optional.get("description", "")),
            str(optional.get("category", "other")).lower(),
            bool(optional.get("default_enabled", False)),
            bool(optional.get("recommended", False)),
            str(optional.get("performance_impact", "")),
            list(optional.get("conflicts", [])),
        )
        items = [item for item in self.files() if item.path != entry.path]
        action = "BUILD_FILE_UPDATED" if len(items) != len(self.files()) else "BUILD_FILE_ADDED"
        if entry.mod_id:
            items = [item for item in items if not (item.mod_id == entry.mod_id and item.path.startswith("mods/"))]
        items.append(entry)
        self._write_json_atomic(self.draft_dir / "files.json", [asdict(item) for item in items])
        self.audit(action, actor, {"path": entry.path, "sha256": entry.sha256})
        return entry

    def remove_file(self, destination: str, actor: str = "SYSTEM") -> None:
        items = self.files()
        kept = [item for item in items if item.path != destination]
        if len(kept) == len(items):
            raise KeyError(destination)
        self._write_json_atomic(self.draft_dir / "files.json", [asdict(item) for item in kept])
        self.audit("BUILD_FILE_REMOVED", actor, {"path": destination})

    def validate(self) -> list[str]:
        errors: list[str] = []
        files = self.files()
        paths, mod_ids = set(), set()
        for item in files:
            stored = self.draft_dir / "files" / item.stored_name
            if item.path in paths:
                errors.append(f"Duplicate destination: {item.path}")
            paths.add(item.path)
            if item.mod_id and item.mod_id in mod_ids:
                errors.append(f"Duplicate mod id: {item.mod_id}")
            if item.mod_id:
                mod_ids.add(item.mod_id)
            if not stored.is_file():
                errors.append(f"Missing file: {item.path}")
            elif stored.stat().st_size != item.size or sha256(stored) != item.sha256:
                errors.append(f"Invalid hash: {item.path}")
            if item.scope not in SCOPES or item.mode not in MODES:
                errors.append(f"Invalid scope/mode: {item.path}")
        for item in files:
            for dependency in item.dependencies:
                if dependency not in mod_ids and dependency not in {"minecraft", "neoforge", "java"}:
                    errors.append(f"Missing dependency {dependency} for {item.mod_id or item.path}")
        return errors

    def publish(self, notes: str, actor: str) -> Path:
        errors = self.validate()
        if errors:
            raise ValueError("\n".join(errors))
        metadata, files = self.metadata(), self.files()
        final = self.releases_dir / metadata.pack_version
        if final.exists():
            raise FileExistsError(f"Release {metadata.pack_version} already exists")
        stage = Path(tempfile.mkdtemp(prefix="publish-", dir=self.root))
        try:
            payload_dir = stage / "files"
            payload_dir.mkdir()
            manifest_files = []
            for item in files:
                shutil.copy2(self.draft_dir / "files" / item.stored_name, payload_dir / item.stored_name)
                if item.scope in {"CLIENT", "BOTH"}:
                    manifest_files.append(
                        {
                            "id": item.mod_id or item.sha256[:12],
                            "name": Path(item.path).name,
                            "version": item.mod_version,
                            "path": item.path,
                            "url": f"{self.public_base_url}/releases/{metadata.pack_version}/files/{item.stored_name}",
                            "size": item.size,
                            "sha256": item.sha256,
                            "type": self._file_type(item.path),
                            "mode": item.mode.lower(),
                            "required": item.mode == "REQUIRED",
                        }
                    )
            manifest = {
                "schemaVersion": 2,
                "status": "PUBLISHED",
                "pack": metadata.pack_name,
                "displayName": metadata.display_name,
                "seasonName": metadata.season_name,
                "version": metadata.pack_version,
                "minecraft": metadata.minecraft_version,
                "loader": metadata.loader,
                "loaderVersion": metadata.loader_version,
                "description": metadata.description,
                "logo": metadata.logo,
                "background": metadata.background,
                "minecraft_server": metadata.server_address,
                "maintenance": metadata.maintenance,
                "minimumLauncherVersion": metadata.minimum_launcher_version,
                "changelog": notes,
                "files": manifest_files,
                "publishedAt": int(time.time()),
                "publishedBy": actor,
            }
            manifest["optionalMods"] = [
                {
                    "id": item.mod_id or Path(item.path).stem.lower(),
                    "name": item.display_name or Path(item.path).stem,
                    "description": item.description,
                    "category": item.category,
                    "defaultEnabled": item.default_enabled,
                    "recommended": item.recommended,
                    "restartRequired": True,
                    "performanceImpact": item.performance_impact,
                    "dependencies": item.dependencies,
                    "conflicts": item.conflicts,
                    "minecraftVersion": metadata.minecraft_version,
                    "loader": metadata.loader,
                    "files": [item.path],
                }
                for item in files
                if item.scope in {"CLIENT", "BOTH"} and item.mode == "OPTIONAL"
            ]
            self._write_json(stage / "manifest.json", manifest)
            self._write_json(
                stage / "release.json",
                {
                    "metadata": asdict(metadata),
                    "notes": notes,
                    "author": actor,
                    "publishedAt": manifest["publishedAt"],
                    "filesChanged": len(files),
                },
            )
            os.replace(stage, final)
            self._write_json_atomic(self.current_dir / "manifest.json", manifest)
            self.audit("BUILD_PUBLISHED", actor, {"version": metadata.pack_version, "files": len(files)})
            return final / "manifest.json"
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise

    def history(self) -> list[dict]:
        out = []
        for path in self.releases_dir.glob("*/release.json"):
            out.append(self._read_json(path, {}))
        return sorted(out, key=lambda item: item.get("publishedAt", 0), reverse=True)

    def rollback(self, version: str, actor: str) -> None:
        manifest_path = self.releases_dir / version / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(version)
        manifest = self._read_json(manifest_path, {})
        self._write_json_atomic(self.current_dir / "manifest.json", manifest)
        self.audit("BUILD_ROLLBACK", actor, {"version": version})

    def audit(self, action: str, actor: str, detail: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.audit_file.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"time": int(time.time()), "action": action, "actor": actor, "detail": detail}, ensure_ascii=False
                )
                + "\n"
            )

    @staticmethod
    def _inspect_mod(path: Path) -> tuple[str, str, list[str]]:
        if path.suffix.lower() != ".jar":
            return "", "", []
        try:
            with zipfile.ZipFile(path) as archive:
                name = next(
                    (n for n in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml") if n in archive.namelist()), None
                )
                if not name:
                    return "", "", []
                text = archive.read(name).decode("utf-8", "replace")
            mod_id = next(iter(re.findall(r'^modId\s*=\s*["\']([^"\']+)', text, re.M)), "")
            version = next(iter(re.findall(r'^version\s*=\s*["\']([^"\']+)', text, re.M)), "")
            dependencies = re.findall(r'^modId\s*=\s*["\']([^"\']+)', text, re.M)[1:]
            return mod_id, version, sorted(set(dependencies))
        except (OSError, zipfile.BadZipFile):
            return "", "", []

    @staticmethod
    def _file_type(path: str) -> str:
        root = PurePosixPath(path).parts[0]
        return {
            "mods": "mod",
            "resourcepacks": "resourcepack",
            "shaderpacks": "shader",
            "kubejs": "kubejs",
            "config": "config",
        }.get(root, "other")

    @staticmethod
    def _read_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_json_atomic(self, path: Path, value) -> None:
        temp = path.with_suffix(path.suffix + ".part")
        self._write_json(temp, value)
        os.replace(temp, path)
