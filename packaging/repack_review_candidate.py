"""Add reviewed notices to a pinned CI ZIP without rebuilding or signing code."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import zipfile

verify = runpy.run_path(str(Path(__file__).with_name('verify_notices.py')))['verify']
NOTICE_PREFIX = 'NEXUS Launcher/_internal/third-party-notices/'
COPYRIGHT = 'NEXUS Launcher/_internal/COPYRIGHT.md'
EXE = 'NEXUS Launcher/NEXUS Launcher.exe'


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def repack(source, expected_sha256, notices, copyright_file, output):
    source, notices, output = Path(source), Path(notices), Path(output)
    if output.exists():
        raise ValueError('Output must be a new file')
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256) or file_hash(source) != expected_sha256:
        raise ValueError('CI archive checksum mismatch')
    verify(notices)
    copyright_bytes = Path(copyright_file).read_bytes()
    if len(copyright_bytes) > 1_000_000:
        raise ValueError('Copyright notice too large')
    retained = {}
    with zipfile.ZipFile(source) as original:
        names = set()
        total = 0
        for info in original.infolist():
            p = PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or ':' in info.filename:
                raise ValueError('Unsafe CI archive path')
            if info.filename.casefold() in names:
                raise ValueError('Duplicate CI archive path')
            names.add(info.filename.casefold())
            total += info.file_size
            if info.file_size > 500_000_000 or total > 3_000_000_000:
                raise ValueError('CI archive size limit')
        if EXE.casefold() not in names or COPYRIGHT.casefold() not in names:
            raise ValueError('Candidate structure missing')
        if 'repack-provenance.json' in names:
            raise ValueError('Expected original CI artifact, not an earlier repack')
        with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as target:
            for info in original.infolist():
                if info.is_dir() or info.filename.startswith(NOTICE_PREFIX):
                    continue
                content = original.read(info)
                if info.filename == COPYRIGHT:
                    content = copyright_bytes
                else:
                    retained[info.filename] = hashlib.sha256(content).hexdigest()
                target.writestr(info.filename, content)
            for path in sorted(notices.rglob('*')):
                if path.is_file():
                    target.write(path, NOTICE_PREFIX + path.relative_to(notices).as_posix())
            provenance = {'parent_ci_archive_sha256': expected_sha256,
                          'retained_files': retained,
                          'replaced_text_files': {COPYRIGHT: hashlib.sha256(copyright_bytes).hexdigest()},
                          'notice_inventory_sha256': file_hash(notices / 'inventory.json'),
                          'signing': 'NOT SIGNED', 'license_clearance': 'NOT ESTABLISHED',
                          'execution': 'NOT REPEATED; parent CI execution evidence preserved'}
            target.writestr('REPACK-PROVENANCE.json', json.dumps(provenance, indent=2))
    with zipfile.ZipFile(output) as result:
        if result.testzip() is not None:
            raise ValueError('Output ZIP CRC failure')
        for name, expected in retained.items():
            if hashlib.sha256(result.read(name)).hexdigest() != expected:
                raise ValueError('Retained file changed: ' + name)
    verify(notices)
    return {'sha256': file_hash(output), 'retained_files': len(retained),
            'exe_sha256': retained[EXE], 'signing': 'NOT SIGNED'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--notices', required=True)
    parser.add_argument('--copyright', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(repack(args.source, args.sha256, args.notices, args.copyright, args.output)))
