"""Isolated nexus-update-v2 trust; no networking, installation or legacy state.

TUF public Metadata API verifies root signatures. The standard public Updater
verifies complete top-level metadata bundles with an in-memory-only fetcher.
This is not an installer: target bytes and NEXUS security policy are Phase 3.
"""
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

from tuf.api.metadata import Metadata, Root
from tuf.api.exceptions import DownloadHTTPError
from tuf.ngclient import Updater
from tuf.ngclient.config import UpdaterConfig
from tuf.ngclient.fetcher import FetcherInterface

import nexus_launcher.update_v2_anchor as update_v2_anchor
from nexus_launcher.safe_paths import checked_path, pinned_directory, replace_file

LIMIT = 4 * 1024 * 1024
STATE_LIMIT = 32 * 1024 * 1024
ROLES = ('timestamp', 'snapshot', 'targets')
BASE = 'https://nexus-update-v2.invalid/metadata/'


class TrustError(ValueError):
    """Fail closed; do not reset history or fall back to legacy verification."""


def _canonical(value):
    # Only for local receipts, NOT TUF signature canonicalization.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TrustError('Duplicate JSON key')
        result[key] = value
    return result


def _json(raw, limit=LIMIT):
    if not isinstance(raw, bytes) or not raw or len(raw) > limit:
        raise TrustError('Invalid metadata length')
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(TrustError('Non-finite JSON')))


def _metadata(raw, role):
    value = _json(raw)
    if not isinstance(value, dict) or set(value) != {'signed', 'signatures'}:
        raise TrustError('Unsupported TUF envelope')
    # No private material belongs in client trust metadata, even as unknown fields.
    def public_only(item):
        if isinstance(item, dict):
            if any(str(k).lower() in {'private', 'private_key', 'secret'} for k in item):
                raise TrustError('Private material forbidden in public metadata')
            for child in item.values():
                public_only(child)
        elif isinstance(item, list):
            for child in item:
                public_only(child)
    public_only(value)
    md = Metadata.from_bytes(raw)
    if md.signed.type != role or type(md.signed.version) is not int or md.signed.version < 1:
        raise TrustError('Wrong metadata role or version')
    return md


def validate_root(raw):
    """Public-only root profile. Signature operations are delegated to TUF."""
    md = _metadata(raw, 'root')
    root = md.signed
    if set(root.roles) != {'root', 'targets', 'timestamp', 'snapshot'} or not root.consistent_snapshot:
        raise TrustError('Unsupported root role profile')
    seen = set()
    for role, grant in root.roles.items():
        if (len(grant.keyids) != len(set(grant.keyids))
                or type(grant.threshold) is not int):
            raise TrustError('Invalid role grant')
        if role == 'root' and (grant.threshold != 2 or len(grant.keyids) != 3):
            raise TrustError('Root requires 2 of 3 keys')
        if role == 'targets' and (grant.threshold != 2 or len(grant.keyids) < 2):
            raise TrustError('Release and policy require two keys')
        if not 1 <= grant.threshold <= len(grant.keyids):
            raise TrustError('Invalid signature threshold')
        for keyid in grant.keyids:
            key = root.keys[keyid]
            if key.keytype != 'ed25519' or key.scheme != 'ed25519':
                raise TrustError('Only Ed25519 keys are permitted')
            public = bytes.fromhex(key.keyval['public'])
            if len(public) != 32 or public in seen:
                raise TrustError('Keys must be distinct across all roles')
            seen.add(public)
            if set(key.keyval) != {'public'}:
                raise TrustError('Only public key material is permitted')
    if set(root.keys) != {k for grant in root.roles.values() for k in grant.keyids}:
        raise TrustError('Unassigned root keys forbidden')
    root.verify_delegate('root', md.signed_bytes, md.signatures)
    return md


