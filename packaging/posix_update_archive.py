"""Create a POSIX update ZIP and unsigned inventory from one native bundle.

No key loading or publication. The release owner signs the exact inventory and
archive digest only after native build and staged-bundle acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

from nexus_launcher.posix_package import FORMAT, TARGETS, inventory


def build(bundle, archive, *, platform, arch, version):
    bundle, archive = Path(bundle).absolute(), Path(archive).absolute()
    expected, entry = TARGETS[(platform, arch)]
    if bundle.name != expected or not bundle.is_dir() or bundle.is_symlink() or archive.exists():
        raise ValueError('Native bundle and new output required')
    records = []
    for parent, dirs, files in os.walk(bundle, followlinks=False):
        for name in sorted(dirs + files):
            p = Path(parent) / name
            path = p.relative_to(bundle.parent).as_posix()
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode):
                records.append({'path': path, 'kind': 'symlink', 'target': os.readlink(p)})
            elif stat.S_ISREG(info.st_mode):
                with p.open('rb') as stream:
                    sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                records.append({'path': path, 'kind': 'file', 'size': info.st_size,
                                'sha256': sha, 'mode': 0o755 if info.st_mode & 0o111 else 0o644})
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError('Special file in native bundle')
    records.sort(key=lambda x: x['path'])
    payload = {'format': FORMAT, 'platform': platform, 'arch': arch, 'version': version,
               'entrypoint': entry, 'files': records}
    inventory(payload)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for item in records:
            p = bundle.parent / item['path']
            info = zipfile.ZipInfo(item['path'], date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            if item['kind'] == 'symlink':
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, item['target'].encode('utf-8'))
            else:
                info.external_attr = (stat.S_IFREG | item['mode']) << 16
                with p.open('rb') as source, z.open(info, 'w') as target:
                    sha, size = hashlib.sha256(), 0
                    while block := source.read(256 * 1024):
                        target.write(block)
                        sha.update(block)
                        size += len(block)
                    if size != item['size'] or sha.hexdigest() != item['sha256']:
                        raise ValueError('Native source changed during packaging')
    with archive.open('rb') as stream:
        payload.update(size=archive.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    return payload


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True)
    p.add_argument('--archive', required=True)
    p.add_argument('--platform', required=True, choices=['linux', 'macos'])
    p.add_argument('--arch', required=True, choices=['x64', 'arm64'])
    p.add_argument('--version', required=True)
    p.add_argument('--inventory', required=True)
    args = p.parse_args()
    result = build(args.bundle, args.archive, platform=args.platform, arch=args.arch, version=args.version)
    with Path(args.inventory).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('Created unsigned POSIX update archive; signing and native acceptance still required')
