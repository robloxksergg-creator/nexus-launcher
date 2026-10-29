"""Offline owner signing tool. No network, publication or private-key export."""
import argparse
import base64
import ctypes
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nexus_launcher import public_update_identity as identity
from nexus_launcher.github_updates import GitHubPackageTransport
from nexus_launcher.portable_package import MAX_FILES, MAX_TOTAL_BYTES, verify_portable_archive
from nexus_launcher.safe_paths import relative_parts
from nexus_launcher.signed_release import canonical


def load_dpapi_signer(path):
    if os.name != 'nt':
        raise OSError('Windows current-user DPAPI required')

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    encrypted = Path(path).read_bytes()
    if not 1 <= len(encrypted) <= 16384:
        raise ValueError('Invalid protected key size')
    buffer = ctypes.create_string_buffer(encrypted)
    source = Blob(len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    free = ctypes.WinDLL('kernel32', use_last_error=True).LocalFree
    free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
    unprotect = crypt.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    unprotect.restype = wintypes.BOOL
    if not unprotect(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError('Cannot unlock signing key for this Windows user')
    try:
        key = Ed25519PrivateKey.from_private_bytes(ctypes.string_at(output.data, output.size))
    finally:
        ctypes.memset(output.data, 0, output.size)
        free(output.data)
    if key.public_key().public_bytes_raw().hex() != identity.PUBLIC_KEY:
        raise ValueError('Signer does not match the new public preview identity')
    return key


def build_envelope(archive, url, key, *, now=None):
    # Validate a literal repository release asset before reading/signing inputs.
    GitHubPackageTransport(url)
    if key.public_key().public_bytes_raw().hex() != identity.PUBLIC_KEY:
        raise ValueError('Wrong public preview signer')
    archive = Path(archive)
    size = archive.stat().st_size
    if not 0 < size <= MAX_TOTAL_BYTES:
        raise ValueError('Invalid archive size')
    files, names, total = [], set(), 0
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if not 1 <= len(members) <= MAX_FILES:
            raise ValueError('Invalid package file count')
        for member in members:
            relative_parts(member.filename)
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (member.is_dir() or member.flag_bits & 1 or mode not in (0, stat.S_IFREG)
                    or member.filename != member.orig_filename or member.filename.casefold() in names):
                raise ValueError('Invalid package entry')
            names.add(member.filename.casefold())
            total += member.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError('Expanded package too large')
            with source.open(member) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'path': member.filename, 'size': member.file_size, 'sha256': digest})
    now = now or datetime.now(UTC)
    with archive.open('rb') as stream:
        archive_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    payload = {'format': 'nexus-portable-zip-v1', 'version': identity.VERSION,
               'entrypoint': 'NEXUS Managed Launcher.exe', 'channel': identity.CHANNEL,
               'available': True, 'platform': 'windows', 'arch': 'x64',
               'published_at': (now - timedelta(minutes=1)).isoformat(),
               'expires_at': (now + timedelta(days=30)).isoformat(),
               'url': url, 'size': size, 'sha256': archive_hash, 'files': files}
    envelope = {'schema': 2, 'key_id': identity.KEY_ID, 'release': payload,
                'signature': base64.b64encode(key.sign(canonical(payload))).decode('ascii')}
    verify_portable_archive(archive, envelope, keys={identity.KEY_ID: identity.PUBLIC_KEY})
    return envelope


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--protected-key', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        raise ValueError('Refusing to overwrite existing signed metadata')
    envelope = build_envelope(args.archive, args.url, load_dpapi_signer(args.protected_key))
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(envelope, stream, separators=(',', ':'), allow_nan=False)
    print('Signed public preview envelope written; no publication performed')
