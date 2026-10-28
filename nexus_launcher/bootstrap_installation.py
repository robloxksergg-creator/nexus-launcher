"""Provision the first signed slot; never adopt/overwrite a legacy installation."""
import hashlib
from pathlib import Path

from nexus_launcher.portable_package import stage_portable_archive, verify_staged_portable
from nexus_launcher.portable_transition import _read
from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.signed_release import canonical, verify_envelope
from nexus_launcher.update_state import update_lock
from nexus_launcher.user_instances import atomic_json


def provision_initial(root, archive, envelope, *, platform, arch, keys=None):
    root = Path(root).absolute()
    with pinned_directory(root, create=True), update_lock(root):
        if checked_path(root, 'active.json').exists():
            return False  # The normal backend revalidates it; never replace it.
        if checked_path(root, 'transition.json').exists():
            raise ValueError('Unresolved existing installation')
        payload = verify_envelope(envelope, keys=keys)
        if payload.get('available') is not True or payload.get('platform') != platform or payload.get('arch') != arch:
            raise ValueError('Initial package not approved for this platform')
        identity = hashlib.sha256(canonical(payload)).hexdigest()
        receipt = checked_path(root, 'initial-provision.json')
        if receipt.exists():
            journal = _read(root, 'initial-provision.json')
            if (journal.get('schema') != 1 or journal.get('phase') != 'PREPARED'
                    or journal.get('identity') != identity):
                raise ValueError('Initial provisioning needs recovery')
            slot = checked_path(root, 'slots/' + journal['slot'])
            verify_staged_portable(slot, keys=keys)
            installed = _read(slot, 'envelope.json')
            if hashlib.sha256(canonical(installed['release'])).hexdigest() != identity:
                raise ValueError('Initial package changed during recovery')
        else:
            if checked_path(root, 'highest-package.json').exists():
                raise ValueError('Do not recreate a missing installed pointer')
            slots = checked_path(root, 'slots')
            with pinned_directory(slots, create=True):
                slot = stage_portable_archive(Path(archive), envelope, slots, keys=keys)
            atomic_json(receipt, {'schema': 1, 'phase': 'PREPARED', 'slot': slot.name, 'identity': identity})
        # Journal binds the exact initial slot across a power loss before pointer.
        atomic_json(checked_path(root, 'highest-package.json'), envelope)
        atomic_json(checked_path(root, 'active.json'), {'slot': slot.name})
        atomic_json(receipt, {'schema': 1, 'phase': 'COMPLETE', 'slot': slot.name, 'identity': identity})
        return True
