"""Signed POSIX ZIP inventory. Internal bundle links are data, never write paths.

This format is separate from the Windows portable format. Extraction writes
regular files first, then creates only authenticated, bounded internal links.
It grants neither OS publisher trust nor protection from same-user malware.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile

from nexus_launcher.safe_paths import checked_path, pinned_directory, relative_parts
from nexus_launcher.signed_release import verify_envelope, verify_signature

FORMAT = 'nexus-posix-zip-v1'
TARGETS = {
    ('linux', 'x64'): ('NEXUS-Linux-x64', 'NEXUS-Linux-x64/nexus-launcher'),
    ('macos', 'arm64'): ('NEXUS Launcher.app', 'NEXUS Launcher.app/Contents/MacOS/NEXUS Launcher'),
}


@dataclass(frozen=True)
class PosixInventory:
    version: str
    entrypoint: str
    files: tuple
    modes: tuple
    links: tuple
    bundle: str


def inventory(payload):
    from nexus_launcher.portable_package import MAX_FILES, MAX_TOTAL_BYTES
    target = TARGETS.get((payload.get('platform'), payload.get('arch')))
    if payload.get('format') != FORMAT or target is None:
        raise ValueError('Unsupported POSIX target')
    bundle, entry = target
    version = payload.get('version')
    if (not isinstance(version, str) or not re.fullmatch(r'\d{1,6}(?:\.\d{1,6}){2,3}', version)
            or payload.get('entrypoint') != entry):
        raise ValueError('Invalid POSIX identity')
    records = payload.get('files')
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_FILES:
        raise ValueError('Invalid POSIX inventory')
    files, modes, links, names, folded, total = [], [], {}, set(), set(), 0
    for item in records:
        if not isinstance(item, dict):
            raise ValueError('Invalid POSIX record')
        name = item.get('path')
        parts = relative_parts(name)
        if len(name) > 1024 or parts[0] != bundle or len(parts) < 2 or name.casefold() in folded:
            raise ValueError('Invalid or duplicate bundle path')
        names.add(name)
        folded.add(name.casefold())
        if item.get('kind') == 'file':
            if set(item) != {'path', 'kind', 'size', 'sha256', 'mode'}:
                raise ValueError('Invalid file fields')
            size, digest, mode = item['size'], item['sha256'], item['mode']
            if (type(size) is not int or not 0 <= size <= MAX_TOTAL_BYTES
                    or type(mode) is not int or mode not in (0o644, 0o755)
                    or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
                raise ValueError('Invalid POSIX file')
            files.append((name, size, digest))
            modes.append((name, mode))
            total += size
        elif item.get('kind') == 'symlink':
            if set(item) != {'path', 'kind', 'target'}:
                raise ValueError('Invalid link fields')
            value = item['target']
            if (not isinstance(value, str) or not 0 < len(value.encode('utf-8')) <= 1024
                    or value.startswith('/') or '\\' in value or ':' in value
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise ValueError('Invalid link target')
            links[name] = value
        else:
            raise ValueError('Unsupported POSIX record type')
    if total > MAX_TOTAL_BYTES or dict(modes).get(entry) != 0o755:
        raise ValueError('Missing executable or excessive expanded size')
    directories = set()
    for name in names:
        parts = name.split('/')
        for i in range(1, len(parts)):
            parent = '/'.join(parts[:i])
            if parent in names:
                raise ValueError('Entry beneath a file or symlink')
            directories.add(parent)
    targets = names | directories
    for name, value in links.items():
        stack = name.split('/')[:-1]
        pending = value.split('/')
        visited = {name}
        while pending:
            part = pending.pop(0)
            if part in ('', '.'):
                continue
            if part == '..':
                if len(stack) <= 1:
                    raise ValueError('Link escapes bundle')
                stack.pop()
                continue
            stack.append(part)
            prefix = '/'.join(stack)
            if prefix in links:
                if prefix in visited:
                    raise ValueError('Cyclic bundle link')
                visited.add(prefix)
                stack.pop()
                pending = links[prefix].split('/') + pending
        resolved = '/'.join(stack)
        if resolved not in targets:
            raise ValueError('Dangling bundle link')
    return PosixInventory(version, entry, tuple(files), tuple(modes), tuple(links.items()), bundle)


def verify_archive(source, envelope, *, keys=None):
    inv = inventory(verify_envelope(envelope, keys=keys))
    expected = {name: (size, sha) for name, size, sha in inv.files}
    modes, links = dict(inv.modes), dict(inv.links)
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) != len(expected) + len(links):
            raise ValueError('POSIX archive inventory mismatch')
        seen = set()
        for item in entries:
            name = item.filename
            if name != item.orig_filename or name in seen or item.flag_bits & 1:
                raise ValueError('Ambiguous or encrypted ZIP entry')
            seen.add(name)
            mode = item.external_attr >> 16
            if name in links:
                if (not stat.S_ISLNK(mode) or item.file_size > 1024
                        or archive.read(item) != links[name].encode('utf-8')):
                    raise ValueError('Link does not match signed target')
            elif name in expected:
                size, sha = expected[name]
                if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != modes[name] or item.file_size != size:
                    raise ValueError('File type, mode or size mismatch')
                digest, count = hashlib.sha256(), 0
                with archive.open(item) as stream:
                    while block := stream.read(256 * 1024):
                        count += len(block)
                        if count > size:
                            raise ValueError('Expanded file exceeds signed size')
                        digest.update(block)
                if count != size or digest.hexdigest() != sha:
                    raise ValueError('File hash mismatch')
            else:
                raise ValueError('Unsigned ZIP entry')
    return inv


def verify_tree(root, inv):
    root = Path(root).absolute()
    bundle = checked_path(root, inv.bundle)
    if not bundle.is_dir():
        raise ValueError('Bundle directory missing')
    observed, modes, links = set(), dict(inv.modes), dict(inv.links)
    for parent, dirs, files in os.walk(bundle, followlinks=False):
        for name in dirs + files:
            p = Path(parent) / name
            relative = p.relative_to(root).as_posix()
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode):
                if links.get(relative) != os.readlink(p):
                    raise ValueError('Unsigned or altered link')
                observed.add(relative)
            elif stat.S_ISREG(info.st_mode):
                observed.add(relative)
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError('Special file in bundle')
    if observed != {p for p, _, _ in inv.files} | links.keys():
        raise ValueError('Bundle inventory changed')
    for name, size, digest in inv.files:
        p = checked_path(root, name)
        info = p.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size != size
                or os.name == 'posix' and stat.S_IMODE(info.st_mode) != modes[name]):
            raise ValueError('Bundle mode, type or size changed')
        with p.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('Bundle content changed')


def stage_archive(source, envelope, staging_root, *, keys=None):
    from nexus_launcher.resource_limits import ensure_space
    from nexus_launcher.user_instances import atomic_json
    if os.name != 'posix':
        raise OSError('POSIX staging requires a POSIX host')
    envelope = json.loads(json.dumps(envelope, allow_nan=False))
    source = Path(source).absolute()
    staging_root = Path(staging_root).absolute()
    checked_path(source.parent, source.name)
    with source.open('rb') as stream, pinned_directory(staging_root, create=True):
        inv = verify_archive(stream, envelope, keys=keys)
        ensure_space(staging_root, sum(size for _, size, _ in inv.files))
        slot = Path(tempfile.mkdtemp(prefix='portable-stage-', dir=staging_root))
        atomic_json(slot / 'journal.json', {'schema': 1, 'phase': 'PREPARING'})
        files = slot / 'files'
        files.mkdir()
        modes = dict(inv.modes)
        with zipfile.ZipFile(stream) as archive:
            for name, size, digest in inv.files:
                p = checked_path(files, name)
                with pinned_directory(p.parent, create=True), archive.open(name) as content, p.open('xb') as target:
                    h, count = hashlib.sha256(), 0
                    while block := content.read(256 * 1024):
                        count += len(block)
                        if count > size:
                            raise ValueError('Expanded POSIX file too large')
                        target.write(block)
                        h.update(block)
                    if count != size or h.hexdigest() != digest:
                        raise ValueError('POSIX staged file changed')
                    os.fchmod(target.fileno(), modes[name])
                    target.flush()
                    os.fsync(target.fileno())
            # No extraction write can ever traverse a bundle symlink.
            for name, value in inv.links:
                p = checked_path(files, name)
                with pinned_directory(p.parent, create=True):
                    os.symlink(value, p)
        verify_tree(files, inv)
        from nexus_launcher.posix_quarantine import preserve
        preserve(source, files / inv.bundle)
        atomic_json(slot / 'envelope.json', envelope)
        atomic_json(slot / 'journal.json', {'schema': 1, 'phase': 'READY'})
        return slot


def stage_directory(source_parent, envelope, staging_root, *, keys=None, cancelled=lambda: False,
                    installed=False):
    """Copy authenticated bytes; installed=True is only for the running baseline.

    Publication expiry still blocks every new archive installation. It does not
    invalidate the exact already installed version being adopted without upgrade.
    """
    from nexus_launcher.resource_limits import ensure_space
    from nexus_launcher.user_instances import atomic_json
    if os.name != 'posix':
        raise OSError('POSIX staging requires a POSIX host')
    inv = inventory((verify_signature if installed else verify_envelope)(envelope, keys=keys))
    source_parent, staging_root = Path(source_parent).absolute(), Path(staging_root).absolute()
    verify_tree(source_parent, inv)
    with pinned_directory(staging_root, create=True):
        ensure_space(staging_root, sum(size for _, size, _ in inv.files))
        slot = Path(tempfile.mkdtemp(prefix='portable-stage-', dir=staging_root))
        atomic_json(slot / 'journal.json', {'schema': 1, 'phase': 'PREPARING'})
        files = slot / 'files'
        files.mkdir()
        modes = dict(inv.modes)
        for name, size, digest in inv.files:
            if cancelled():
                raise InterruptedError('Initial update preparation cancelled')
            src, dst = checked_path(source_parent, name), checked_path(files, name)
            with pinned_directory(dst.parent, create=True), src.open('rb') as stream, dst.open('xb') as target:
                h, count = hashlib.sha256(), 0
                while block := stream.read(256 * 1024):
                    if cancelled():
                        raise InterruptedError('Initial update preparation cancelled')
                    count += len(block)
                    if count > size:
                        raise ValueError('Installed source changed while copying')
                    target.write(block)
                    h.update(block)
                if count != size or h.hexdigest() != digest:
                    raise ValueError('Installed source does not match signed release')
                os.fchmod(target.fileno(), modes[name])
                target.flush()
                os.fsync(target.fileno())
        for name, value in inv.links:
            p = checked_path(files, name)
            with pinned_directory(p.parent, create=True):
                os.symlink(value, p)
        verify_tree(files, inv)
        from nexus_launcher.posix_quarantine import preserve
        preserve(source_parent / inv.bundle, files / inv.bundle)
        atomic_json(slot / 'envelope.json', envelope)
        atomic_json(slot / 'journal.json', {'schema': 1, 'phase': 'READY'})
        return slot