def _anchor():
    raw, expected = update_v2_anchor.ROOT_JSON, update_v2_anchor.ROOT_SHA256
    if (not isinstance(raw, bytes) or not isinstance(expected, str)
            or hashlib.sha256(raw).hexdigest() != expected):
        raise TrustError('No valid build-pinned v2 root')
    validate_root(raw)
    return raw


@contextmanager
def _lock(directory):
    with pinned_directory(directory):
        with checked_path(directory, 'trust.lock').open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def _write(directory, state):
    content = _canonical(state)
    wrapper = _canonical({'state': state, 'sha256': hashlib.sha256(content).hexdigest()})
    if len(wrapper) > STATE_LIMIT:
        raise TrustError('Trust history storage limit reached')
    fd, name = tempfile.mkstemp(prefix='trust-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(wrapper)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(name, checked_path(directory, 'trust-state.json'))
    finally:
        Path(name).unlink(missing_ok=True)


class _BundleFetcher(FetcherInterface):
    """Cannot access the network. Missing roots are deliberately final (404)."""
    def __init__(self, bundle):
        self.bundle = bundle

    def _fetch(self, url):
        if not url.startswith(BASE):
            raise TrustError('Unexpected metadata origin')
        name = url[len(BASE):]
        if name not in self.bundle:
            raise DownloadHTTPError('No supplied metadata', 404)
        return iter((self.bundle[name],))


def _verify_bundle(root_raw, metadata):
    parsed = {role: _metadata(metadata[role], role) for role in ROLES}
    root = validate_root(root_raw).signed
    for role, md in parsed.items():
        root.verify_delegate(role, md.signed_bytes, md.signatures)
    # No delegations accepted in this Phase 2 top-level-only contract.
    if parsed['targets'].signed.delegations is not None:
        raise TrustError('Delegated targets are not enabled')
    wire = {'timestamp.json': metadata['timestamp']}
    for role in ('snapshot', 'targets'):
        wire[f'{parsed[role].signed.version}.{role}.json'] = metadata[role]
    with tempfile.TemporaryDirectory(prefix='nexus-v2-tuf-') as directory:
        updater = Updater(directory, BASE, fetcher=_BundleFetcher(wire), bootstrap=root_raw,
                          config=UpdaterConfig(max_root_rotations=1, max_delegations=0,
                                               targets_max_length=LIMIT))
        updater.refresh()
    return parsed


class TrustStore:
    """Explicitly initialized, versioned, separate v2 state directory.

    Every read rebuilds the root chain from the compiled anchor. A local digest
    detects accidental corruption, not malicious disk rollback by the user/admin.
    No method installs a target or grants authority from timestamp/snapshot alone.
    """
    def __init__(self, directory):
        self.directory = Path(directory).absolute()

    @classmethod
    def initialize(cls, directory):
        raw = _anchor()
        directory = Path(directory).absolute()
        checked_path(directory, 'trust-state.json')
        # An existing directory, including an interrupted initialization, is not
        # silently adopted or reset. Recovery requires explicit operator action.
        directory.mkdir(exist_ok=False)
        with _lock(directory):
            _write(directory, {'schema': 1, 'protocol': 'nexus-update-v2',
                               'anchor': hashlib.sha256(raw).hexdigest(), 'generation': 0,
                               'roots': [], 'metadata': None, 'checked_at': None})
        return cls(directory)

    def _load(self):
        anchor = _anchor()
        with checked_path(self.directory, 'trust-state.json').open('rb') as stream:
            wrapper = _json(stream.read(STATE_LIMIT + 1), STATE_LIMIT)
        if (not isinstance(wrapper, dict) or set(wrapper) != {'state', 'sha256'}
                or hashlib.sha256(_canonical(wrapper['state'])).hexdigest() != wrapper['sha256']):
            raise TrustError('Damaged trust state')
        state = wrapper['state']
        if (not isinstance(state, dict)
                or set(state) != {'schema', 'protocol', 'anchor', 'generation', 'roots', 'metadata', 'checked_at'}
                or type(state['schema']) is not int or state['schema'] != 1
                or state['protocol'] != 'nexus-update-v2'
                or state['anchor'] != hashlib.sha256(anchor).hexdigest()
                or type(state['generation']) is not int or state['generation'] < 0
                or not isinstance(state['roots'], list)):
            raise TrustError('Incompatible trust state; never reset automatically')
        roots = [anchor]
        current = validate_root(anchor)
        for text in state['roots']:
            raw = text.encode('utf-8')
            new = validate_root(raw)
            if new.signed.version != current.signed.version + 1:
                raise TrustError('Non-sequential root history')
            current.signed.verify_delegate('root', new.signed_bytes, new.signatures)
            current = new
            roots.append(raw)
        receipt = state['metadata']
        if receipt is not None:
            if not isinstance(receipt, dict) or set(receipt) != {'root_version', *ROLES}:
                raise TrustError('Damaged metadata receipt')
            index = receipt['root_version'] - validate_root(anchor).signed.version
            if type(receipt['root_version']) is not int or not 0 <= index < len(roots):
                raise TrustError('Unknown receipt root')
            owner = validate_root(roots[index]).signed
            for role in ROLES:
                md = _metadata(receipt[role].encode('utf-8'), role)
                owner.verify_delegate(role, md.signed_bytes, md.signatures)
        if state['checked_at'] is not None:
            checked = datetime.fromisoformat(state['checked_at'])
            if checked.tzinfo is None:
                raise TrustError('Invalid trusted time receipt')
        if state['generation'] < len(state['roots']) + (receipt is not None):
            raise TrustError('Invalid generation')
        return state, roots[-1], current

    def inspect(self):
        with _lock(self.directory):
            state, _, current = self._load()
            return {'protocol': state['protocol'], 'generation': state['generation'],
                    'root_version': current.signed.version,
                    'metadata_versions': None if state['metadata'] is None else {
                        r: _metadata(state['metadata'][r].encode(), r).signed.version for r in ROLES}}

    def rotate_root(self, raw):
        with _lock(self.directory):
            state, _, old = self._load()
            new = validate_root(raw)
            if new.signed.version != old.signed.version + 1:
                raise TrustError('Root rotation must be exactly N+1')
            old.signed.verify_delegate('root', new.signed_bytes, new.signatures)
            # New root self-threshold already verified in validate_root().
            state['roots'].append(raw.decode('utf-8'))
            state['generation'] += 1
            _write(self.directory, state)

    def accept_bundle(self, *, timestamp, snapshot, targets):
        """Authenticate a COMPLETE metadata set, never executable bytes.

        Phase 3 must additionally verify target bytes, package contract and
        monotonic security policy before any staging/launch action.
        """
        metadata = {'timestamp': timestamp, 'snapshot': snapshot, 'targets': targets}
        with _lock(self.directory):
            state, root_raw, root = self._load()
            now = datetime.now(UTC)
            if state['checked_at'] is not None and now < datetime.fromisoformat(state['checked_at']):
                raise TrustError('Clock moved behind trusted refresh')
            parsed = {r: _metadata(metadata[r], r) for r in ROLES}
            old = state['metadata']
            if old is not None:
                for role, md in parsed.items():
                    previous = _metadata(old[role].encode(), role)
                    if md.signed.version < previous.signed.version:
                        raise TrustError('Metadata rollback refused')
                    if md.signed.version == previous.signed.version and md.signed_bytes != previous.signed_bytes:
                        raise TrustError('Metadata equivocation refused')
            _verify_bundle(root_raw, metadata)
            state['metadata'] = {'root_version': root.signed.version,
                                 **{r: metadata[r].decode('utf-8') for r in ROLES}}
            state['checked_at'] = now.isoformat()
            state['generation'] += 1
            _write(self.directory, state)
