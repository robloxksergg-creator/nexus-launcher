"""Derive shared portable data only from a signed, selected managed slot."""
import hashlib
import json
from pathlib import Path

from nexus_launcher.portable_package import verify_installed_inventory, verify_portable_inventory
from nexus_launcher.resource_limits import read_limited
from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.signed_release import canonical


def _read(root, name, limit=4*1024*1024):
    with checked_path(root, name).open("rb") as stream:
        return json.loads(read_limited(stream, limit))


def managed_portable_data_root(executable: Path, *, keys=None):
    executable = Path(executable).absolute()
    files = executable.parent
    slot = files.parent
    slots = slot.parent
    if files.name != "files" or not slot.name.startswith("portable-stage-") or slots.name != "slots":
        raise ValueError("Not a managed portable layout")
    root = slots.parent
    with pinned_directory(root), pinned_directory(files):
        checked_path(root, executable.relative_to(root).as_posix())
        if _read(slot, "journal.json", 4096) != {"schema": 1, "phase": "READY"}:
            raise ValueError("Portable slot is not ready")
        active = _read(root, "active.json", 4096)
        if not isinstance(active, dict) or set(active) != {"slot"}:
            raise ValueError("Invalid active selection")
        pending = checked_path(root, "transition.json")
        launching = False
        if pending.exists():
            transition = _read(root, "transition.json", 16384)
            if transition.get("phase") == "LAUNCHING":
                launching = transition.get("candidate") == {"slot": slot.name}
                if not launching or active != transition.get("previous"):
                    raise ValueError("Another portable launch is in progress")
            elif transition.get("phase") not in {"COMPLETE", "ROLLED_BACK"}:
                raise ValueError("Portable transition needs reconciliation")
        if not launching and active != {"slot": slot.name}:
            raise ValueError("Portable slot is not selected")
        envelope = _read(slot, "envelope.json")
        inventory = (verify_portable_inventory if launching else verify_installed_inventory)(envelope, keys=keys)
        if launching and hashlib.sha256(canonical(envelope["release"])).hexdigest() != transition.get("candidate_identity"):
            raise ValueError("Portable launch identity changed")
        if inventory.entrypoint != executable.name:
            raise ValueError("Portable entrypoint mismatch")
        record = next(item for item in inventory.files if item[0] == executable.name)
        if executable.stat().st_size != record[1]:
            raise ValueError("Portable executable size mismatch")
        with executable.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != record[2]:
                raise ValueError("Portable executable integrity mismatch")
        return checked_path(root, "data")
