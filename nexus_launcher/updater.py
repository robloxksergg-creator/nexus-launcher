from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from nexus_launcher.file_transaction import apply as apply_transaction
from nexus_launcher.file_transaction import recover as recover_transaction
from nexus_launcher.resource_limits import copy_limited, digest_limited, ensure_space, validate_archive
from nexus_launcher.safe_paths import (
    atomic_copy,
    checked_path,
    checked_tree,
    pinned_directory,
    relative_parts,
    remove_owned_tree,
    replace_file,
    unlink_file,
    validate_paths,
)
from nexus_launcher.secure_http import origin
from nexus_launcher.native_http import open_https
from nexus_launcher.update_state import serialized, update_lock
from nexus_launcher.native_transfer import TransferVerifier
from nexus_launcher.native_zip import open_zip_entry
import nexus_launcher.build_channel as build_channel

ALLOWED_ROOTS = {"mods", "config", "defaultconfigs", "kubejs", "resourcepacks", "shaderpacks", "libraries", "tacz", "nexus-rc-version.txt"}
FILE_TYPES = {"mod", "config", "resourcepack", "shader", "kubejs", "library", "other"}
MAX_PACK_BYTES = 1024 * 1024 * 1024
STATE_DIR = ".nexus-launcher"
MANIFEST_SCHEMA_VERSIONS = {1, 2}
FILE_MODES = {"required", "optional", "preserve"}
TRUSTED_DOWNLOAD_HOSTS = {
    "nexusmc.flux-productions.com",
    "nexusmc-site.robloxksergg.workers.dev",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
STAGING_DOWNLOAD_HOST = "nexusmc-control-plane-staging.robloxksergg.workers.dev"


def trusted_download_hosts() -> set[str]:
    hosts = set(TRUSTED_DOWNLOAD_HOSTS)
    if build_channel.STAGING_BUILD:
        hosts.add(STAGING_DOWNLOAD_HOST)
    return hosts
DOWNLOAD_ATTEMPTS = 3


class InstallState(StrEnum):
    NOT_INSTALLED = "NOT_INSTALLED"
    CHECKING = "CHECKING"
    PREPARING = "PREPARING"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    APPLYING = "APPLYING"
    FINALIZING = "FINALIZING"
    READY = "READY"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    FAILED = "FAILED"
    RUNNING = "RUNNING"


@dataclass(frozen=True)
class InstallSnapshot:
    state: InstallState
    operation_id: str = ""
    instance_id: str = ""
    current_file: str = ""
    bytes_done: int = 0
    bytes_total: int | None = None
    error_kind: str = ""
    error: str = ""
    updated_at: int = 0


@dataclass(frozen=True)
class DownloadProgress:
    operation_id: str
    instance_id: str
    phase: str
    current_file: str | None
    bytes_done: int
    bytes_total: int | None
    sampled_at: float
    attempt: int = 1


@dataclass(frozen=True)
class RepairResult:
    checked: int
    repaired: int
    downloaded: int


@dataclass(frozen=True)
class PackFile:
    id: str
    name: str
    version: str
    path: str
    url: str
    size: int
    sha256: str
    required: bool = True
    type: str = "other"
    mode: str = "required"


@dataclass(frozen=True)
class OptionalMod:
    id: str
    name: str
    description: str = ""
    category: str = "other"
    recommended: bool = False
    default_enabled: bool = False
    restart_required: bool = True
    performance_impact: str = ""
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    conflicts: tuple[str, ...] = field(default_factory=tuple)
    minecraft_version: str = ""
    loader: str = ""
    minimum_ram: int = 0
    recommended_ram: int = 0
    files: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PackRelease:
    version: str
    url: str
    sha256: str
    changelog: str = ""
    minecraft_server: str = ""
    pack: str = ""
    minecraft: str = ""
    loader: str = ""
    loader_version: str = ""
    visibility: str = "public"
    maintenance: bool = False
    files: tuple[PackFile, ...] = field(default_factory=tuple)
    display_name: str = ""
    season_name: str = ""
    description: str = ""
    logo: str = ""
    background: str = ""
    minimum_launcher_version: str = ""
    optional_mods: tuple[OptionalMod, ...] = field(default_factory=tuple)


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        # Preserve the legacy helper's file-size range; transport/extraction
        # enforce their own limits. Only memory and elapsed work are bounded here.
        return digest_limited(source, "sha256", limit=(1 << 64) - 1)


def fetch_manifest(url: str) -> PackRelease | None:
    origin(url)
    manifest_parts = urllib.parse.urlparse(url)
    if manifest_parts.scheme != "https" or not manifest_parts.hostname:
        raise ValueError("Manifest должен загружаться по HTTPS")
    candidates = [url]
    if manifest_parts.hostname == "nexusmc-site.robloxksergg.workers.dev":
        candidates.append(url.replace("nexusmc-site.robloxksergg.workers.dev", "nexusmc.flux-productions.com", 1))
    elif manifest_parts.hostname == "nexusmc.flux-productions.com":
        candidates.append(url.replace("nexusmc.flux-productions.com", "nexusmc-site.robloxksergg.workers.dev", 1))
    payload = None
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            request = urllib.request.Request(
                candidate, headers={"User-Agent": "NexusLauncher/1.0", "Accept": "application/json"}
            )
            with open_https(
                request, timeout=15, allowed_hosts=TRUSTED_DOWNLOAD_HOSTS | {manifest_parts.hostname}
            ) as response:
                if int(response.headers.get("Content-Length", "0")) > 1024 * 1024:
                    raise ValueError("Манифест слишком большой")
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError("Манифест слишком большой")
                payload = json.loads(raw)
            break
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
    if payload is None:
        assert last_error is not None
        raise last_error
    server = str(payload.get("minecraft_server", payload.get("server", ""))).strip()
    schema_version = int(payload.get("schemaVersion", 1))
    if schema_version not in MANIFEST_SCHEMA_VERSIONS:
        raise ValueError(f"Неподдерживаемая версия manifest: {schema_version}")
    files: list[PackFile] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(payload.get("files", [])):
        if not isinstance(item, dict):
            raise ValueError("Запись файла в manifest должна быть объектом")
        path = str(item.get("path", "")).replace("\\", "/")
        safe = _safe_member(path)
        if safe is None or safe.as_posix() != path.lstrip("/"):
            raise ValueError(f"Недопустимый путь файла: {path}")
        normalized_path = safe.as_posix()
        relative_parts(normalized_path)
        if normalized_path.casefold() in seen_paths:
            raise ValueError(f"Повторяющийся путь в manifest: {normalized_path}")
        seen_paths.add(normalized_path.casefold())
        digest = str(item.get("sha256", "")).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"Некорректный SHA-256: {path}")
        download_url = str(item.get("url", ""))
        download_parts = urllib.parse.urlparse(download_url)
        if download_parts.scheme != "https" or not download_parts.hostname:
            raise ValueError(f"Файл должен скачиваться по HTTPS: {path}")
        allowed_hosts = trusted_download_hosts() | {manifest_parts.hostname.lower()}
        if download_parts.hostname.lower() not in allowed_hosts:
            raise ValueError(f"Недоверенный сервер загрузки: {download_parts.hostname}")
        file_type = str(item.get("type", "other")).lower()
        if file_type not in FILE_TYPES:
            raise ValueError(f"Неизвестный тип файла: {file_type}")
        size = int(item.get("size", 0))
        if size < 0 or size > MAX_PACK_BYTES:
            raise ValueError(f"Некорректный размер файла: {path}")
        mode = str(item.get("mode", "required" if item.get("required", True) else "optional")).lower()
        if mode not in FILE_MODES:
            raise ValueError(f"Неизвестный режим файла: {mode}")
        files.append(
            PackFile(
                str(item.get("id", index)),
                str(item.get("name", Path(path).name)),
                str(item.get("version", "")),
                path,
                download_url,
                size,
                digest,
                mode == "required",
                file_type,
                mode,
            )
        )
    optional_mods: list[OptionalMod] = []
    for item in payload.get("optionalMods", []):
        if not isinstance(item, dict) or not str(item.get("id", "")).strip():
            raise ValueError("Optional mod должен иметь id")
        optional_mods.append(
            OptionalMod(
                str(item["id"]).strip().lower(),
                str(item.get("name", item["id"])),
                str(item.get("description", "")),
                str(item.get("category", "other")).lower(),
                bool(item.get("recommended", False)),
                bool(item.get("defaultEnabled", False)),
                bool(item.get("restartRequired", True)),
                str(item.get("performanceImpact", "")),
                tuple(str(x).lower() for x in item.get("dependencies", [])),
                tuple(str(x).lower() for x in item.get("conflicts", [])),
                str(item.get("minecraftVersion", "")),
                str(item.get("loader", "")).lower(),
                int(item.get("minimumRam", 0)),
                int(item.get("recommendedRam", 0)),
                tuple(str(x) for x in item.get("files", [])),
            )
        )
    optional_paths = {path for mod in optional_mods for path in mod.files}
    for entry in files:
        if entry.mode == "optional" and entry.path not in optional_paths:
            optional_mods.append(OptionalMod(entry.id.lower(), entry.name, files=(entry.path,)))
    version = str(payload.get("version", "")).strip()
    if files:
        if not version:
            raise ValueError("В manifest нет версии сборки")
        return PackRelease(
            version,
            "",
            "",
            str(payload.get("changelog", "")),
            server,
            str(payload.get("pack", "")),
            str(payload.get("minecraft", "")),
            str(payload.get("loader", "")).lower(),
            str(payload.get("loaderVersion", payload.get("loader_version", ""))),
            str(payload.get("visibility", "public")),
            bool(payload.get("maintenance", False)),
            tuple(files),
            str(payload.get("displayName", "")),
            str(payload.get("seasonName", "")),
            str(payload.get("description", "")),
            str(payload.get("logo", "")),
            str(payload.get("background", "")),
            str(payload.get("minimumLauncherVersion", "")),
            tuple(optional_mods),
        )
    if not all(payload.get(key) for key in ("version", "url", "sha256")):
        return None
    digest = str(payload["sha256"]).lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("В манифесте некорректный SHA-256")
    download_url = str(payload["url"])
    if not download_url.startswith("https://"):
        raise ValueError("Сборка должна скачиваться только по HTTPS")
    return PackRelease(str(payload["version"]), download_url, digest, str(payload.get("changelog", "")), server)


