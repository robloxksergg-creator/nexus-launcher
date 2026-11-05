"""Verify pinned Windows hotfix bytes and native acceptance before publication."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SOURCE = '4f132b555ab6a1a20d3c8a548ed33d940c1b17ce'
PUBLIC_KEY = 'e5df7b42b312755a66e6f6c88368529172c4e4ed28d37354d4eea1402900925b'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(root, output, approval):
    from nexus_launcher.portable_package import verify_portable_archive
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('Fresh publication output required')
    compact = json.loads(Path(approval).read_text(encoding='utf-8'))
    if compact['source_commit'] != SOURCE or compact['schema'] != 2 or compact['key_id'] != 'nexus-public-preview-20261029':
        raise ValueError('Wrong owner approval identity')
    archive = root / 'windows/NEXUS-Managed-1.0.9-Windows-x64.zip'
    installer = root / 'installer/NEXUS-Setup.exe'
    if digest(installer) != compact['installer_sha256']:
        raise ValueError('Installer integrity mismatch')
    files = []
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            with z.open(item) as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'path': item.filename, 'size': item.file_size, 'sha256': sha})
    payload = {**compact['release'], 'files': files}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    if hashlib.sha256(canonical).hexdigest() != compact['canonical_sha256']:
        raise ValueError('Signed payload reconstruction mismatch')
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY)).verify(
        base64.b64decode(compact['signature'], validate=True), canonical)
    envelope = {**{k: compact[k] for k in ('schema', 'key_id', 'signature')}, 'release': payload}
    if payload['version'] != '1.0.9' or payload['platform'] != 'windows' or payload['arch'] != 'x64':
        raise ValueError('Wrong release platform/version')
    verify_portable_archive(archive, envelope, keys={compact['key_id']: PUBLIC_KEY})
    acceptance = json.loads((root / 'acceptance/windows-acceptance-for-publication.json').read_text(encoding='utf-8'))
    installation = json.loads((root / 'acceptance/full-install-acceptance.json').read_text(encoding='utf-8'))
    if (acceptance['source_commit'] != SOURCE or acceptance['user_data_preserved'] is not True
            or acceptance['preinstall_ui_verified'] is not True or acceptance['bundled_native_helper_verified'] is not True
            or acceptance['versions'] != [{'version': '1.0.8', 'native_readiness': 'PASS'},
                                          {'version': '1.0.9', 'native_readiness': 'PASS'}]):
        raise ValueError('Exact native update/helper acceptance missing')
    if (installation['version'] != '1.0.9' or installation['files_verified'] != len(files)
            or installation['completion_visible'] is not True or installation['installer_copy_verified'] is not True
            or installation['long_paths_reported_disabled'] is not True or installation['max_destination_units'] >= 248):
        raise ValueError('Long destination installation acceptance missing')
    output.mkdir()
    for p in (archive, installer):
        shutil.copyfile(p, output / p.name)
    (output / 'portable-envelope.json').write_text(json.dumps(envelope, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('RELEASE-NOTES.md'), output / 'RELEASE-NOTES.md')
    shutil.copyfile(root / 'acceptance/windows-acceptance-for-publication.json', output / 'windows-update-acceptance.json')
    shutil.copyfile(root / 'acceptance/full-install-acceptance.json', output / 'windows-install-acceptance.json')
    (output / 'SHA256SUMS.txt').write_text(''.join(digest(p) + '  ' + p.name + '\n' for p in sorted(output.iterdir())), encoding='utf-8')
    print('Windows hotfix bytes, owner signature, long destination and native helper acceptance verified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input', 'output', 'approval'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    prepare(args.input, args.output, args.approval)
