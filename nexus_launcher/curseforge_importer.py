from __future__ import annotations

from nexus_launcher.resource_limits import digest_file

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from nexus_launcher.curseforge_metadata import expected_file
from nexus_launcher.file_transaction import apply as apply_transaction
from nexus_launcher.file_transaction import recover as recover_transaction
from nexus_launcher.resource_limits import MAX_FILE_BYTES, copy_limited, ensure_space, read_limited, validate_archive
from nexus_launcher.native_zip import open_zip_entry
from nexus_launcher.safe_paths import checked_path, pinned_directory, relative_parts, remove_owned_tree, replace_file
from nexus_launcher.secure_http import open_https
from nexus_launcher.update_state import serialized

CURSEFORGE_HOSTS = {
    "www.curseforge.com",
    "curseforge.com",
    "mediafilez.forgecdn.net",
    "media.forgecdn.net",
    "edge.forgecdn.net",
}

DOWNLOAD_URL = "https://www.curseforge.com/api/v1/mods/{project}/files/{file}/download"
STATE_NAME = "nexus-pack-manifest.json"
PACK_FIXES = {
    "nexus-builder": {
        "replace": {(394468, 8382327): (394468, 6382649)},
        "add": [(257814, 7976316)],
    },
    "nexus-elderfall": {"remove": {(447673, 8403458)}},
    "nexus-pinewood": {"remove": {(455508, 7805348)}},
}


@dataclass(frozen=True)
class PackInfo:
    name: str
    minecraft_version: str
    loader: str
    loader_version: str
    recommended_memory_mb: int
    mod_count: int
    overrides: str


def sha256_file(path: Path) -> str:
    return digest_file(path)


def _safe_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/").rstrip("/")
    return PurePosixPath(*relative_parts(normalized))


def inspect_pack(archive_path: Path) -> tuple[PackInfo, dict]:
    with zipfile.ZipFile(archive_path) as archive:
        validate_archive(archive)
        for item in archive.infolist():
            _safe_path(item.filename)
        with archive.open("manifest.json") as source:
            payload = json.loads(read_limited(source))
    minecraft = payload["minecraft"]
    primary = next(
        (item["id"] for item in minecraft.get("modLoaders", []) if item.get("primary")),
        minecraft["modLoaders"][0]["id"],
    )
    loader, _, loader_version = primary.partition("-")
    return (
        PackInfo(
            str(payload.get("name", archive_path.stem)),
            str(minecraft["version"]),
            loader.lower(),
            loader_version,
            int(minecraft.get("recommendedRam", 4096 if loader == "neoforge" else 3072)),
            len(payload.get("files", [])),
            str(payload.get("overrides", "overrides")),
        ),
        payload,
    )


