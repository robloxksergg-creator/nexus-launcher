"""Collect notices from cached, checksum-pinned Cargo.lock registry archives."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import tomllib

collect = runpy.run_path(str(Path(__file__).with_name('collect_source_notices.py')))['collect']


def collect_locked(lockfile, caches, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Output must be a new directory')
    packages = tomllib.loads(Path(lockfile).read_text(encoding='utf-8'))['package']
    prepared = []
    seen = set()
    for package in packages:
        source = package.get('source')
        if not source:
            continue  # Workspace source is covered separately.
        if source != 'registry+https://github.com/rust-lang/crates.io-index':
            raise ValueError('Unsupported registry or Git source')
        name, version, digest = package['name'], package['version'], package.get('checksum', '')
        if not re.fullmatch('[A-Za-z0-9_-]+', name) or not re.fullmatch('[0-9A-Za-z.+-]+', version):
            raise ValueError('Unsupported crate identity')
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid crate checksum')
        key = name + '-' + version
        if key in seen:
            raise ValueError('Duplicate crate identity')
        seen.add(key)
        candidates = []
        for cache in caches:
            cache = Path(cache)
            candidates += [p for p in [cache / (key + '.crate'), *cache.glob('*/' + key + '.crate')] if p.is_file()]
        if not candidates:
            raise ValueError('Missing locked crate archive: ' + key)
        archive = candidates[0]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise ValueError('Locked crate checksum mismatch: ' + key)
        prepared.append((key, archive, digest))
    if not prepared:
        raise ValueError('No registry packages found')
    destination.mkdir(parents=True, exist_ok=False)
    for key, archive, digest in prepared:
        collect(archive, digest, destination / key, key)
    files = [{'path': p.relative_to(destination).as_posix(),
              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(destination.rglob('*')) if p.is_file()]
    result = {'schema': 1, 'kind': 'notice-bundle', 'registry_archives_verified': len(prepared),
              'scope': 'all Cargo.lock registry packages, not the actual linked closure',
              'license_clearance': 'NOT ESTABLISHED', 'files': files}
    (destination / 'inventory.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lockfile', required=True)
    parser.add_argument('--cache', action='append', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = collect_locked(args.lockfile, args.cache, args.output)
    print('Verified registry archives:', result['registry_archives_verified'])
