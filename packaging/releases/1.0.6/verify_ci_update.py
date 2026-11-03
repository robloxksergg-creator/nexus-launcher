"""Offline two-version package acceptance on a disposable Windows runner.

Uses only the existing public 1.0.5 package and the hash-pinned 1.0.6 build.
Reconstructs the owner-signed envelope; no private key, accounts or live feed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main(inputs, approval, output, root):
    inputs, output, root = Path(inputs), Path(output), Path(root)
    if output.exists() or root.exists():
        raise ValueError('Fresh owned acceptance directories required')
    output.mkdir()
    initial = output / 'initial.zip'
    envelope = output / 'initial-envelope.json'
    base = 'https://github.com/robloxksergg-creator/nexus-launcher/releases/download/v1.0.5-preview.1/'
    for filename, destination, expected_size, expected_sha in [
        ('NEXUS-Managed-1.0.5-Windows-x64.zip', initial, 221535890,
         'dde4e63f4f71319fb1b1c49dade68683a5f350030b6447c6bd090c34570e6de2'),
        ('portable-envelope.json', envelope, 1302930,
         '44b3ef04650dfcd484c1fbd53f14d972df117856f068a63151ce2e6cb1e1303f'),
    ]:
        request = urllib.request.Request(base + filename, headers={'User-Agent': 'NEXUS-package-acceptance'})
        with urllib.request.urlopen(request, timeout=90) as stream, destination.open('xb') as target:
            received = 0
            while block := stream.read(1024 * 1024):
                received += len(block)
                if received > expected_size:
                    raise ValueError('Public acceptance input exceeds pinned size')
                target.write(block)
        if received != expected_size or digest(destination) != expected_sha:
            raise ValueError('Public acceptance input integrity mismatch')
    archive = inputs / 'NEXUS-Managed-1.0.6-Windows-x64.zip'
    if digest(archive) != 'd841a2125bab05ddbf7adb51f259352689f52347633f59432ee8149a8af6de64':
        raise ValueError('Candidate hash mismatch')
    compact = json.loads(Path(approval).read_text(encoding='utf-8'))
    if compact['source_commit'] != '29f9cb6a2a1796ab0a0e1b2a23d618b03822f4d8':
        raise ValueError('Wrong candidate source')
    files = []
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            with source.open(entry) as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'path': entry.filename, 'size': entry.file_size, 'sha256': sha})
    payload = {**compact['release'], 'files': files}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    if hashlib.sha256(canonical).hexdigest() != compact['canonical_sha256']:
        raise ValueError('Signed payload reconstruction mismatch')
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(
        'e5df7b42b312755a66e6f6c88368529172c4e4ed28d37354d4eea1402900925b'
    )).verify(base64.b64decode(compact['signature'], validate=True), canonical)
    candidate = output / 'candidate-envelope.json'
    signed = {k: compact[k] for k in ('schema', 'key_id', 'signature')}
    signed['release'] = payload
    candidate.write_text(json.dumps(signed), encoding='utf-8')
    from nexus_launcher import build_channel
    build_channel.PUBLIC_PREVIEW_BUILD = True
    import runpy
    harness = runpy.run_path(str(Path(__file__).parents[2] / 'verify_managed_windows.py'))
    result = harness['verify'](initial, envelope, archive, candidate, root,
                               output / 'windows-update-acceptance.json', preinstall_smoke=True)
    child = root / 'acceptance-1.json'
    smoke = json.loads(child.read_text(encoding='utf-8'))
    if not smoke['preinstall']['visible'] or smoke['preinstall']['cards'] != 5:
        raise ValueError('Packaged preparation interface missing')
    result.update(preinstall_ui_verified=True, child_report_sha256=digest(child),
                  source_commit=compact['source_commit'],
                  environment='Disposable Windows CI; does not qualify local Smart App Control policy')
    (output / 'windows-acceptance-for-publication.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    for filename in ('acceptance-0.json', 'acceptance-1.json', 'acceptance-0.png',
                     'acceptance-1.png', 'acceptance-1-preinstall.png'):
        shutil.copyfile(root / filename, output / filename)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs', 'approval', 'output', 'root'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    main(args.inputs, args.approval, args.output, args.root)
