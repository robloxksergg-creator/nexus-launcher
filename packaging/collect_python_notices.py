"""Collect installed distribution license texts; never install or contact a network.

This inventory covers only explicitly named distributions, not an entire frozen
application or its transitive/native dependencies. It is not license clearance.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re


def collect(names, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Output must be a new directory')
    prepared = []
    seen = set()
    for name in names:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            raise ValueError('Invalid distribution name')
        normalized = re.sub(r'[-_.]+', '-', name).lower()
        if normalized in seen:
            raise ValueError('Duplicate distribution')
        seen.add(normalized)
        dist = metadata.distribution(name)
        licenses = []
        for entry in dist.files or []:
            path = PurePosixPath(str(entry).replace('\\', '/'))
            # RECORD can contain paths outside site-packages. Never collect those.
            if path.is_absolute() or '..' in path.parts or ':' in str(path):
                continue
            basename = path.name.lower()
            if not basename.startswith(('license', 'copying', 'notice', 'copyright')):
                continue
            source = Path(dist.locate_file(entry))
            if source.is_symlink() or not source.is_file():
                raise ValueError('License file is missing or is a symlink')
            content = source.read_bytes()
            licenses.append((path, content))
        if not licenses:
            raise ValueError('No license texts found for ' + normalized)
        prepared.append((normalized, dist, licenses))
    if not prepared:
        raise ValueError('At least one distribution is required')
    # Validate all inputs before creating output; partial IO failures still fail.
    destination.mkdir(parents=True, exist_ok=False)
    inventory = {'scope': 'explicit installed Python distributions only',
                 'complete_frozen_inventory': False, 'distributions': []}
    for name, dist, licenses in prepared:
        item = {'name': dist.metadata['Name'], 'version': dist.version,
                'license_expression': dist.metadata.get('License-Expression'),
                'files': []}
        for relative, content in licenses:
            target = destination / name / str(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            item['files'].append({'path': target.relative_to(destination).as_posix(),
                                  'sha256': hashlib.sha256(content).hexdigest()})
        inventory['distributions'].append(item)
    (destination / 'inventory.json').write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('distributions', nargs='+')
    args = parser.parse_args()
    result = collect(args.distributions, args.output)
    print('Collected notices for', len(result['distributions']), 'distributions')


if __name__ == '__main__':
    main()
