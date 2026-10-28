"""Inventory candidate payload bytes, including dotfiles; no execution or signing."""
import argparse
import hashlib
import json
from pathlib import Path


def inventory(root):
    root = Path(root).resolve(strict=True)
    files = []
    seen = set()
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Candidate link escapes payload')
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.casefold() in seen:
            raise ValueError('Candidate path collision')
        if relative.split('/')[0].casefold() == 'data':
            raise ValueError('Portable user data must not ship')
        seen.add(relative.casefold())
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        files.append({'path': relative, 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size})
    if not files:
        raise ValueError('Empty candidate payload')
    return {'schema': 1, 'scope': 'candidate payload files only, including hidden paths', 'files': files}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() or output.resolve().is_relative_to(Path(args.root).resolve()):
        raise ValueError('Inventory output must be new and outside payload')
    output.write_text(json.dumps(inventory(args.root), indent=2), encoding='utf-8')
