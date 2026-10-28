"""Copy bounded notice texts from a checksum-pinned tar source archive.

No archive extraction API or source execution is used. Selected filenames do not
establish complete license compliance or the actual linked dependency set.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


def collect(archive, expected_sha256, destination, prefix):
    archive, destination = Path(archive), Path(destination)
    if destination.exists():
        raise ValueError('Output must be a new directory')
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Invalid expected SHA-256')
    if not re.fullmatch('[A-Za-z0-9_.+-]+', prefix) or prefix in {'.', '..'}:
        raise ValueError('Invalid archive prefix')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise ValueError('Source archive checksum mismatch')
    chosen = []
    seen = set()
    total = 0
    count = 0
    # Keep selected bytes in memory until archive validation has completed.
    with tarfile.open(archive, 'r|*') as source:
        for member in source:
            count += 1
            if count > 500_000:
                raise ValueError('Too many source entries')
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != prefix:
                raise ValueError('Unsafe source path')
            if not member.isfile():
                continue
            if '.bin' in path.parts:
                continue  # Executable package-manager shims are not notice texts.
            name = path.name.lower()
            in_license_directory = any(part.lower() == 'licenses' for part in path.parts[:-1])
            if not (re.match(r'^(licen[sc]e|copying|notice|copyright|authors)(?:$|[._-])', name)
                    or name in {'readme.chromium', 'readme.qt'}
                    or (in_license_directory and path.suffix.lower() in {'', '.txt', '.md', '.html'})):
                continue
            if path.suffix.lower() in {'.py', '.js', '.ts', '.c', '.cpp', '.h', '.sh'}:
                continue
            relative = PurePosixPath(*path.parts[1:])
            if not relative.parts or '\\' in str(relative) or ':' in str(relative):
                raise ValueError('Unsafe notice destination')
            if str(relative).casefold() in seen:
                raise ValueError('Notice path collision')
            if member.size > 10_000_000 or member.size < 0:
                raise ValueError('Notice too large')
            total += member.size
            if total > 200_000_000 or len(chosen) >= 10_000:
                raise ValueError('Notice collection too large')
            content = source.extractfile(member).read(10_000_001)
            if len(content) != member.size:
                raise ValueError('Incomplete notice')
            seen.add(str(relative).casefold())
            chosen.append((relative, content))
    if not chosen:
        raise ValueError('No notice texts found')
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for relative, content in chosen:
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        files.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(content).hexdigest()})
    inventory = {'schema': 1, 'kind': 'notice-bundle', 'archive_sha256': expected_sha256,
                 'archive_prefix': prefix, 'scope': 'selected source notice filenames; all source platforms',
                 'license_clearance': 'NOT ESTABLISHED', 'files': files}
    (destination / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    return inventory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args()
    result = collect(args.archive, args.sha256, args.output, args.prefix)
    print('Collected source notice texts:', len(result['files']))
