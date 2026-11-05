"""Offline owner signing for bounded POSIX bundles. No network or key export."""
import argparse
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import runpy

from nexus_launcher import public_update_identity as identity
from nexus_launcher.github_updates import GitHubPackageTransport
from nexus_launcher.posix_package import inventory, verify_archive
from nexus_launcher.signed_release import canonical


def build_envelope(archive, metadata, url, key, *, now=None):
    GitHubPackageTransport(url)
    if key.public_key().public_bytes_raw().hex() != identity.PUBLIC_KEY:
        raise ValueError('Wrong public preview signer')
    if not isinstance(metadata, dict) or set(metadata) != {
        'format', 'platform', 'arch', 'version', 'entrypoint', 'files', 'size', 'sha256'
    }:
        raise ValueError('Unexpected unsigned POSIX metadata')
    inventory(metadata)
    from nexus_launcher.portable_package import MAX_TOTAL_BYTES
    if type(metadata['size']) is not int or not 0 < metadata['size'] <= MAX_TOTAL_BYTES:
        raise ValueError('Invalid POSIX archive size')
    if metadata['version'] != identity.VERSION:
        raise ValueError('Wrong build-time release version')
    archive = Path(archive)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if archive.stat().st_size != metadata['size'] or digest != metadata['sha256']:
        raise ValueError('POSIX archive does not match native build receipt')
    now = now or datetime.now(UTC)
    payload = {**metadata, 'available': True, 'channel': identity.CHANNEL, 'url': url,
               'published_at': (now - timedelta(minutes=1)).isoformat(),
               'expires_at': (now + timedelta(days=30)).isoformat()}
    envelope = {'schema': 2, 'key_id': identity.KEY_ID, 'release': payload,
                'signature': base64.b64encode(key.sign(canonical(payload))).decode('ascii')}
    verify_archive(archive, envelope, keys={identity.KEY_ID: identity.PUBLIC_KEY})
    return envelope


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'inventory', 'url', 'protected-key', 'output'):
        p.add_argument('--' + name, required=True)
    args = p.parse_args()
    target = Path(args.output)
    if target.exists():
        raise ValueError('Refusing existing signed output')
    metadata = json.loads(Path(args.inventory).read_text(encoding='utf-8'))
    loader = runpy.run_path(str(Path(__file__).with_name('sign_public_update.py')))
    signed = build_envelope(args.archive, metadata, args.url, loader['load_dpapi_signer'](args.protected_key))
    with target.open('x', encoding='utf-8') as stream:
        json.dump(signed, stream, separators=(',', ':'), allow_nan=False)
    print('Signed POSIX update envelope written locally; no publication performed')
