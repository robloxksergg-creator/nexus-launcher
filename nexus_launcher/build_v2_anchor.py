"""Build-time PUBLIC metadata embedding. Never generates or loads signing keys."""
import hashlib
from pathlib import Path

from nexus_launcher.update_v2_trust import validate_root


def render_public_anchor(raw: bytes) -> str:
    validate_root(raw)
    return ('# Generated public-only NEXUS v2 build anchor.\n'
            f'ROOT_JSON = {raw!r}\n'
            f'ROOT_SHA256 = {hashlib.sha256(raw).hexdigest()!r}\n')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.public_root.open('rb') as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    rendered = render_public_anchor(raw)
    # Never overwrite an existing anchor or source implicitly.
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(rendered)


if __name__ == '__main__':
    main()