def _safe_member(name: str) -> PurePosixPath | None:
    clean = name.replace("\\", "/")
    if clean.startswith("/") or ":" in clean or "\x00" in clean:
        raise ValueError(f"Опасный путь в архиве: {name}")
    path = PurePosixPath(clean)
    if not clean or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Опасный путь в архиве: {name}")
    if path.parts[0] in ALLOWED_ROOTS:
        return path
    if clean in {".nexusbot-delete.txt", ".nexusbot-pack.json", ".nexusbot-optional-mods.txt"}:
        return path
    return None


class ModpackUpdater:
    def __init__(
        self, game_dir: Path, log: Callable[[str], None] = print, progress: Callable[[int, int], None] = lambda *_: None,
        progress_event: Callable[[DownloadProgress], None] = lambda *_: None, *, instance_id: str = ""
    ):
        checked_path(game_dir, "probe")
        self.game_dir = game_dir.absolute()
        self.state_dir = self.game_dir / STATE_DIR
        self.update_dir = self.state_dir
        self.log = log
        self.progress = progress
        self.progress_event = progress_event
        self.operation_id = str(uuid.uuid4())
        self.instance_id = instance_id
        raw_log = self.log
        self.log = lambda message: raw_log(f"[{self.operation_id}] {message}")
        if self.transaction_path.exists() or self._path(".nexus-launcher/file-transaction").exists():
            with update_lock(self.update_dir):
                recover_transaction(self.game_dir)
                self._recover_incomplete_update()
        previous_delivery = self.delivery_snapshot()
        if previous_delivery.state in {InstallState.DOWNLOADING, InstallState.VERIFYING, InstallState.PREPARING}:
            self.operation_id = previous_delivery.operation_id or self.operation_id

    def _path(self, relative: str) -> Path:
        return checked_path(self.game_dir, relative)

    def _emit_progress(self, phase, current_file, done, total, attempt=1):
        phase_state = {
            "download": InstallState.DOWNLOADING,
            "downloading": InstallState.DOWNLOADING,
            "verifying": InstallState.VERIFYING,
            "applying": InstallState.APPLYING,
            "finalizing": InstallState.FINALIZING,
            "complete": InstallState.READY,
            "ready": InstallState.READY,
        }.get(str(phase).lower())
        if phase_state:
            self._set_delivery(phase_state, current_file or "", done, total if total > 0 else None)
        self.progress(done, total or max(done, 1))
        self.progress_event(DownloadProgress(self.operation_id, self.instance_id, phase, current_file,
                                             done, total if total > 0 else None, time.monotonic(), attempt))

    @property
    def delivery_path(self) -> Path:
        return self._path(STATE_DIR + "/delivery-state.json")

    def _set_delivery(self, state: InstallState, current_file: str = "", done: int = 0,
                      total: int | None = None, error_kind: str = "", error: str = "") -> InstallSnapshot:
        snapshot = InstallSnapshot(state, self.operation_id, self.instance_id, current_file, max(0, done),
                                   total if total and total > 0 else None, error_kind, error, int(time.time()))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._durable_json(STATE_DIR + "/delivery-state.json", {
            "state": snapshot.state.value, "operation_id": snapshot.operation_id,
            "instance_id": snapshot.instance_id, "current_file": snapshot.current_file,
            "bytes_done": snapshot.bytes_done, "bytes_total": snapshot.bytes_total,
            "error_kind": snapshot.error_kind, "error": snapshot.error, "updated_at": snapshot.updated_at,
        })
        return snapshot

    def delivery_snapshot(self) -> InstallSnapshot:
        try:
            raw = json.loads(self.delivery_path.read_text(encoding="utf-8"))
            state = InstallState(str(raw.get("state", InstallState.NOT_INSTALLED)))
            # Applying cannot be resumed. Constructor rollback makes the previous version authoritative.
            if state in {InstallState.APPLYING, InstallState.FINALIZING} and not self.transaction_path.exists():
                state = InstallState.READY if self.installed_version else InstallState.NOT_INSTALLED
            return InstallSnapshot(state, str(raw.get("operation_id", "")), str(raw.get("instance_id", "")),
                                   str(raw.get("current_file", "")), int(raw.get("bytes_done", 0)),
                                   int(raw["bytes_total"]) if raw.get("bytes_total") else None,
                                   str(raw.get("error_kind", "")), str(raw.get("error", "")), int(raw.get("updated_at", 0)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return InstallSnapshot(InstallState.NOT_INSTALLED, instance_id=self.instance_id)

    def mark_running(self, running: bool) -> InstallSnapshot:
        return self._set_delivery(InstallState.RUNNING if running else InstallState.READY)

    @staticmethod
    def classify_error(error: Exception) -> str:
        text = str(error).lower()
        if any(word in text for word in ("sha", "hash", "повреж", "размер файла")):
            return "integrity"
        if any(word in text for word in ("space", "мест", "disk")):
            return "storage"
        if isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError)):
            return "network"
        if isinstance(error, PermissionError):
            return "permission"
        return "internal"

    def _stage_path(self, release: PackRelease, entry: PackFile) -> Path:
        """A stable, hash-bound path makes an interrupted transfer recoverable."""
        relative_parts(entry.path)
        version_key = hashlib.sha256(f"{release.version}\0{entry.sha256}".encode()).hexdigest()[:24]
        return self._path(f"{STATE_DIR}/staging/{version_key}/{entry.path}.part")

    def _validate_state(self, state: dict) -> dict:
        if not isinstance(state, dict):
            raise ValueError("Invalid pack state")
        managed = state.get("managed_files", {})
        if not isinstance(managed, dict):
            raise ValueError("Invalid managed inventory")
        validate_paths(self.game_dir, managed, ALLOWED_ROOTS)
        validate_paths(self.game_dir, state.get("preserved_files", []), ALLOWED_ROOTS)
        for item in state.get("optional_catalog", []):
            if not isinstance(item, dict):
                raise ValueError("Invalid optional inventory")
            validate_paths(self.game_dir, item.get("files", []), ALLOWED_ROOTS)
        for name in state.get("optional_mods", []):
            if len(relative_parts(name)) != 1:
                raise ValueError("Invalid optional mod filename")
        return state

    @property
    def installed_version(self) -> str:
        try:
            return str(self._read_state().get("version", ""))
        except (OSError, json.JSONDecodeError):
            return ""

    def download(self, release: PackRelease) -> Path:
        relative_parts("pack-" + release.version + ".zip")
        if len(release.sha256) != 64 or any(c not in "0123456789abcdef" for c in release.sha256):
            raise ValueError("Missing valid pack SHA-256")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        target = self._path(STATE_DIR + f"/pack-{release.version}.zip")
        ensure_space(self.state_dir, MAX_PACK_BYTES)
        fd, temp_name = tempfile.mkstemp(prefix="pack-", suffix=".part", dir=self.state_dir)
        temporary = Path(temp_name)
        request = urllib.request.Request(release.url, headers={"User-Agent": "NexusLauncher/1.0"})
        try:
            with (
                os.fdopen(fd, "wb") as output,
                open_https(request, timeout=60, allowed_hosts=trusted_download_hosts()) as response,
            ):
                total = int(response.headers.get("Content-Length", "0"))
                if total > MAX_PACK_BYTES:
                    raise ValueError("Сборка больше допустимого размера 1 ГБ")
                done = 0
                deadline = time.monotonic() + 300
                while block := getattr(response, "read1", response.read)(1024 * 1024):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Pack download deadline exceeded")
                    done += len(block)
                    if done > MAX_PACK_BYTES:
                        raise ValueError("Сборка больше допустимого размера 1 ГБ")
                    output.write(block)
                    self._emit_progress("download", release.pack or None, done, total)
            if sha256_file(temporary) != release.sha256:
                raise ValueError("SHA-256 сборки не совпадает. Обновление отменено.")
            replace_file(temporary, self._path(target.relative_to(self.game_dir).as_posix()))
            return target
        finally:
            temporary.unlink(missing_ok=True)

    def apply(self, archive_path: Path, release: PackRelease) -> None:
        self._read_state()  # Reject a corrupt inventory before any mutation.
        self.log(f"Устанавливаю сборку {release.version}…")
        self.game_dir.mkdir(parents=True, exist_ok=True)
        managed_files: dict[str, str] = {}
        optional_mods: set[str] = set()
        with tempfile.TemporaryDirectory(prefix="nexus-update-") as temporary_name:
            staging = Path(temporary_name)
            with zipfile.ZipFile(archive_path) as archive:
                ensure_space(self.game_dir, 2 * validate_archive(archive))
                validate_paths(
                    self.game_dir,
                    [
                        safe.as_posix()
                        for item in archive.infolist()
                        if not item.is_dir()
                        and (safe := _safe_member(item.filename))
                        and safe.parts[0] in ALLOWED_ROOTS
                    ],
                    ALLOWED_ROOTS,
                )
                total_unpacked = sum(member.file_size for member in archive.infolist())
                if total_unpacked > 3 * MAX_PACK_BYTES:
                    raise ValueError("Распакованный архив слишком большой")
                for member in archive.infolist():
                    safe = _safe_member(member.filename)
                    if safe and not member.is_dir():
                        target = checked_path(staging, safe.as_posix())
                        with pinned_directory(target.parent, create=True):
                            with open_zip_entry(archive, member) as source, target.open("xb") as output:
                                copy_limited(source, output, member.file_size)

            delete_file = staging / ".nexusbot-delete.txt"
            delete_paths: list[PurePosixPath] = []
            if delete_file.is_file():
                for line in delete_file.read_text(encoding="utf-8-sig").splitlines():
                    if line.strip():
                        safe = _safe_member(line.strip())
                        if safe and safe.parts[0] in ALLOWED_ROOTS:
                            delete_paths.append(safe)

            optional_file = staging / ".nexusbot-optional-mods.txt"
            if optional_file.is_file():
                optional_mods = {
                    Path(line.strip()).name.lower()
                    for line in optional_file.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                }

            for root in ALLOWED_ROOTS:
                for source in (staging / root).rglob("*"):
                    if source.is_file():
                        managed_files[source.relative_to(staging).as_posix()] = sha256_file(source)
            state = {
                "version": release.version,
                "sha256": release.sha256,
                "url": release.url,
                "managed_files": managed_files,
                "optional_mods": sorted(optional_mods),
            }
            apply_transaction(
                self.game_dir,
                staging,
                [{"path": p, "sha256": h} for p, h in managed_files.items()],
                [p.as_posix() for p in delete_paths],
                STATE_DIR + "/pack.json",
                state,
            )
        self.audit_managed_files()
        self.log(f"Сборка {release.version} установлена")

    def audit_managed_files(self) -> dict[str, list[str]]:
        """Validate official files without modifying user-owned additions."""
        try:
            state = self._validate_state(json.loads(self._path(STATE_DIR + "/pack.json").read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {"missing": [], "changed": [], "extras": []}
        managed = {str(path): str(digest) for path, digest in state.get("managed_files", {}).items()}
        optional = {str(name).lower() for name in state.get("optional_mods", [])}
        missing: list[str] = []
        changed: list[str] = []
        for relative, digest in managed.items():
            target = self._path(relative)
            if not target.is_file():
                missing.append(relative)
            elif sha256_file(target) != digest:
                changed.append(relative)
        managed_mods = {Path(path).name.lower() for path in managed if Path(path).parts[:1] == ("mods",)}
        extras: list[str] = []
        mods = self.game_dir / "mods"
        if managed and mods.is_dir():
            for candidate in mods.glob("*.jar"):
                if candidate.name.lower() not in managed_mods | optional:
                    extras.append(f"mods/{candidate.name}")
        if extras:
            self.log(f"Обнаружены пользовательские моды (сохранены): {len(extras)}")
        return {"missing": missing, "changed": changed, "extras": extras}

    @serialized
    def update_if_needed(self, manifest_url: str, force: bool = False) -> PackRelease | None:
        recover_transaction(self.game_dir)
        self._recover_incomplete_update()
        self._set_delivery(InstallState.CHECKING)
        self.log("Получение manifest…")
        try:
            release = fetch_manifest(manifest_url)
        except Exception as error:
            if self.can_launch_offline():
                self._set_delivery(InstallState.READY)
            else:
                self._set_delivery(InstallState.FAILED, error_kind=self.classify_error(error), error=str(error))
            raise
        if not release:
            return release
        if release.files:
            self._sync_files(release, force)
            return release
        if not force and release.version == self.installed_version:
            audit = self.audit_managed_files()
            state_path = self.state_dir / "pack.json"
            try:
                has_inventory = bool(json.loads(state_path.read_text(encoding="utf-8")).get("managed_files"))
            except (OSError, json.JSONDecodeError):
                has_inventory = False
            if has_inventory and not audit["missing"] and not audit["changed"]:
                self.log("Сборка проверена — все моды актуальны")
                self._set_delivery(InstallState.READY)
                return release
            cached = self.state_dir / f"pack-{release.version}.zip"
            archive = cached if cached.is_file() and sha256_file(cached) == release.sha256 else self.download(release)
            self.log("Восстанавливаю отсутствующие или изменённые файлы сборки…")
            self.apply(archive, release)
            return release
        archive = self.download(release)
        self.apply(archive, release)
        return release

    def _read_state(self) -> dict:
        try:
            return self._validate_state(json.loads(self._path(STATE_DIR + "/pack.json").read_text(encoding="utf-8")))
        except FileNotFoundError:
            return {}

    @property
    def optional_state_path(self) -> Path:
        return self._path(STATE_DIR + "/optional-mods.json")

    def optional_selections(self) -> dict[str, bool]:
        try:
            payload = json.loads(self.optional_state_path.read_text(encoding="utf-8"))
            return {str(key).lower(): bool(value) for key, value in payload.items()}
        except (OSError, json.JSONDecodeError):
            return {}

    def optional_catalog(self) -> list[dict]:
        return list(self._read_state().get("optional_catalog", []))

    def set_optional_enabled(self, mod_id: str, enabled: bool) -> None:
        mod_id = mod_id.strip().lower()
        catalog = {str(item.get("id", "")).lower(): item for item in self.optional_catalog()}
        if mod_id not in catalog:
            raise ValueError(f"Неизвестный optional mod: {mod_id}")
        selections = self.optional_selections()
        if enabled:
            conflicts = [
                item for item in catalog[mod_id].get("conflicts", []) if selections.get(str(item).lower(), False)
            ]
            if conflicts:
                raise ValueError("Несовместимо с: " + ", ".join(conflicts))
            missing = [
                item
                for item in catalog[mod_id].get("dependencies", [])
                if item in catalog and not selections.get(str(item).lower(), False)
            ]
            if missing:
                raise ValueError("Сначала включите: " + ", ".join(missing))
        selections[mod_id] = enabled
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._durable_json(STATE_DIR + "/optional-mods.json", selections)

    @property
    def transaction_path(self) -> Path:
        return self._path(STATE_DIR + "/update-transaction.json")

    def _write_transaction(self, changed: list[str], removed: list[str]) -> None:
        validate_paths(self.game_dir, changed + removed, ALLOWED_ROOTS)
        transaction = {
            "schema": 2,
            "phase": "installing",
            "previous_state": self._read_state(),
            "files": [
                {"path": relative, "existed_before": self._path(relative).is_file(), "phase": "pending"}
                for relative in changed + removed
            ],
        }
        self._save_transaction(transaction)

    def _durable_json(self, relative: str, payload: dict) -> None:
        target = self._path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="journal-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            replace_file(temporary, self._path(relative))
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _save_transaction(self, transaction: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._durable_json(STATE_DIR + "/update-transaction.json", transaction)

    def _prepare_transaction_file(self, relative: str) -> None:
        transaction = json.loads(self.transaction_path.read_text(encoding="utf-8"))
        item = next(item for item in transaction["files"] if item["path"] == relative)
        if item["existed_before"]:
            source = self._path(relative)
            backup = self._path(STATE_DIR + "/backup-files/" + relative)
            backup.parent.mkdir(parents=True, exist_ok=True)
            atomic_copy(source, backup)
            item["backup_sha256"] = sha256_file(backup)
        item["phase"] = "prepared"
        self._save_transaction(transaction)

    def _recover_incomplete_update(self) -> None:
        transaction_path = self._path(STATE_DIR + "/update-transaction.json")
        if not transaction_path.is_file():
            return
        self.log("ROLLING_BACK • обнаружено незавершённое обновление")
        try:
            transaction = json.loads(self.transaction_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Cannot safely recover invalid update journal") from error
        if not isinstance(transaction, dict):
            raise ValueError("Invalid update journal")
        modern = transaction.get("schema") == 2
        items = (
            transaction.get("files", [])
            if modern
            else [
                {"path": path, "phase": "legacy", "existed_before": True}
                for path in transaction.get("changed", []) + transaction.get("removed", [])
            ]
        )
        validate_paths(self.game_dir, [item["path"] for item in items], ALLOWED_ROOTS)
        if not modern:
            previous_hashes = self._read_state().get("managed_files", {})
            for item in items:
                expected = previous_hashes.get(item["path"], "")
                if not isinstance(expected, str) or len(expected) != 64:
                    raise ValueError("Legacy journal lacks verified backups; installation retained for manual repair")
                item["phase"] = "prepared"
                item["backup_sha256"] = expected
        if modern:
            self._validate_state(transaction.get("previous_state"))
        # Validate the complete journal and every needed backup BEFORE writes.
        for item in items:
            if (
                item.get("phase") not in {"pending", "prepared", "legacy"}
                or type(item.get("existed_before")) is not bool
            ):
                raise ValueError("Invalid update phase")
            backup = self._path(STATE_DIR + "/backup-files/" + item["path"])
            if item["phase"] == "prepared" and item["existed_before"]:
                if not backup.is_file() or sha256_file(backup) != item.get("backup_sha256"):
                    raise ValueError("Recovery backup missing or corrupt; original files retained")
        for item in items:
            if item["phase"] == "pending":
                continue
            relative = item["path"]
            target = self._path(relative)
            backup = self._path(STATE_DIR + "/backup-files/" + relative)
            if backup.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_copy(backup, target, expected_sha256=item.get("backup_sha256"))
            elif modern and not item["existed_before"]:
                unlink_file(target, missing_ok=True)
        if modern:
            self._durable_json(STATE_DIR + "/pack.json", transaction["previous_state"])
        self._path(STATE_DIR + "/update-transaction.json").unlink(missing_ok=True)
        self.log("ROLLING_BACK • предыдущая сборка восстановлена")

    def can_launch_offline(self) -> bool:
        state = self._read_state()
        if (
            not state.get("last_successful_update")
            or self.transaction_path.exists()
            or self._path(".nexus-launcher/file-transaction").exists()
        ):
            return False
        managed = state.get("managed_files", {})
        if not managed:
            return False
        return all(
            self._path(relative).is_file() and sha256_file(self._path(relative)) == digest
            for relative, digest in managed.items()
        )

    def _download_file(self, entry: PackFile, temporary: Path, transferred: list[int], total: int) -> int:
        temporary.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            offset = temporary.stat().st_size if temporary.is_file() else 0
            if entry.size and offset > entry.size:
                temporary.unlink(missing_ok=True)
                offset = 0
            headers = {"User-Agent": "NexusLauncher/1.0"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(entry.url, headers=headers)
            started = time.monotonic()
            try:
                with open_https(request, timeout=60, allowed_hosts=trusted_download_hosts()) as response:
                    status = int(getattr(response, "status", response.getcode() if hasattr(response, "getcode") else 200))
                    content_range = str(response.headers.get("Content-Range", ""))
                    resumed = offset > 0 and status == 206 and content_range.startswith(f"bytes {offset}-")
                    if offset and not resumed:
                        # A server that ignores Range must never be appended to.
                        offset = 0
                    received = offset
                    mode = "ab" if resumed else "wb"
                    verifier = TransferVerifier(entry.sha256, entry.size or None)
                    if resumed:
                        # A resumed attempt must verify the prefix too, not only new bytes.
                        with temporary.open("rb") as prefix:
                            while prefix_block := prefix.read(1024 * 1024):
                                verifier.update(prefix_block)
                    with temporary.open(mode) as output:
                        self._emit_progress("downloading", entry.path, transferred[0] + received, total, attempt)
                        deadline = time.monotonic() + 300
                        while block := getattr(response, "read1", response.read)(1024 * 1024):
                            if time.monotonic() >= deadline:
                                raise TimeoutError("File download deadline exceeded")
                            received += len(block)
                            if received > MAX_PACK_BYTES or (entry.size and received > entry.size):
                                raise ValueError(f"Файл слишком большой: {entry.name}")
                            verifier.update(block)
                            output.write(block)
                            self._emit_progress("downloading", entry.path, min(total, transferred[0] + received), total, attempt)
                        output.flush()
                        os.fsync(output.fileno())
                self.log(f"VERIFYING • {entry.name}")
                self._emit_progress("verifying", entry.path, transferred[0] + received, total, attempt)
                if entry.size and received != entry.size:
                    raise ValueError(f"Размер файла не совпадает: {entry.name}")
                try:
                    verifier.finish()
                except ValueError:
                    temporary.unlink(missing_ok=True)
                    raise
                # Keep the independent staged-file readback before apply/recovery.
                if sha256_file(temporary) != entry.sha256:
                    temporary.unlink(missing_ok=True)
                    raise ValueError(f"Файл {entry.name} повреждён после загрузки")
                transferred[0] += received
                elapsed = max(time.monotonic() - started, 0.001)
                self.log(
                    f"Загружен {entry.name} • {received / 1048576:.1f} МБ • {received / elapsed / 1048576:.1f} МБ/с"
                )
                return received
            except Exception as error:
                last_error = error
                if attempt < DOWNLOAD_ATTEMPTS:
                    self.log(f"Повтор загрузки {entry.name}: {attempt + 1}/{DOWNLOAD_ATTEMPTS}")
                    time.sleep(0.25 * attempt)
        assert last_error is not None
        raise last_error

    def _sync_files(self, release: PackRelease, force: bool = False) -> None:
        """Synchronize a file manifest while deleting only previously owned paths."""
        previous = self._read_state()
        validate_paths(self.game_dir, [entry.path for entry in release.files], ALLOWED_ROOTS)
        for mod in release.optional_mods:
            validate_paths(self.game_dir, mod.files, ALLOWED_ROOTS)
        self._set_delivery(InstallState.PREPARING)
        try:
            ensure_space(
                self.game_dir,
                sum(entry.size for entry in release.files)
                + sum(
                    self._path(path).stat().st_size
                    for path in previous.get("managed_files", {})
                    if self._path(path).is_file()
                ),
            )
        except Exception as error:
            self._set_delivery(InstallState.FAILED, error_kind=self.classify_error(error), error=str(error))
            raise
        self.game_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        old_managed = {str(path): str(digest) for path, digest in previous.get("managed_files", {}).items()}
        selections = self.optional_selections()
        optional_by_path: dict[str, str] = {}
        for mod in release.optional_mods:
            selections.setdefault(mod.id, mod.default_enabled)
            for path in mod.files:
                optional_by_path[path] = mod.id
        known_optional_ids = {mod.id for mod in release.optional_mods}
        selections = {key: value for key, value in selections.items() if key in known_optional_ids}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._durable_json(STATE_DIR + "/optional-mods.json", selections)
        desired = {
            entry.path: entry
            for entry in release.files
            if entry.mode == "required"
            or (entry.mode == "optional" and selections.get(optional_by_path.get(entry.path, entry.id.lower()), False))
        }
        preserved_paths = {entry.path for entry in release.files if entry.mode == "preserve"}
        self.log(f"CHECKING • файлов: {len(desired)}")
        pending: list[PackFile] = []
        for entry in desired.values():
            target = self._path(entry.path)
            if not target.is_file() or target.stat().st_size != entry.size or sha256_file(target) != entry.sha256:
                pending.append(entry)

        # A file can move from pack-managed to user-managed between releases.
        # In that transition it must be released from inventory, not deleted.
        removed = sorted(set(old_managed) - set(desired) - preserved_paths)
        backup_root = checked_tree(self.game_dir, STATE_DIR + "/backup-files")
        if backup_root.exists():
            remove_owned_tree(self.game_dir, STATE_DIR + "/backup-files")
        changed: list[str] = []
        deleted: list[str] = []
        total = sum(max(0, entry.size) for entry in pending)
        transferred = [0]
        staged: dict[str, Path] = {}
        try:
            for entry in pending:
                self.log(f"DOWNLOADING • {entry.name}")
                stage = self._stage_path(release, entry)
                if stage.is_file() and (not entry.size or stage.stat().st_size == entry.size) and sha256_file(stage) == entry.sha256:
                    transferred[0] += stage.stat().st_size
                    self._emit_progress("verifying", entry.path, transferred[0], total)
                else:
                    self._download_file(entry, stage, transferred, total)
                staged[entry.path] = stage
            self.log("APPLYING • проверенные файлы")
            self._emit_progress("applying", None, transferred[0], total)
            self._write_transaction([entry.path for entry in pending], removed)
            for entry in pending:
                self._prepare_transaction_file(entry.path)
                target = self._path(entry.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                replace_file(staged[entry.path], target)
                changed.append(entry.path)
            for relative in removed:
                self.log(f"CLEANING • {relative}")
                target = self._path(relative)
                if target.is_file():
                    self._prepare_transaction_file(relative)
                    if relative in optional_by_path:
                        cache = self._path(STATE_DIR + "/optional-cache/" + target.name)
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        replace_file(self._path(relative), self._path(cache.relative_to(self.game_dir).as_posix()))
                    else:
                        unlink_file(self._path(relative))
                    deleted.append(relative)
        except Exception as error:
            self.log("ROLLING_BACK • ошибка установки")
            self._recover_incomplete_update()
            self._set_delivery(InstallState.FAILED, error_kind=self.classify_error(error), error=str(error))
            raise
        state = {
            "format": 3,
            "schema_version": 2,
            "pack": release.pack,
            "version": release.version,
            "minecraft": release.minecraft,
            "loader": release.loader,
            "loader_version": release.loader_version,
            "managed_files": {path: entry.sha256 for path, entry in desired.items()},
            "optional_mods": [Path(entry.path).name.lower() for entry in release.files if entry.mode == "optional"],
            "optional_catalog": [
                {
                    "id": mod.id,
                    "name": mod.name,
                    "description": mod.description,
                    "category": mod.category,
                    "recommended": mod.recommended,
                    "defaultEnabled": mod.default_enabled,
                    "restartRequired": mod.restart_required,
                    "performanceImpact": mod.performance_impact,
                    "dependencies": list(mod.dependencies),
                    "conflicts": list(mod.conflicts),
                    "minecraftVersion": mod.minecraft_version,
                    "loader": mod.loader,
                    "minimumRam": mod.minimum_ram,
                    "recommendedRam": mod.recommended_ram,
                    "files": list(mod.files),
                    "downloadSize": sum(entry.size for entry in release.files if entry.path in mod.files),
                }
                for mod in release.optional_mods
            ],
            "preserved_files": [entry.path for entry in release.files if entry.mode == "preserve"],
            "last_successful_update": int(time.time()),
            "channel": "stable",
            "display_name": release.display_name,
            "season_name": release.season_name,
            "description": release.description,
            "logo": release.logo,
            "background": release.background,
            "minecraft_server": release.minecraft_server,
        }
        self._emit_progress("finalizing", None, transferred[0], total)
        self._durable_json(STATE_DIR + "/pack.json", state)
        self._path(STATE_DIR + "/update-transaction.json").unlink(missing_ok=True)
        self._emit_progress("ready", None, max(total, 1), max(total, 1))
        self.log(f"COMPLETE • скачано {len(pending)} • удалено {len(deleted)}")

    def repair(self, manifest_url: str) -> RepairResult:
        """Rehash and restore only missing or corrupted required files."""
        self.log("CHECKING • режим восстановления сборки")
        before = self.audit_managed_files()
        release = self.update_if_needed(manifest_url, force=True)
        downloaded = sum(entry.size for entry in (release.files if release else ()) if entry.path in set(before["missing"] + before["changed"]))
        return RepairResult(
            checked=len((release.files if release else ())),
            repaired=len(before["missing"]) + len(before["changed"]),
            downloaded=downloaded,
        )
