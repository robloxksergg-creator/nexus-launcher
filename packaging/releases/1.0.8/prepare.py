"""Reconstruct owner-signed envelopes from pinned native packages and receipts.

No private key, remote mutation, live account or game launch is performed here.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PUBLIC_KEY = 'e5df7b42b312755a66e6f6c88368529172c4e4ed28d37354d4eea1402900925b'
KEY_ID = 'nexus-public-preview-20261029'
SOURCE = 'e2440128336b3cd9c60e190d2e010738c8de26a3'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reconstruct(compact, files):
    if compact['schema'] != 2 or compact['key_id'] != KEY_ID:
        raise ValueError('Wrong envelope identity')
    payload = {**compact['release'], 'files': files}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, allow_nan=False).encode()
    if hashlib.sha256(canonical).hexdigest() != compact['canonical_sha256']:
        raise ValueError('Owner payload reconstruction mismatch')
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY)).verify(
        base64.b64decode(compact['signature'], validate=True), canonical)
    if payload['version'] != '1.0.8' or payload['channel'] != 'stable' or payload['available'] is not True:
        raise ValueError('Wrong signed release')
    return {**{k: compact[k] for k in ('schema', 'key_id', 'signature')}, 'release': payload}


def windows_files(archive):
    files = []
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            with source.open(item) as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'path': item.filename, 'size': item.file_size, 'sha256': sha})
    return files


def prepare(root, output, approval):
    from nexus_launcher.portable_package import verify_portable_archive
    root, output = Path(root), Path(output)
    record = json.loads(Path(approval).read_text(encoding='utf-8'))
    if output.exists() or record['source_commit'] != SOURCE:
        raise ValueError('Fresh output and approved source required')
    for name, expected in record['packages'].items():
        path = root / name
        if path.stat().st_size != expected['size'] or digest(path) != expected['sha256']:
            raise ValueError('Pinned package mismatch: ' + name)
    windows = root / 'windows/NEXUS-Managed-1.0.8-Windows-x64.zip'
    envelopes = {'portable-envelope.json': reconstruct(record['envelopes']['windows'], windows_files(windows))}
    verify_portable_archive(windows, envelopes['portable-envelope.json'], keys={KEY_ID: PUBLIC_KEY})
    for platform, arch in [('linux', 'x64'), ('macos', 'arm64')]:
        metadata = json.loads((root / platform / f'posix-inventory-{platform}-{arch}.json').read_text(encoding='utf-8'))
        name = f'posix-envelope-{platform}-{arch}.json'
        envelopes[name] = reconstruct(record['envelopes'][platform], metadata['files'])
        payload = envelopes[name]['release']
        if payload['platform'] != platform or payload['arch'] != arch:
            raise ValueError('Wrong platform binding')
        archive = root / platform / ('NEXUS-Update-1.0.8-' + ('Linux-x64' if platform == 'linux' else 'macOS-arm64') + '.zip')
        verify_portable_archive(archive, envelopes[name], keys={KEY_ID: PUBLIC_KEY})
        native = json.loads((root / platform / 'posix-update-receipts/native-posix-update-acceptance.json').read_text(encoding='utf-8'))
        if (native['platform'] != platform or native['arch'] != arch
                or native['initial_adoption_verified'] is not True or native['user_data_preserved'] is not True
                or native['versions'] != [{'version': '1.0.8', 'native_readiness': 'PASS'},
                                          {'version': '1.0.9', 'native_readiness': 'PASS'}]):
            raise ValueError('Native POSIX acceptance missing')
    acceptance = json.loads((root / 'acceptance/windows-acceptance-for-publication.json').read_text(encoding='utf-8'))
    installation = json.loads((root / 'acceptance/full-install-acceptance.json').read_text(encoding='utf-8'))
    if (acceptance['source_commit'] != SOURCE or acceptance['user_data_preserved'] is not True
            or acceptance['preinstall_ui_verified'] is not True
            or acceptance['versions'] != [{'version': '1.0.7', 'native_readiness': 'PASS'},
                                           {'version': '1.0.8', 'native_readiness': 'PASS'}]):
        raise ValueError('Owner-signed Windows update acceptance missing')
    if (installation['version'] != '1.0.8' or installation['completion_visible'] is not True
            or installation['installer_copy_verified'] is not True
            or installation['files_verified'] != len(envelopes['portable-envelope.json']['release']['files'])):
        raise ValueError('Full installation acceptance missing')
    output.mkdir()
    for name in record['packages']:
        if name.endswith(('.exe', '.zip', '.tar.gz')):
            shutil.copyfile(root / name, output / Path(name).name)
    for name, envelope in envelopes.items():
        (output / name).write_text(json.dumps(envelope, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    for name in ('RELEASE-NOTES.md', 'AUTOUPDATE.md'):
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    shutil.copyfile(root / 'acceptance/windows-acceptance-for-publication.json', output / 'windows-update-acceptance.json')
    shutil.copyfile(root / 'acceptance/full-install-acceptance.json', output / 'windows-install-acceptance.json')
    for platform in ('linux', 'macos'):
        shutil.copyfile(root / platform / 'posix-update-receipts/native-posix-update-acceptance.json', output / f'{platform}-synthetic-update-acceptance.json')
    (output / 'SHA256SUMS.txt').write_text(''.join(digest(p) + '  ' + p.name + '\n' for p in sorted(output.iterdir())), encoding='utf-8')
    print('All pinned packages, three owner signatures and native receipts verified; no publication')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input', 'output', 'approval'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    prepare(args.input, args.output, args.approval)
