"""Combine verified notice collections; no downloads or legal-clearance grant."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy

verify = runpy.run_path(str(Path(__file__).with_name('verify_notices.py')))['verify']


def assemble(groups, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Output must be a new directory')
    prepared = []
    seen = set()
    for name, root in groups:
        if not re.fullmatch('[a-z][a-z0-9-]{0,39}', name) or name in seen:
            raise ValueError('Invalid or duplicate notice group')
        seen.add(name)
        root = Path(root).resolve(strict=True)
        verify(root)
        prepared.append((name, root))
    if not prepared:
        raise ValueError('At least one notice group is required')
    destination.mkdir(parents=True, exist_ok=False)
    entries = []
    for name, root in prepared:
        for source in sorted(root.rglob('*')):
            if not source.is_file():
                continue
            if source.is_symlink() or not source.resolve().is_relative_to(root):
                raise ValueError('Notice source escapes collection')
            relative = Path(name) / source.relative_to(root)
            data = source.read_bytes()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entries.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(data).hexdigest()})
        # Detect ordinary edits during collection; this is not an immutability
        # guarantee against privileged writers or a durability/trust protocol.
        verify(root)
    inventory = {'schema': 1, 'kind': 'notice-bundle', 'groups': [name for name, root in prepared],
                 'license_clearance': 'NOT ESTABLISHED',
                 'scope': 'reviewed notice collections; actual linked license closure requires review',
                 'files': entries}
    (destination / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    verify(destination)
    return inventory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--group', action='append', required=True, help='name=collection-directory')
    args = parser.parse_args()
    groups = [value.split('=', 1) for value in args.group]
    if any(len(group) != 2 for group in groups):
        parser.error('Each group must be name=directory')
    result = assemble(groups, args.output)
    print('Combined notice files:', len(result['files']))