class CurseForgeImporter:
    def __init__(
        self,
        instance: Path,
        pack_id: str,
        log: Callable[[str], None] = print,
        progress: Callable[[int, int], None] = lambda *_: None,
    ):
        checked_path(instance, "probe")
        self.instance = instance.absolute()
        self.update_dir = self.instance / ".nexus-launcher"
        self.pack_id = pack_id
        self.log = log
        self.progress = progress

    @property
    def state_path(self) -> Path:
        return checked_path(self.instance, ".nexus-launcher/" + STATE_NAME)

    def _write_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="pack-state-", suffix=".tmp", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(state, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            replace_file(name, self.state_path)
        finally:
            Path(name).unlink(missing_ok=True)

    @serialized
    def verify(self) -> bool:
        recover_transaction(self.instance)
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return all(
                (target := checked_path(self.instance, item["path"])).is_file()
                and (
                    item["path"] == "options.txt"
                    or Path(item["path"]).parts[0] == "config"
                    or (target.stat().st_size == item["size"] and sha256_file(target) == item["sha256"])
                )
                for item in state["files"]
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False

    @serialized
    def repair_installed(self) -> None:
        """Migrate known-broken optional components without redownloading the pack."""
        recover_transaction(self.instance)
        removed = PACK_FIXES.get(self.pack_id, {}).get("remove", set())
        if not removed or not self.state_path.is_file():
            return
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        kept = []
        for item in state["files"]:
            source = item.get("source", {})
            if (source.get("projectId"), source.get("fileId")) not in removed:
                kept.append(item)
                continue
            relative = _safe_path(item["path"])
            target = checked_path(self.instance, relative.as_posix())
            if target.is_file():
                backup = (
                    self.instance / ".nexus-launcher" / "quarantine" / "pack-repair" / str(time.time_ns()) / target.name
                )
                backup.parent.mkdir(parents=True, exist_ok=True)
                replace_file(target, backup)
            self.log(f"Отключён несовместимый компонент: {target.name}")
        if len(kept) != len(state["files"]):
            state["files"] = kept
            self._write_state(state)

    @serialized
    def is_installed(self, archive_path: Path) -> bool:
        """Fast marker check for packs maintained by a later update manifest.

        The remote manifest may legitimately replace CurseForge base files, so
        their original hashes must not cause a complete base-pack download.
        """
        recover_transaction(self.instance)
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return state.get("id") == self.pack_id and state.get("sourceArchiveSha256") == sha256_file(archive_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    @serialized
    def quarantine_extra_mods(self) -> list[str]:
        recover_transaction(self.instance)
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            allowed = {
                Path(item["path"]).name.casefold()
                for item in state["files"]
                if Path(item["path"]).parts[:1] == ("mods",)
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []
        mods_dir = self.instance / "mods"
        extras = [jar for jar in mods_dir.glob("*.jar") if jar.name.casefold() not in allowed]
        if not extras:
            return []
        quarantine = self.instance / ".nexus-launcher" / "quarantine" / time.strftime("%Y%m%d-%H%M%S")
        quarantine.mkdir(parents=True, exist_ok=True)
        for jar in extras:
            replace_file(jar, quarantine / jar.name)
        self.log(f"Лишние моды перемещены в карантин: {len(extras)}")
        return [jar.name for jar in extras]

    @serialized
    def install(self, archive_path: Path, version: str = "0.1.0-test.1") -> dict:
        recover_transaction(self.instance)
        info, payload = inspect_pack(archive_path)
        parent = checked_path(self.instance.parent, ".staging")
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="import-", dir=parent))
        try:
            return self._install_staged(archive_path, version, info, payload, staging)
        finally:
            # Only this invocation's unique staging directory is ours to clean.
            remove_owned_tree(parent, staging.name)

    def _install_staged(self, archive_path, version, info, payload, staging) -> dict:
        records: list[dict] = []
        file_references = self._fixed_references(payload.get("files", []))
        total = len(file_references) + 1
        self.log(f"Импорт {info.name}: {info.mod_count} модов")
        for index, file_ref in enumerate(file_references, 1):
            record = self._download_mod(staging / "mods", file_ref)
            records.append(record)
            self.progress(index, total)
            self.log(f"Загрузка модов: {index} / {len(file_references)} — {Path(record['path']).name}")
        self._extract_overrides(archive_path, staging, info.overrides, records)
        self.progress(total, total)
        self._validate_jars(staging)
        state = {
            "schemaVersion": 1,
            "id": self.pack_id,
            "name": info.name,
            "version": version,
            "minecraft": {"version": info.minecraft_version},
            "loader": {"type": info.loader, "version": info.loader_version},
            "recommendedMemoryMb": info.recommended_memory_mb,
            "sourceArchiveSha256": sha256_file(archive_path),
            "installedAt": int(time.time()),
            "lastVerifiedAt": int(time.time()),
            "files": records,
        }
        self._apply(staging, records, state)
        self.log(f"Сборка {info.name} установлена")
        return state

    def _fixed_references(self, references: list[dict]) -> list[dict]:
        fixes = PACK_FIXES.get(self.pack_id, {})
        replacements = fixes.get("replace", {})
        result: list[dict] = []
        for reference in references:
            key = (int(reference["projectID"]), int(reference["fileID"]))
            if key in fixes.get("remove", set()):
                continue
            project_id, file_id = replacements.get(key, key)
            replaced = {**reference, "projectID": project_id, "fileID": file_id}
            if (project_id, file_id) != key:
                replaced.pop("sha256", None)  # The previous file's digest is not the replacement's.
            result.append(replaced)
        for project_id, file_id in fixes.get("add", []):
            result.append({"projectID": project_id, "fileID": file_id, "required": True})
        return result

    def _download_mod(self, mods_dir: Path, file_ref: dict) -> dict:
        project_id, file_id = int(file_ref["projectID"]), int(file_ref["fileID"])
        if project_id <= 0 or file_id <= 0:
            raise ValueError("Некорректный CurseForge ID")
        expected = file_ref.get("sha256", "")
        if expected and (not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected)):
            raise ValueError("Некорректный ожидаемый SHA-256 CurseForge")
        url = DOWNLOAD_URL.format(project=project_id, file=file_id)
        mods_dir.mkdir(parents=True, exist_ok=True)
        ensure_space(mods_dir, MAX_FILE_BYTES)
        last_error: Exception | None = None
        for attempt in range(3):
            temporary = None
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "NEXUS-Launcher/0.5"})
                with open_https(request, timeout=60, allowed_hosts=CURSEFORGE_HOSTS) as response:
                    filename = urllib.parse.unquote(Path(urllib.parse.urlparse(response.geturl()).path).name)
                    if any(char in filename for char in "/\\:") or filename in {"", ".", ".."}:
                        raise ValueError("Небезопасное имя загружаемого файла")
                    if not filename.lower().endswith((".jar", ".zip")):
                        raise ValueError(f"CurseForge вернул неподдерживаемый файл для fileID {file_id}")
                    metadata = None
                    if not expected:
                        metadata = expected_file(project_id, file_id, os.environ.get("NEXUS_CURSEFORGE_API_KEY", ""))
                        if metadata["name"] != filename:
                            raise ValueError("Имя файла не совпадает с CurseForge metadata")
                    target = checked_path(mods_dir, filename)
                    fd, name = tempfile.mkstemp(prefix="curseforge-", suffix=".part", dir=mods_dir)
                    temporary = Path(name)
                    with os.fdopen(fd, "wb") as output:
                        copy_limited(response, output)
                if temporary.stat().st_size == 0 or not zipfile.is_zipfile(temporary):
                    raise ValueError(f"Повреждённый JAR: {filename}")
                if expected and sha256_file(temporary) != expected.lower():
                    raise ValueError("CurseForge SHA-256 mismatch")
                if metadata:
                    with temporary.open("rb") as source:
                        actual_sha1 = hashlib.file_digest(source, "sha1").hexdigest()
                    if temporary.stat().st_size != metadata["size"] or actual_sha1 != metadata["sha1"]:
                        raise ValueError("CurseForge metadata integrity mismatch")
                with zipfile.ZipFile(temporary) as archive:
                    validate_archive(archive)
                if filename.lower().endswith(".zip"):
                    with zipfile.ZipFile(temporary) as archive:
                        validate_archive(archive)
                        names = {name.replace("\\", "/") for name in archive.namelist()}
                    files = [name for name in names if not name.endswith("/")]
                    prefix = ""
                    while files and all("/" in name for name in files):
                        roots = {name.split("/")[0] for name in files}
                        if len(roots) != 1 or next(iter(roots)) in {"shaders", "assets"}:
                            break
                        part = next(iter(roots)) + "/"
                        prefix += part
                        files = [name[len(part) :] for name in files]
                    nested_shader = bool(prefix and any(name.startswith(prefix + "shaders/") for name in names))
                    if "pack.mcmeta" in names:
                        directory = "resourcepacks"
                    elif any(name.startswith("shaders/") for name in names) or nested_shader:
                        directory = "shaderpacks"
                    else:
                        raise ValueError(f"Неизвестный тип ZIP CurseForge: {filename}")
                    if nested_shader:
                        fd, name = tempfile.mkstemp(prefix="normalize-", suffix=".zip", dir=mods_dir)
                        os.close(fd)
                        normalized = Path(name)
                        try:
                            with (
                                zipfile.ZipFile(temporary) as source,
                                zipfile.ZipFile(normalized, "w", zipfile.ZIP_DEFLATED) as output,
                            ):
                                for item in source.infolist():
                                    if item.is_dir() or not item.filename.replace("\\", "/").startswith(prefix):
                                        continue
                                    relative = _safe_path(item.filename.replace("\\", "/")[len(prefix) :])
                                    with source.open(item) as src, output.open(relative.as_posix(), "w") as dest:
                                        copy_limited(src, dest, item.file_size)
                            replace_file(normalized, temporary)
                        finally:
                            normalized.unlink(missing_ok=True)
                    target = checked_path(mods_dir.parent, f"{directory}/{filename}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                target = checked_path(mods_dir.parent, target.relative_to(mods_dir.parent).as_posix())
                replace_file(temporary, target)
                return {
                    "path": target.relative_to(mods_dir.parent).as_posix(),
                    "size": target.stat().st_size,
                    "sha256": sha256_file(target),
                    "source": {"type": "curseforge", "projectId": project_id, "fileId": file_id},
                }
            except Exception as error:
                last_error = error
                if temporary is not None:
                    checked_path(mods_dir, temporary.name).unlink(missing_ok=True)
                if attempt < 2:
                    time.sleep(1 + attempt * 2)
        raise RuntimeError(f"Не удалось загрузить CurseForge fileID {file_id}: {last_error}") from last_error

    def _extract_overrides(self, archive_path: Path, staging: Path, root: str, records: list[dict]) -> None:
        prefix = root.strip("/\\") + "/"
        with zipfile.ZipFile(archive_path) as archive:
            ensure_space(staging, validate_archive(archive))
            for item in archive.infolist():
                normalized = item.filename.replace("\\", "/")
                if item.is_dir() or not normalized.startswith(prefix):
                    continue
                relative = _safe_path(normalized[len(prefix) :])
                target = checked_path(staging, relative.as_posix())
                with pinned_directory(target.parent, create=True):
                    with open_zip_entry(archive, item) as source, target.open("xb") as output:
                        copy_limited(source, output, item.file_size)
                records.append(
                    {
                        "path": relative.as_posix(),
                        "size": target.stat().st_size,
                        "sha256": sha256_file(target),
                        "source": {"type": "override"},
                    }
                )

    def _validate_jars(self, staging: Path) -> None:
        seen: set[str] = set()
        for jar in (staging / "mods").glob("*.jar"):
            key = jar.name.casefold()
            if key in seen:
                raise ValueError(f"Дублирующийся JAR: {jar.name}")
            seen.add(key)
            if jar.stat().st_size == 0 or not zipfile.is_zipfile(jar):
                raise ValueError(f"Повреждённый JAR: {jar.name}")

    def _apply(self, staging: Path, records: list[dict], state=None) -> None:
        self.instance.mkdir(parents=True, exist_ok=True)
        previous: set[str] = set()
        try:
            previous = {item["path"] for item in json.loads(self.state_path.read_text(encoding="utf-8"))["files"]}
        except FileNotFoundError:
            pass
        current = {item["path"] for item in records}
        for relative in previous | current:
            checked_path(self.instance, relative)
        for relative in current:
            checked_path(staging, relative)
        replacements = [
            item for item in records if item["path"] != "options.txt" or not (self.instance / "options.txt").is_file()
        ]
        apply_transaction(
            self.instance,
            staging,
            replacements,
            sorted(previous - current - {"options.txt"}),
            ".nexus-launcher/" + STATE_NAME,
            state if state is not None else {"files": records},
        )
