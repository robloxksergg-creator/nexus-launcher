"""Local inactive-slot transition journal. No EXE launch or updater UI wiring.

Only trusted bootstrapper code may eventually report health. The result supplied
here is a testable contract, not an authenticated Windows process health proof.
"""
import hashlib
import json
import uuid
from pathlib import Path

from nexus_launcher.portable_package import verify_portable_inventory, verify_staged_portable
from nexus_launcher.resource_limits import read_limited
from nexus_launcher.safe_paths import checked_path, relative_parts
from nexus_launcher.signed_release import canonical, verify_envelope, verify_signature
from nexus_launcher.update_state import update_lock
from nexus_launcher.user_instances import atomic_json


def _read(root, name):
    with checked_path(root, name).open("rb") as stream:
        return json.loads(read_limited(stream))


def _slot(root, name, keys, *, installed=False):
    if not isinstance(name, str) or len(relative_parts(name)) != 1 or not name.startswith("portable-stage-"):
        raise ValueError("Invalid owned portable slot")
    path = checked_path(root, "slots/" + name)
    inventory = verify_staged_portable(path, keys=keys, installed=installed)
    envelope = _read(path, "envelope.json")
    payload = (verify_signature if installed else verify_envelope)(envelope, keys=keys)
    from nexus_launcher.portable_package import verify_installed_inventory
    if (verify_installed_inventory if installed else verify_portable_inventory)(envelope, keys=keys) != inventory:
        raise ValueError("Portable inventory changed during verification")
    identity = hashlib.sha256(canonical(payload)).hexdigest()
    return inventory, payload, identity, envelope


def _pointer(root):
    value = _read(root, "active.json")
    if not isinstance(value, dict) or set(value) != {"slot"}:
        raise ValueError("Invalid active portable pointer")
    return value


def prepare_transition(root: Path, candidate: str, expected_active: str, *, platform: str, arch: str, keys=None):
    """Require an already provisioned active slot; never invent initial ownership."""
    root = Path(root).absolute()
    with update_lock(root):
        journal_path = checked_path(root, "transition.json")
        if journal_path.exists() and _read(root, "transition.json").get("phase") not in {"COMPLETE", "ROLLED_BACK"}:
            raise RuntimeError("Unresolved portable transition")
        previous = _pointer(root)
        if previous["slot"] != expected_active or candidate == expected_active:
            raise ValueError("Active slot conflict")
        old, _, old_id, _ = _slot(root, expected_active, keys, installed=True)
        new, payload, new_id, envelope = _slot(root, candidate, keys)
        if payload.get("available") is not True or payload.get("platform") != platform or payload.get("arch") != arch:
            raise ValueError("Portable candidate is not approved for this platform")
        if tuple(map(int, new.version.split("."))) <= tuple(map(int, old.version.split("."))):
            raise ValueError("Portable downgrade/replay refused")
        from nexus_launcher.self_update import version_tuple
        history = checked_path(root, "highest-package.json")
        if history.exists():
            highest = verify_signature(_read(root, "highest-package.json"), keys=keys)
            if highest.get("format") != "nexus-portable-zip-v1":
                raise ValueError("Invalid portable release history")
            proposed, recorded = version_tuple(new.version), version_tuple(highest["version"])
            if proposed < recorded or (proposed == recorded and hashlib.sha256(canonical(highest)).hexdigest() != new_id):
                raise ValueError("Portable rollback/equivocation refused")
        atomic_json(history, envelope)
        journal = {"schema": 1, "phase": "PREPARED", "operation_id": uuid.uuid4().hex,
                   "previous": previous, "candidate": {"slot": candidate},
                   "previous_identity": old_id, "candidate_identity": new_id}
        atomic_json(journal_path, journal)
        return journal


def recover_transition(root: Path):
    """Recovery never launches or blindly repeats a switch; uncertainty is durable."""
    root = Path(root).absolute()
    with update_lock(root):
        journal = _read(root, "transition.json")
        if journal.get("phase") in {"COMPLETE", "ROLLED_BACK", "UNKNOWN"}:
            return journal
        if journal.get("phase") not in {"PREPARED", "LAUNCHING", "COMMITTING", "ROLLING_BACK"}:
            raise ValueError("Unknown portable transition phase")
        if _pointer(root) not in (journal["previous"], journal["candidate"]):
            raise ValueError("Active slot was changed outside this operation")
        journal["phase"] = "UNKNOWN"
        atomic_json(checked_path(root, "transition.json"), journal)
        return journal


def resolve_transition(root: Path, result: str, *, operation_id: str, candidate_identity: str, keys=None):
    """Test/local trusted-caller health verdict; no process start or force-kill.

    Production wiring must independently authenticate health before calling this.
    UNKNOWN blocks new transitions. Failure restores only a reverified old slot.
    """
    if result not in {"HEALTHY", "FAILED", "UNKNOWN"}:
        raise ValueError("Invalid health result")
    root = Path(root).absolute()
    with update_lock(root):
        journal = _read(root, "transition.json")
        if journal.get("schema") != 1 or journal.get("phase") not in {"PREPARED", "LAUNCHING", "UNKNOWN"}:
            raise ValueError("Transition needs recovery or is already resolved")
        if operation_id != journal.get("operation_id") or candidate_identity != journal.get("candidate_identity"):
            raise ValueError("Stale or mismatched portable health result")
        pointer = _pointer(root)
        if pointer not in (journal["previous"], journal["candidate"]):
            raise ValueError("Active slot conflict")
        if result == "UNKNOWN":
            journal["phase"] = "UNKNOWN"
            atomic_json(checked_path(root, "transition.json"), journal)
            return journal
        chosen = journal["candidate"] if result == "HEALTHY" else journal["previous"]
        _, _, identity, _ = _slot(root, chosen["slot"], keys, installed=result == "FAILED")
        expected = journal["candidate_identity"] if result == "HEALTHY" else journal["previous_identity"]
        if identity != expected:
            raise ValueError("Portable slot changed after preparation")
        journal["phase"] = "COMMITTING" if result == "HEALTHY" else "ROLLING_BACK"
        atomic_json(checked_path(root, "transition.json"), journal)
        atomic_json(checked_path(root, "active.json"), chosen)
        journal["phase"] = "COMPLETE" if result == "HEALTHY" else "ROLLED_BACK"
        atomic_json(checked_path(root, "transition.json"), journal)
        return journal
