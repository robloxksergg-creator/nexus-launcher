"""Untrusted local world-submission and review pipeline.

This module intentionally has no production signing or publishing authority.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath

from nexus_launcher.resource_limits import MAX_ARCHIVE_ENTRIES, MAX_EXTRACTED_BYTES, copy_limited, digest_limited, ensure_space
from nexus_launcher.safe_paths import checked_path, replace_file
from nexus_launcher.native_zip import open_zip_entry, write_zip_data, write_zip_entry

SUBMISSION_SCHEMA_VERSION = 1
WORLD_CATEGORIES = ("TECH", "RPG", "VANILLA", "ADVENTURE", "INDUSTRIAL", "SURVIVAL", "OTHER")
CHANNELS = {"dev", "beta", "stable"}
VISIBILITIES = {"private", "unlisted", "public"}
TRUST_LEVELS = {"official", "partner", "community", "local"}
MAX_PACKAGE_BYTES = 16 * 1024 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
EXECUTABLE_SUFFIXES = {".exe", ".dll", ".bat", ".cmd", ".ps1", ".com", ".scr"}
SECRET_PATTERN = re.compile(r"(?i)(token|cookie|authorization|api[_-]?key|secret|password|private[_-]?key)")
ABSOLUTE_PATTERN = re.compile(r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|^/|^\\\\)")


class PublicationState(StrEnum):
    LOCAL_DRAFT = "LOCAL_DRAFT"
    READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    RELEASE_CANDIDATE = "RELEASE_CANDIDATE"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


@dataclass(frozen=True)
class ReviewRecord:
    actor: str
    action: str
    timestamp: int
    comment: str = ""


@dataclass(frozen=True)
class Submission:
    id: str
    project_id: str
    owner: str
    revision: int
    project_version: str
    minecraft_version: str
    loader: str
    metadata: dict
    presentation: dict
    client_artifact: str
    server_artifact: str = ""
    manifest_summary: dict = field(default_factory=dict)
    validation_result: tuple[dict, ...] = field(default_factory=tuple)
    changelog: str = ""
    created_at: int = 0
    status: PublicationState = PublicationState.LOCAL_DRAFT
    review_history: tuple[ReviewRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        result = {
            "schemaVersion": SUBMISSION_SCHEMA_VERSION, "id": self.id, "projectId": self.project_id,
            "owner": self.owner, "revision": self.revision, "projectVersion": self.project_version,
            "minecraftVersion": self.minecraft_version, "loader": self.loader, "metadata": self.metadata,
            "presentation": self.presentation, "clientArtifact": self.client_artifact,
            "serverArtifact": self.server_artifact, "manifestSummary": self.manifest_summary,
            "validationResult": list(self.validation_result), "changelog": self.changelog,
            "createdAt": self.created_at, "status": self.status.value,
            "reviewHistory": [record.__dict__ for record in self.review_history],
            "official": False, "signed": False,
        }
        return result

    @classmethod
    def from_dict(cls, raw: dict) -> "Submission":
        if not isinstance(raw, dict) or raw.get("schemaVersion") != SUBMISSION_SCHEMA_VERSION:
            raise ValueError("Unsupported submission schema")
        history = tuple(ReviewRecord(str(x["actor"]), str(x["action"]), int(x["timestamp"]), str(x.get("comment", "")))
                        for x in raw.get("reviewHistory", []))
        return cls(str(raw["id"]), str(raw["projectId"]), str(raw["owner"]), int(raw["revision"]),
                   str(raw["projectVersion"]), str(raw["minecraftVersion"]), str(raw["loader"]),
                   dict(raw["metadata"]), dict(raw["presentation"]), str(raw["clientArtifact"]),
                   str(raw.get("serverArtifact", "")), dict(raw.get("manifestSummary", {})),
                   tuple(raw.get("validationResult", [])), str(raw.get("changelog", "")), int(raw["createdAt"]),
                   PublicationState(str(raw["status"])), history)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return digest_limited(stream, "sha256", limit=MAX_PACKAGE_BYTES)


def safe_slug(value: str, fallback="world") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold().encode("ascii", "ignore").decode()).strip("-")
    slug = slug[:64]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug or ""):
        slug = re.sub(r"[^a-z0-9]+", "-", fallback.casefold()).strip("-")[:64] or "world"
    return slug


def normalize_tags(value) -> list[str]:
    source = value.split(",") if isinstance(value, str) else value
    if not isinstance(source, (list, tuple)) or len(source) > 12:
        raise ValueError("Use no more than 12 tags")
    result = []
    for tag in source:
        normalized = " ".join(str(tag).strip().split())
        if not normalized:
            continue
        if len(normalized) > 28 or not re.fullmatch(r"[\w +.-]+", normalized, re.UNICODE):
            raise ValueError("Invalid tag: " + normalized)
        canonical = normalized[:1].upper() + normalized[1:]
        if canonical.casefold() not in {x.casefold() for x in result}:
            result.append(canonical)
    return result


def _clean_text(value, field_name, limit=8000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError("Invalid submission field: " + field_name)
    if "<script" in value.casefold() or SECRET_PATTERN.search(field_name):
        raise ValueError("Unsafe submission field: " + field_name)
    return value.strip()


def validate_metadata(metadata: dict, *, allow_trust=False) -> dict:
    if not isinstance(metadata, dict):
        raise ValueError("Submission metadata must be an object")
    forbidden = {"official", "creatorVerified", "installAllowed", "launchAllowed", "installManifest", "signed"}
    if not allow_trust and forbidden & metadata.keys():
        raise PermissionError("Creator cannot set trusted catalogue fields")
    result = {
        "title": _clean_text(metadata.get("title", ""), "title", 120, True),
        "shortName": _clean_text(metadata.get("shortName", ""), "shortName", 12, True),
        "summary": _clean_text(metadata.get("summary", ""), "summary", 280, True),
        "description": _clean_text(metadata.get("description", ""), "description", 12000, True),
        "category": _clean_text(metadata.get("category", "OTHER"), "category", 24, True).upper(),
        "tags": normalize_tags(metadata.get("tags", [])),
        "language": _clean_text(metadata.get("language", "ru"), "language", 12, True).lower(),
        "slug": safe_slug(str(metadata.get("slug") or metadata.get("title", ""))),
        "channel": _clean_text(metadata.get("channel", "dev"), "channel", 12, True).lower(),
        "visibility": _clean_text(metadata.get("visibility", "private"), "visibility", 12, True).lower(),
    }
    if result["category"] not in WORLD_CATEGORIES or result["channel"] not in CHANNELS or result["visibility"] not in VISIBILITIES:
        raise ValueError("Invalid category, channel or visibility")
    for key in ("website", "discord", "telegram", "support"):
        value = _clean_text(metadata.get(key, ""), key, 500)
        if value and not value.startswith("https://"):
            raise ValueError(key + " must use HTTPS")
        result[key] = value
    return result


def _safe_member(name: str) -> PurePosixPath:
    if "\\" in name or "\0" in name or ABSOLUTE_PATTERN.search(name):
        raise ValueError("Unsafe submission path")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Unsafe submission path")
    return path


class LocalSubmissionRepository:
    def __init__(self, root: Path):
        self.root = root.absolute()

    def _record_path(self, submission_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{36}", submission_id):
            raise ValueError("Invalid submission ID")
        return checked_path(self.root, submission_id + ".json")

    def save(self, submission: Submission) -> Submission:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._record_path(submission.id)
        if target.exists():
            old = Submission.from_dict(json.loads(target.read_text(encoding="utf-8")))
            if submission.review_history[:len(old.review_history)] != old.review_history:
                raise PermissionError("Review history is append-only")
        fd, name = tempfile.mkstemp(prefix=submission.id, suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(submission.to_dict(), output, ensure_ascii=False, indent=2)
                output.flush(); os.fsync(output.fileno())
            replace_file(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        return submission

    def get(self, submission_id: str) -> Submission:
        return Submission.from_dict(json.loads(self._record_path(submission_id).read_text(encoding="utf-8")))

    def list(self, status: PublicationState | None = None) -> list[Submission]:
        result = []
        if self.root.is_dir():
            for path in self.root.glob("*.json"):
                try:
                    item = Submission.from_dict(json.loads(path.read_text(encoding="utf-8")))
                    if status is None or item.status == status:
                        result.append(item)
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                    continue
        return sorted(result, key=lambda x: (x.created_at, x.revision), reverse=True)

    def next_revision(self, project_id: str) -> int:
        return max((x.revision for x in self.list() if x.project_id == project_id), default=0) + 1

    def withdraw(self, submission_id: str, actor: str) -> Submission:
        item = self.get(submission_id)
        if item.status in {PublicationState.PUBLISHED, PublicationState.ARCHIVED, PublicationState.SUSPENDED}:
            raise ValueError("Published submission cannot be withdrawn locally")
        record = ReviewRecord(actor, "withdrawn", int(time.time()))
        return self.save(replace(item, status=PublicationState.WITHDRAWN, review_history=item.review_history + (record,)))

    def review(self, submission_id: str, decision: str, actor: str, comment="", *, reviewer=False) -> Submission:
        if not reviewer:
            raise PermissionError("Reviewer capability required")
        states = {"approve": PublicationState.APPROVED, "request_changes": PublicationState.CHANGES_REQUESTED,
                  "reject": PublicationState.REJECTED}
        if decision not in states:
            raise ValueError("Unknown review decision")
        item = self.get(submission_id)
        record = ReviewRecord(actor, decision, int(time.time()), _clean_text(comment, "comment", 4000))
        return self.save(replace(item, status=states[decision], review_history=item.review_history + (record,)))

    def approved_candidate(self, submission_id: str, actor: str, *, reviewer=False) -> dict:
        if not reviewer:
            raise PermissionError("Reviewer capability required")
        item = self.get(submission_id)
        if item.status != PublicationState.APPROVED:
            raise ValueError("Submission is not approved")
        return {"schemaVersion": 1, "submissionId": item.id, "revision": item.revision,
                "status": PublicationState.RELEASE_CANDIDATE.value, "official": False, "signed": False,
                "approvedBy": actor, "createdAt": int(time.time())}


class SubmissionPackage:
    @staticmethod
    def create(destination: Path, submission: Submission, client: Path, server: Path | None = None,
               presentation: dict[str, Path] | None = None) -> Path:
        if not client.is_file() or client.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError("Valid client artifact required")
        artifacts = {"artifacts/client.zip": client}
        if server:
            if not server.is_file() or server.stat().st_size > MAX_PACKAGE_BYTES:
                raise ValueError("Invalid server artifact")
            artifacts["artifacts/server.zip"] = server
        assets = {}
        for key, source in (presentation or {}).items():
            if key not in {"icon", "banner", "poster", "video"} or not source.is_file():
                raise ValueError("Invalid presentation asset")
            relative = f"presentation/{key}{source.suffix.lower()}"
            assets[relative] = source
        portable = replace(submission, client_artifact="artifacts/client.zip",
                           server_artifact="artifacts/server.zip" if server else "",
                           presentation={key: next(name for name in assets if name.startswith(f"presentation/{key}."))
                                         for key in (presentation or {})})
        payload = portable.to_dict()
        payload["artifactHashes"] = {name: sha256(path) for name, path in artifacts.items()}
        payload["presentationHashes"] = {name: sha256(path) for name, path in assets.items()}
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        if len(encoded) > MAX_METADATA_BYTES or ABSOLUTE_PATTERN.search(encoded.decode(errors="ignore")):
            raise ValueError("Submission metadata contains an absolute path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        ensure_space(destination.parent, sum(x.stat().st_size for x in (*artifacts.values(), *assets.values())))
        fd, name = tempfile.mkstemp(prefix=destination.name, suffix=".part", dir=destination.parent)
        os.close(fd); temporary = Path(name)
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                write_zip_data(archive, "submission.json", encoded)
                for relative, source in {**artifacts, **assets}.items():
                    with source.open("rb") as incoming, write_zip_entry(
                            archive, relative, force_zip64=True, limit=MAX_PACKAGE_BYTES) as outgoing:
                        copy_limited(incoming, outgoing, limit=MAX_PACKAGE_BYTES)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    @staticmethod
    def inspect(package: Path) -> tuple[Submission, list[str]]:
        if not package.is_file() or package.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError("Invalid submission package")
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES or sum(x.file_size for x in entries) > MAX_EXTRACTED_BYTES * 4:
                raise ValueError("Submission package exceeds limits")
            names = {_safe_member(x.filename).as_posix() for x in entries if not x.is_dir()}
            if "submission.json" not in names:
                raise ValueError("Missing submission metadata")
            info = archive.getinfo("submission.json")
            if info.file_size > MAX_METADATA_BYTES:
                raise ValueError("Submission metadata is too large")
            with open_zip_entry(archive, info, limit=MAX_METADATA_BYTES) as stream:
                raw_bytes = stream.read(MAX_METADATA_BYTES + 1)
            if SECRET_PATTERN.search(raw_bytes.decode(errors="ignore")) or ABSOLUTE_PATTERN.search(raw_bytes.decode(errors="ignore")):
                raise ValueError("Submission contains secrets or absolute paths")
            raw = json.loads(raw_bytes)
            if raw.get("official") is not False or raw.get("signed") is not False:
                raise PermissionError("Creator package cannot claim official or signed trust")
            submission = Submission.from_dict(raw)
            validate_metadata(submission.metadata)
            warnings = []
            hashes = {**raw.get("artifactHashes", {}), **raw.get("presentationHashes", {})}
            for relative, expected in hashes.items():
                safe = _safe_member(relative).as_posix()
                if safe not in names or not re.fullmatch(r"[a-f0-9]{64}", str(expected)):
                    raise ValueError("Submission inventory is invalid")
                with open_zip_entry(archive, archive.getinfo(safe), limit=MAX_PACKAGE_BYTES) as stream:
                    actual = digest_limited(stream, "sha256", limit=MAX_PACKAGE_BYTES)
                if actual != expected:
                    raise ValueError("Submission artifact hash mismatch")
            for artifact in (submission.client_artifact, submission.server_artifact):
                if artifact:
                    safe_artifact = _safe_member(artifact).as_posix()
                    if safe_artifact not in hashes or safe_artifact not in names:
                        raise ValueError("Artifact is not covered by submission inventory")
                    with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as spool:
                        with open_zip_entry(archive, archive.getinfo(safe_artifact), limit=MAX_PACKAGE_BYTES) as nested_stream:
                            copy_limited(nested_stream, spool, limit=MAX_PACKAGE_BYTES)
                        spool.seek(0)
                        with zipfile.ZipFile(spool) as nested:
                            nested_names = nested.namelist()
                    for name in nested_names:
                        _safe_member(name)
                        if Path(name).suffix.lower() in EXECUTABLE_SUFFIXES:
                            warnings.append("Executable content requires security review: " + name)
            return submission, warnings


class PublishingService:
    def __init__(self, studio, repository: LocalSubmissionRepository, capabilities, actor="local-creator"):
        self.studio, self.repository, self.capabilities, self.actor = studio, repository, capabilities, actor

    def prepare(self, project_id: str, destination: Path, *, include_server=False,
                warnings_confirmed=False) -> Submission:
        self.capabilities.require("can_prepare_submission")
        project = self.studio.load(project_id)
        instance = self.studio.instances.load(project_id)
        report = self.studio.validation_report(project_id, False)
        presentation_fields = project.get("presentation", {})
        if not presentation_fields.get("icon") or not presentation_fields.get("banner"):
            raise ValueError("Submission requires Icon and Card/Hero artwork")
        if presentation_fields.get("video") and not presentation_fields.get("poster"):
            raise ValueError("Video presentation requires a poster")
        errors = [x for x in report if x.level == "ERROR"]
        warnings = [x for x in report if x.level == "WARNING"]
        if errors:
            raise ValueError("Submission blocked by validation errors: " + "; ".join(x.message for x in errors))
        if warnings and not warnings_confirmed:
            raise ValueError("Confirm validation warnings before preparing submission")
        fields = project.get("metadata", {})
        metadata = validate_metadata({
            "title": project["name"], "shortName": fields.get("short_name") or project["name"][:12],
            "summary": fields.get("summary") or project.get("description", "")[:280],
            "description": project.get("description", ""), "category": fields.get("category") or "OTHER",
            "tags": fields.get("tags", ""), "language": fields.get("language") or "ru",
            "slug": fields.get("slug") or safe_slug(project["name"], project_id),
            "channel": project.get("channel", "dev"), "visibility": fields.get("visibility") or "private",
            **{key: fields.get(key, "") for key in ("website", "discord", "telegram", "support")},
        })
        revision = self.repository.next_revision(project_id)
        submission_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory(prefix="nexus-submission-build-") as temporary_name:
            temporary = Path(temporary_name)
            client = self.studio.export(project_id, temporary / "client.zip", False)
            server = self.studio.export(project_id, temporary / "server.zip", True) if include_server else None
            inventory = self.studio.inventory(project_id)
            previous = next((x for x in self.repository.list() if x.project_id == project_id), None)
            old_inventory = (previous.manifest_summary.get("inventory", {}) if previous else {})
            diff = {"added": sorted(inventory.keys() - old_inventory.keys()),
                    "removed": sorted(old_inventory.keys() - inventory.keys()),
                    "changed": sorted(k for k in inventory.keys() & old_inventory.keys() if inventory[k] != old_inventory[k])}
            submission = Submission(
                submission_id, project_id, self.actor, revision, project["version"], instance.minecraft_version,
                instance.loader, metadata, {}, "artifacts/client.zip", "artifacts/server.zip" if server else "",
                {"files": len(inventory), "downloadSize": client.stat().st_size + (server.stat().st_size if server else 0),
                 "installedSize": sum(
                     path.stat().st_size
                     for _, path in __import__(
                         "nexus_launcher.creator_services", fromlist=["safe_files"]
                     ).safe_files(self.studio.instances.path_for(project_id))
                 ),
                 "hashAlgorithm": "SHA-256", "manifestVersion": 1, "inventory": inventory, "diff": diff},
                tuple({"level": x.level, "message": x.message} for x in report), project.get("changelog", ""),
                int(time.time()), PublicationState.READY_FOR_SUBMISSION,
                (ReviewRecord(self.actor, "package_prepared", int(time.time())),),
            )
            assets = {key: Path(value) for key, value in project.get("presentation", {}).items() if value}
            SubmissionPackage.create(destination, submission, client, server, assets)
        self.repository.save(submission)
        return submission

    def import_for_review(self, package: Path) -> tuple[Submission, list[str]]:
        self.capabilities.require("can_review_submission")
        submission, warnings = SubmissionPackage.inspect(package)
        record = ReviewRecord(self.actor, "imported_for_review", int(time.time()))
        reviewed = replace(submission, status=PublicationState.UNDER_REVIEW,
                           review_history=submission.review_history + (record,))
        self.repository.save(reviewed)
        return reviewed, warnings

    def decide(self, submission_id: str, decision: str, comment="") -> Submission:
        self.capabilities.require("can_review_submission")
        return self.repository.review(submission_id, decision, self.actor, comment,
                                      reviewer=self.capabilities.can_review_submission)


class WorldCatalogueRepository:
    """Source-neutral catalogue interface; implementations return validated data only."""
    def list_worlds(self) -> list[dict]:
        raise NotImplementedError


class BundledCatalogueRepository(WorldCatalogueRepository):
    def __init__(self, worlds): self.worlds = list(worlds)
    def list_worlds(self): return list(self.worlds)


class CachedCatalogueRepository(WorldCatalogueRepository):
    def __init__(self, cache: Path, validator): self.cache, self.validator = cache, validator
    def list_worlds(self):
        try: return list(self.validator(json.loads(self.cache.read_text(encoding="utf-8"))).values())
        except (OSError, ValueError, TypeError, json.JSONDecodeError): return []
