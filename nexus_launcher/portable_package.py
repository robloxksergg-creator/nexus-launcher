"""Offline verification of a complete portable package, never installation.

This module does not download, extract, launch, activate or publish a package.
Only an authenticated envelope can supply the expected file inventory.
"""

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from nexus_launcher.safe_paths import checked_path, pinned_directory, relative_parts
from nexus_launcher.signed_release import verify_envelope, verify_signature

MAX_FILES = 10000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class PortableInventory:
    version: str
    entrypoint: str
    files: tuple[tuple[str, int, str], ...]


def verify_portable_inventory(envelope, *, keys=None):
    payload = verify_envelope(envelope, keys=keys)
    return _inventory_from_payload(payload)


def verify_installed_inventory(envelope, *, keys=None):
    """Verify an installed package's identity, not fresh update eligibility.

    Publication expiry blocks new installation, not an already selected version.
    Callers must separately prove the slot is the installed/active selection.
    """
    return _inventory_from_payload(verify_signature(envelope, keys=keys))


def _inventory_from_payload(payload):
    if payload.get("format") != "nexus-portable-zip-v1":
        raise ValueError("Unsupported portable package format")
    version = payload.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d{1,6}(?:\.\d{1,6}){2,3}", version):
        raise ValueError("Invalid package version")
    entry = payload.get("entrypoint")
    if not isinstance(entry, str) or len(relative_parts(entry)) != 1 or not entry.lower().endswith(".exe"):
        raise ValueError("Invalid portable entrypoint")
    files = payload.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("Invalid package inventory")
    seen, result, total = set(), [], 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise ValueError("Invalid file record")
        name, size, digest = item["path"], item["size"], item["sha256"]
        parts = relative_parts(name)
        if parts[0].casefold() in {"data", "updates", ".env", ".git"}:
            raise ValueError("User data is forbidden in a release package")
        folded = name.casefold()
        if folded in seen:
            raise ValueError("Ambiguous duplicate package path")
        if type(size) is not int or size < 0 or size > MAX_TOTAL_BYTES:
            raise ValueError("Invalid file size")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid file digest")
        seen.add(folded)
        result.append((name, size, digest))
        total += size
    if total > MAX_TOTAL_BYTES or entry not in {x[0] for x in result}:
        raise ValueError("Incomplete or oversized portable package")
    for name in seen:
        parts = name.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            raise ValueError("Package file conflicts with a parent directory")
    if not any(name.startswith("_internal/") for name, _, _ in result):
        raise ValueError("Missing portable runtime")
    return PortableInventory(version, entry, tuple(result))


def verify_portable_archive(source, envelope, *, keys=None):
    """Read a local archive and authenticate all bytes; no filesystem extraction.

    Version ordering, platform compatibility, dispatch and activation remain
    separate gates. A successful integrity check is not installation authority.
    """
    inventory = verify_portable_inventory(envelope, keys=keys)
    expected = {name: (size, digest) for name, size, digest in inventory.files}
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) != len(expected):
            raise ValueError("Archive does not match signed file inventory")
        seen = set()
        for member in members:
            if member.orig_filename != member.filename:
                raise ValueError("Ambiguous archive filename")
            relative_parts(member.filename)
            mode = member.external_attr >> 16
            if member.is_dir() or member.flag_bits & 1 or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ValueError("Archive links, devices and encrypted entries are forbidden")
            if member.filename in seen or member.filename not in expected:
                raise ValueError("Unexpected or duplicate archive member")
            seen.add(member.filename)
            size, expected_digest = expected[member.filename]
            if member.file_size != size:
                raise ValueError("Archive file size mismatch")
            digest, received = hashlib.sha256(), 0
            with archive.open(member) as stream:
                while block := stream.read(1024 * 1024):
                    received += len(block)
                    if received > size:
                        raise ValueError("Archive expanded beyond signed size")
                    digest.update(block)
            if received != size or digest.hexdigest() != expected_digest:
                raise ValueError("Archive file integrity mismatch")
    return inventory


def stage_portable_archive(source: Path, envelope, staging_root: Path, *, keys=None):
    """Prepare a unique inactive slot. Never replace, execute or remove a version.

    The caller supplies an owned staging root. READY is an integrity receipt,
    not activation authority; consumers must revalidate files before activation.
    Failed partial slots are retained without READY, not recursively cleaned up.
    """
    from nexus_launcher.resource_limits import copy_limited, ensure_space
    from nexus_launcher.user_instances import atomic_json

    envelope = json.loads(json.dumps(envelope, allow_nan=False))
    source, staging_root = Path(source).absolute(), Path(staging_root).absolute()
    checked_path(source.parent, source.name)
    with pinned_directory(source.parent), pinned_directory(staging_root):
        with source.open("rb") as stream:
            inventory = verify_portable_archive(stream, envelope, keys=keys)
            ensure_space(staging_root, sum(size for _, size, _ in inventory.files))
            slot = Path(tempfile.mkdtemp(prefix="portable-stage-", dir=staging_root))
            with pinned_directory(slot):
                atomic_json(checked_path(slot, "journal.json"), {"schema": 1, "phase": "PREPARING"})
                files_root = checked_path(slot, "files")
                files_root.mkdir()
                with pinned_directory(files_root), zipfile.ZipFile(stream) as archive:
                    for name, size, expected in inventory.files:
                        target = checked_path(files_root, name)
                        with pinned_directory(target.parent, create=True):
                            checked_path(files_root, name)
                            digest = hashlib.sha256()
                            with archive.open(name) as content, target.open("xb") as output:
                                actual = copy_limited(content, output, limit=size, digest=digest)
                                output.flush()
                                os.fsync(output.fileno())
                            if actual != size or digest.hexdigest() != expected:
                                raise ValueError("Staged file integrity mismatch")
                atomic_json(checked_path(slot, "envelope.json"), envelope)
                _verify_staged_files(files_root, inventory)
                atomic_json(checked_path(slot, "journal.json"), {"schema": 1, "phase": "READY"})
                return slot


def _verify_staged_files(root, inventory):
    expected = {name for name, _, _ in inventory.files}
    observed = set()
    for parent, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            relative = (Path(parent) / name).relative_to(root).as_posix()
            checked_path(root, relative)
        observed.update((Path(parent) / name).relative_to(root).as_posix() for name in names)
    if observed != expected:
        raise ValueError("Staged file inventory mismatch")
    for name, size, expected_digest in inventory.files:
        target = checked_path(root, name)
        with pinned_directory(target.parent):
            if not stat.S_ISREG(target.lstat().st_mode) or target.stat().st_size != size:
                raise ValueError("Staged file size/type mismatch")
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected_digest:
                    raise ValueError("Staged file integrity mismatch")


def verify_staged_portable(slot: Path, *, keys=None, installed=False):
    """Revalidate a READY receipt and every staged file, without activation."""
    from nexus_launcher.resource_limits import read_limited

    slot = Path(slot).absolute()
    with pinned_directory(slot):
        with checked_path(slot, "journal.json").open("rb") as stream:
            journal = json.loads(read_limited(stream, 4096))
        if journal != {"schema": 1, "phase": "READY"}:
            raise ValueError("Portable slot is not ready")
        with checked_path(slot, "envelope.json").open("rb") as stream:
            envelope = json.loads(read_limited(stream))
        inventory = (verify_installed_inventory if installed else verify_portable_inventory)(envelope, keys=keys)
        root = checked_path(slot, "files")
        with pinned_directory(root):
            _verify_staged_files(root, inventory)
        return inventory
