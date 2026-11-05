"""Offline two-version package acceptance on a disposable Windows runner.

Uses only the existing public 1.0.8 package and the hash-pinned 1.0.9 build.
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


def main(inputs, approval, output, root, installer):
    inputs, output, root = Path(inputs), Path(output), Path(root)
    if output.exists() or root.exists():
        raise ValueError('Fresh owned acceptance directories required')
    output.mkdir()
    initial = output / 'initial.zip'
    envelope = output / 'initial-envelope.json'
    base = 'https://github.com/robloxksergg-creator/nexus-launcher/releases/download/v1.0.8-preview.1/'
    for filename, destination, expected_size, expected_sha in [
        ('NEXUS-Managed-1.0.8-Windows-x64.zip', initial, 221575997,
         'bf6fbc5e19d3d57607d980b6e85c593ab1d6ff072b732ef9fd925af580878ea0'),
        ('portable-envelope.json', envelope, 1059111,
         '87a12f5b8562185b1b4178666a35bf7229cbc8e24214d601dfa4d996f5a2bc38'),
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
    archive = inputs / 'NEXUS-Managed-1.0.9-Windows-x64.zip'
    if digest(archive) != '2bf3ca7c3d3f516b2d730c599fc7e56b8918c28d3a2785bcd6e967b0783127b5':
        raise ValueError('Candidate hash mismatch')
    compact = json.loads(Path(approval).read_text(encoding='utf-8'))
    if compact['source_commit'] != '4f132b555ab6a1a20d3c8a548ed33d940c1b17ce':
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
    if digest(installer) != '70df05da40d73591f645827f42345ab30429feec70e90ed6f025a9d9c870db87':
        raise ValueError('Installer hash mismatch')
    # Inspect the actual one-file payload; exercise its bundled native helper
    # without UAC or live accounts. The Python EXE must never be the runas target.
    from PyInstaller.archive.readers import CArchiveReader
    import subprocess
    reader = CArchiveReader(str(installer))
    members = [n for n in reader.toc if n.replace('\\', '/') == 'installer-tools/NEXUS-Directory-Helper.exe']
    if len(members) != 1:
        raise ValueError('Native folder helper not bundled exactly once')
    helper = output / 'NEXUS-Directory-Helper.exe'
    helper.write_bytes(reader.extract(members[0]))
    from nexus_launcher.installer_permissions import current_sid
    sid = current_sid()
    owned = output / 'helper-created-folder'
    subprocess.run([str(helper), str(owned), sid], check=True, timeout=30)
    (owned / 'sentinel').write_bytes(b'PRESERVE')
    for path, account in [(str(owned), sid), (str(output / 'broad-sid-rejected'), 'S-1-1-0'),
                          (str(output.anchor), sid), ('relative', sid)]:
        refused = subprocess.run([str(helper), path, account], timeout=30)
        if refused.returncode == 0:
            raise ValueError('Native helper accepted forbidden request')
    if (owned / 'sentinel').read_bytes() != b'PRESERVE':
        raise ValueError('Native helper changed existing data')
    from nexus_launcher import build_channel
    build_channel.PUBLIC_PREVIEW_BUILD = True
    import runpy
    installation = runpy.run_path(str(Path(__file__).with_name('verify_ci_installation.py')))
    installation['verify'](archive, candidate, installer, root.with_name(root.name + '-install') / 'NEXUS Launcher' / 'NEXUS Launcher',
                           output / 'full-install-acceptance.json', output / 'completion.png')
    harness = runpy.run_path(str(Path(__file__).parents[2] / 'verify_managed_windows.py'))
    result = harness['verify'](initial, envelope, archive, candidate, root,
                               output / 'windows-update-acceptance.json', preinstall_smoke=True)
    child = root / 'acceptance-1.json'
    smoke = json.loads(child.read_text(encoding='utf-8'))
    if not smoke['preinstall']['visible'] or smoke['preinstall']['cards'] != 5:
        raise ValueError('Packaged preparation interface missing')
    result.update(preinstall_ui_verified=True, child_report_sha256=digest(child),
                  source_commit=compact['source_commit'],
                  bundled_native_helper_verified=True, helper_sha256=digest(helper),
                  interactive_uac='NOT AUTOMATED; no elevation prompt accepted by CI',
                  environment='Disposable Windows CI; does not qualify local Smart App Control policy')
    (output / 'windows-acceptance-for-publication.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    for filename in ('acceptance-0.json', 'acceptance-1.json', 'acceptance-0.png',
                     'acceptance-1.png', 'acceptance-1-preinstall.png'):
        shutil.copyfile(root / filename, output / filename)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs', 'approval', 'output', 'root', 'installer'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    main(args.inputs, args.approval, args.output, args.root, args.installer)
