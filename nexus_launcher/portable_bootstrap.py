"""Trusted bootstrap orchestration with mandatory process/health adapters.

No built-in subprocess launcher: an audited native adapter is still required.
Nonces must travel through a private IPC channel, never argv or public logs.
"""
import secrets
from dataclasses import dataclass
from pathlib import Path

from nexus_launcher.portable_transition import _pointer, _read, _slot, resolve_transition
from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.update_state import update_lock
from nexus_launcher.user_instances import atomic_json


@dataclass(frozen=True, repr=False)
class HealthChallenge:
    operation_id: str
    candidate_identity: str
    nonce: str


def valid_health_ack(ack, challenge, pid):
    if not isinstance(ack, dict) or set(ack) != {"operation_id", "candidate_identity", "nonce", "pid", "ready"}:
        return False
    if type(pid) is not int or pid <= 0 or type(ack["pid"]) is not int or ack["pid"] != pid:
        return False
    if ack["ready"] is not True or not isinstance(ack["nonce"], str):
        return False
    if len(ack["nonce"]) != 64 or any(c not in "0123456789abcdef" for c in ack["nonce"]):
        return False
    return (ack["operation_id"] == challenge.operation_id and ack["candidate_identity"] == challenge.candidate_identity
            and secrets.compare_digest(ack["nonce"], challenge.nonce))


def run_prepared_transition(root: Path, *, adapter, keys=None):
    """Adapter must wait parent, launch verified path, attest IPC and stop child.

    Timeout with an unconfirmed surviving child is UNKNOWN, never safe rollback.
    Adapter authenticity/isolation is a separate gate; mocks do not prove it.
    """
    required = ("wait_parent", "launch", "await_health", "stop_and_wait")
    if adapter is None or any(not callable(getattr(adapter, name, None)) for name in required):
        raise ValueError("A reviewed process/health adapter is required")
    root = Path(root).absolute()
    with update_lock(root):
        journal = _read(root, "transition.json")
        if journal.get("schema") != 1 or journal.get("phase") != "PREPARED":
            raise ValueError("Portable bootstrap attempt already claimed or unresolved")
        if _pointer(root) != journal["previous"]:
            raise ValueError("Active version changed before bootstrap")
        inventory, _, identity, _ = _slot(root, journal["candidate"]["slot"], keys)
        if identity != journal["candidate_identity"]:
            raise ValueError("Candidate identity changed before bootstrap")
        challenge = HealthChallenge(journal["operation_id"], identity, secrets.token_hex(32))
        journal["phase"] = "LAUNCHING"
        atomic_json(checked_path(root, "transition.json"), journal)
    def resolve(result):
        return resolve_transition(root, result, keys=keys, operation_id=challenge.operation_id,
                                  candidate_identity=challenge.candidate_identity)
    child = None
    try:
        if adapter.wait_parent() is not True:
            return resolve("UNKNOWN")
        files = checked_path(root, "slots/" + journal["candidate"]["slot"] + "/files")
        with pinned_directory(files), update_lock(root):
            current = _read(root, "transition.json")
            if current != journal or _pointer(root) != journal["previous"]:
                raise ValueError("Bootstrap authority changed before launch")
            _, _, identity, _ = _slot(root, journal["candidate"]["slot"], keys)
            if identity != challenge.candidate_identity:
                raise ValueError("Candidate changed before launch")
            child = adapter.launch(checked_path(files, inventory.entrypoint), files, challenge)
        ack = adapter.await_health(child, challenge)
        if child.poll() is None and valid_health_ack(ack, challenge, child.pid):
            return resolve("HEALTHY")
    except Exception:
        # Do not leak adapter/transport messages or pretend launch failure is
        # absence of a process; an ambiguous spawn must reconcile as UNKNOWN.
        if child is None:
            return resolve("UNKNOWN")
    try:
        stopped = child.poll() is not None or (adapter.stop_and_wait(child) is True and child.poll() is not None)
    except Exception:
        stopped = False
    return resolve("FAILED" if stopped else "UNKNOWN")
