"""Assemble only the accepted beta artifacts; no key loading or publication."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from verify_tester_windows import reconstruct

SETUP_SHA = 'ca47d34d2855d8d6036a6f86177c8b892c5406c591c2388278fed47f763d7f86'
PACKAGE_SHA = 'f52bb7df3cdc24edfd094034ff2f835edad0b68db187d8b0992d8df01ffdc940'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(inputs, output, approval, instructions, notes):
    import nexus_launcher.build_channel as channel
    channel.PUBLIC_PREVIEW_BUILD = True
    from nexus_launcher import public_update_identity
    if public_update_identity.CHANNEL != 'beta':
        raise ValueError('Dedicated beta verification source required')
    inputs, output = Path(inputs), Path(output)
    if output.exists():
        raise ValueError('Output must be new')
    acceptance = json.loads((inputs / 'acceptance/TESTER-ACCEPTANCE.json').read_text('utf-8'))
    if (acceptance.get('versions') != [{'version': '1.0.11', 'native_readiness': 'PASS'},
                                     {'version': '1.0.12', 'native_readiness': 'PASS'}]
            or acceptance.get('user_data_preserved') is not True
            or acceptance.get('channel') != 'beta'
            or acceptance.get('fresh_install_version') != '1.0.12'
            or acceptance.get('installer_copy_verified') is not True
            or acceptance.get('files_verified') != 5540):
        raise ValueError('Exact native beta acceptance missing')
    archive = inputs / 'managed/NEXUS-Managed-1.0.12-Windows-x64.zip'
    installer = inputs / 'installer/NEXUS-Setup.exe'
    if digest(archive) != PACKAGE_SHA or digest(installer) != SETUP_SHA:
        raise ValueError('Accepted artifact bytes changed')
    output.mkdir(parents=True)
    envelope = reconstruct(archive, approval, output / 'portable-envelope.json')
    if (envelope['release']['version'] != '1.0.12'
            or envelope['release']['url'] != 'https://github.com/robloxksergg-creator/nexus-launcher/releases/download/v1.0.12-testers.1/' + archive.name):
        raise ValueError('Unexpected beta release identity')
    shutil.copy2(archive, output / archive.name)
    shutil.copy2(installer, output / 'NEXUS-Testers-Setup.exe')
    shutil.copy2(instructions, output / 'TESTER-INSTRUCTIONS.md')
    shutil.copy2(notes, output / 'RELEASE-NOTES.md')
    # A minimal receipt contains no account/session data or local machine paths.
    (output / 'VERIFICATION.json').write_text(json.dumps({
        'version': '1.0.12', 'channel': 'beta', 'files_verified': 5540,
        'native_update': 'PASS: 1.0.11 -> 1.0.12', 'fresh_install': 'PASS',
        'synthetic_user_data_preserved': True, 'source_commit': 'bc9d5a65d5792a9fce434b0d2fdabecbae5d966b',
        'acceptance_run': 42477565294, 'package_sha256': PACKAGE_SHA,
        'setup_sha256': SETUP_SHA, 'scope': 'Windows x64; no live account/game/VPN qualification'
    }, indent=2), encoding='utf-8')
    sums = ''.join(digest(p) + '  ' + p.name + '\n' for p in sorted(output.iterdir()) if p.is_file())
    (output / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')
    return {'status': 'BETA ARTIFACTS VERIFIED', 'output_files': len(list(output.iterdir()))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs', 'output', 'approval', 'instructions', 'notes'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.inputs, args.output, args.approval, args.instructions, args.notes)))
