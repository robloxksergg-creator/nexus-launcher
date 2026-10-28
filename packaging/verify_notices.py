"""Validate copied notice bytes before candidate packaging, not legal clearance."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re


def verify(root):
    root = Path(root).resolve(strict=True)
    inventory = root / 'inventory.json'
    if inventory.stat().st_size > 4_000_000:
        raise ValueError('Notice inventory too large')
    data = json.loads(inventory.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Invalid notice inventory')
    if data.get('schema') == 1 and data.get('kind') == 'notice-bundle':
        entries = data.get('files')
    elif isinstance(data.get('distributions'), list):
        entries = []
        for distribution in data['distributions']:
            if not isinstance(distribution, dict) or not isinstance(distribution.get('files'), list):
                raise ValueError('Invalid distribution notices')
            entries.extend(distribution['files'])
    elif isinstance(data.get('packages'), list):
        entries = []
        for package in data['packages']:
            if not isinstance(package, dict) or not isinstance(package.get('notices'), list):
                raise ValueError('Invalid package notices')
            entries.extend(package['notices'])
    else:
        raise ValueError('Unknown notice inventory format')
    if not isinstance(entries, list) or not entries or len(entries) > 10_000:
        raise ValueError('Invalid notice file count')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid notice entry')
        name, digest = entry.get('path'), entry.get('sha256')
        if not isinstance(name, str) or not name or '\\' in name or ':' in name:
            raise ValueError('Invalid notice path')
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
            raise ValueError('Unsafe notice path')
        if name.casefold() in seen or name.casefold() == 'inventory.json':
            raise ValueError('Duplicate or reserved notice path')
        seen.add(name.casefold())
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid notice digest')
        source = root.joinpath(*relative.parts)
        if source.is_symlink() or not source.resolve(strict=True).is_relative_to(root):
            raise ValueError('Notice escapes collection')
        if not source.is_file() or source.stat().st_size > 10_000_000:
            raise ValueError('Invalid notice file')
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Notice checksum mismatch: ' + name)
    actual = {p.relative_to(root).as_posix().casefold() for p in root.rglob('*') if p.is_file()}
    if actual != seen | {'inventory.json'}:
        raise ValueError('Unlisted notice files')
    return {'files_verified': len(entries), 'license_clearance': 'NOT ESTABLISHED'}
