"""Bound memory, disk writes and archive expansion before installation."""

import hashlib
import math
import os
import shutil
import stat
import time

from nexus_launcher.native_transfer import _native

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 50_000
MAX_EXTRACTED_BYTES = 4 * MAX_FILE_BYTES
DISK_MARGIN = 32 * 1024 * 1024


def _stream_api(limit, timeout, capability="STREAM_IO_API_VERSION"):
    if not isinstance(limit, int) or not 0 <= limit <= (1 << 64) - 1:
        raise ValueError("Invalid stream byte limit")
    try:
        valid_timeout = isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout >= 0
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ValueError("Invalid stream time budget")
    if _native is not None and hasattr(_native, capability):
        if getattr(_native, capability) != 1:
            raise ImportError("Incompatible NEXUS stream IO API")
        return _native
    return None


def digest_limited(source, algorithm="sha256", limit=MAX_FILE_BYTES, timeout=300):
    native = _stream_api(limit, timeout, "STREAM_HASH_API_VERSION")
    if algorithm not in ("sha256", "sha512"):
        raise ValueError("Unsupported stream digest")
    read = getattr(source, "read1", source.read)
    if native is not None:
        return native.stream_digest_limited(read, algorithm, limit, timeout, time.monotonic)
    deadline = time.monotonic() + timeout
    total = 0
    hasher = hashlib.new(algorithm)
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError("Hashing exceeded its time budget")
        block = read(min(256 * 1024, limit - total + 1))
        if time.monotonic() >= deadline:
            raise TimeoutError("Hashing exceeded its time budget")
        if not block:
            return hasher.hexdigest()
        if len(block) > limit - total:
            raise ValueError("Hash input exceeds byte limit")
        hasher.update(block)
        total += len(block)


def digest_file(path, algorithm="sha256", timeout=300):
    """Hash a regular file within its opened size; this is not a source snapshot."""
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Hash source must be a regular file")
        return digest_limited(stream, algorithm, limit=info.st_size, timeout=timeout)


def read_limited(source, limit=MAX_RESPONSE_BYTES, timeout=60):
    native = _stream_api(limit, timeout)
    if native is not None:
        return native.stream_read_limited(
            getattr(source, "read1", source.read), limit, timeout, time.monotonic,
        )
    deadline = time.monotonic() + timeout
    chunks = []
    total = 0
    # read1 performs at most one underlying read: a slow drip cannot keep a
    # buffered read(limit) alive indefinitely without a deadline check.
    read = getattr(source, "read1", source.read)
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError("Response exceeded its time budget")
        block = read(min(64 * 1024, limit - total + 1))
        if time.monotonic() >= deadline:
            raise TimeoutError("Response exceeded its time budget")
        if not block:
            return b"".join(chunks)
        total += len(block)
        if total > limit:
            raise ValueError("Response exceeds byte limit")
        chunks.append(block)


def copy_limited(source, destination, limit=MAX_FILE_BYTES, digest=None, timeout=300):
    native = _stream_api(limit, timeout)
    if native is not None:
        return native.stream_copy_limited(
            getattr(source, "read1", source.read), destination.write,
            limit, digest, timeout, time.monotonic,
        )
    total = 0
    deadline = time.monotonic() + timeout
    read = getattr(source, "read1", source.read)
    while block := read(min(256 * 1024, limit - total + 1)):
        if time.monotonic() > deadline:
            raise TimeoutError("File transfer exceeded its time budget")
        total += len(block)
        if total > limit:
            raise ValueError("File exceeds byte limit")
        written = destination.write(block)
        if not isinstance(written, int) or written != len(block):
            raise OSError("Incomplete stream write")
        if digest is not None:
            digest.update(block)
    return total


def ensure_space(path, required):
    while not path.exists():
        if path.parent == path:
            raise OSError("Selected disk is unavailable")
        path = path.parent
    if required < 0 or shutil.disk_usage(path).free < required + DISK_MARGIN:
        raise OSError("Insufficient disk space for safe installation")


def validate_archive(archive):
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("Too many archive entries")
    if _native is not None and hasattr(_native, "ARCHIVE_API_VERSION"):
        if _native.ARCHIVE_API_VERSION != 1:
            raise ImportError("Incompatible NEXUS archive API")
        # Metadata only. Path policy, symlink refusals and bounded extraction
        # stay with existing callers. Native failures never retry in Python.
        return _native.archive_inventory(
            [entry.file_size for entry in entries],
            MAX_ARCHIVE_ENTRIES, MAX_FILE_BYTES, MAX_EXTRACTED_BYTES,
        )
    total = 0
    for entry in entries:
        if entry.file_size < 0 or entry.file_size > MAX_FILE_BYTES:
            raise ValueError("Archive file exceeds size limit")
        total += entry.file_size
        if total > MAX_EXTRACTED_BYTES:
            raise ValueError("Archive exceeds extracted byte limit")
    return total
