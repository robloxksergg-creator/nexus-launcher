"""Offline operator signing for a private initial managed beta package.

Never publishes, installs, starts a program, generates a key or changes trust.
Private key stays outside the workspace and is never printed. This deliberately
does not enable a network feed or stable channel.
"""
import argparse
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path


def sign_initial(archive, draft, key, *, key_id, trusted_keys):
    from nexus_launcher.signed_release import canonical
    from nexus_launcher.portable_package import verify_portable_archive
    public = key.public_key().public_bytes_raw().hex()
    if trusted_keys.get(key_id) != public:
        raise ValueError('Signing key is not pinned in the bootstrap trust store')
    if (not isinstance(draft, dict) or draft.get('channel') != 'beta'
            or draft.get('available') is not False or draft.get('format') != 'nexus-portable-zip-v1'
            or draft.get('platform') != 'windows' or draft.get('arch') != 'x64'):
        raise ValueError('Not an unavailable private beta package draft')
    archive = Path(archive)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if draft.get('sha256') != digest or draft.get('size') != archive.stat().st_size:
        raise ValueError('Archive differs from prepared draft')
    now = datetime.now(UTC)
    payload = {**draft, 'available': True, 'distribution': 'private-bootstrap-initial',
               'published_at': now.isoformat(), 'expires_at': (now+timedelta(days=14)).isoformat()}
    envelope = {'schema': 2, 'key_id': key_id, 'release': payload,
                'signature': base64.b64encode(key.sign(canonical(payload))).decode('ascii')}
    with archive.open('rb') as stream:
        verify_portable_archive(stream, envelope, keys=trusted_keys)
    return envelope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-key', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--draft', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--key-id', default='nexus-launcher-updates-2026-01')
    parser.add_argument('--authorize-local-install', action='store_true', required=True)
    args = parser.parse_args()
    import nexus_launcher.build_channel as build_channel
    build_channel.TESTER_BUILD = True
    build_channel.STAGING_BUILD = True
    from nexus_launcher.offline_sign_release import external_key_path
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from nexus_launcher.release_metadata import METADATA
    # Uses the established external-key policy; never searches for a private key.
    key_path = external_key_path(args.private_key)
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Dedicated Ed25519 key required')
    draft = json.loads(args.draft.read_text(encoding='utf-8'))
    result = sign_initial(args.archive, draft, key, key_id=args.key_id,
                          trusted_keys=METADATA['trusted_update_keys'])
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('Private initial envelope written; no publication or installation performed.')


if __name__ == '__main__':
    main()
