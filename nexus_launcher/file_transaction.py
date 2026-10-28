"""Small durable multi-file transaction for pack replacement, caller holds lock."""

import hashlib
import json
from pathlib import Path

from nexus_launcher.resource_limits import ensure_space, read_limited
from nexus_launcher.safe_paths import atomic_copy, checked_path, remove_owned_tree, unlink_file, validate_paths
from nexus_launcher.user_instances import atomic_json
from nexus_launcher.native_transfer import _native

ROOTS = {
    "mods",
    "config",
    "defaultconfigs",
    "kubejs",
    "resourcepacks",
    "shaderpacks",
    "libraries",
    "tacz",
    "options.txt",
}
STATES = {".nexus-launcher/pack.json", ".nexus-launcher/nexus-pack-manifest.json"}
OPERATION = ".nexus-launcher/file-transaction"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checkpoint(phase):
    """Fault-injection seam; production does not alter the transaction."""


def _recover_python(root):
    root = Path(root)
    operation = checked_path(root, OPERATION)
    journal = checked_path(operation, "journal.json")
    if not journal.exists():
        if operation.exists():
            remove_owned_tree(root, OPERATION)
        return
    with journal.open("rb") as stream:
        state = json.loads(read_limited(stream))
    if not isinstance(state, dict) or state.get("phase") not in {"preparing", "prepared", "committed"}:
        raise ValueError("Invalid file transaction journal")
    items = state.get("files")
    if not isinstance(items, list) or not items:
        raise ValueError("Invalid file transaction inventory")
    paths = [item["path"] for item in items]
    validate_paths(root, [p for p in paths if p not in STATES], ROOTS)
    if len({p.casefold() for p in paths}) != len(paths):
        raise ValueError("Duplicate transaction path")
    for item in items:
        checked_path(root, item["path"])
        if type(item.get("existed")) is not bool:
            raise ValueError("Invalid transaction existence flag")
    if state["phase"] == "prepared":
        # Preflight every required backup before restoring any destination.
        for index, item in enumerate(items):
            if item["existed"]:
                backup = checked_path(operation, f"backup/{index}")
                if not backup.is_file() or digest(backup) != item.get("sha256"):
                    raise ValueError("Corrupt transaction backup; installation retained, launch blocked")
        for index, item in enumerate(items):
            target = checked_path(root, item["path"])
            if item["existed"]:
                atomic_copy(checked_path(operation, f"backup/{index}"), target, expected_sha256=item["sha256"])
            else:
                unlink_file(target, missing_ok=True)
    # Rollback is idempotent if killed midway; preparing never changed targets.
    state["phase"] = "committed"
    atomic_json(journal, state)
    checkpoint("cleanup")
    remove_owned_tree(root, OPERATION)


def _apply_python(root, staging, records, removed, state_path, new_state):
    root, staging = Path(root), Path(staging)
    if state_path not in STATES:
        raise ValueError("Invalid state destination")
    _recover_python(root)
    paths = [record["path"] for record in records]
    validate_paths(root, paths, ROOTS)
    validate_paths(staging, paths, ROOTS)
    validate_paths(root, removed, ROOTS)
    validate_paths(root, [*paths, *removed], ROOTS)
    if set(paths) & set(removed):
        raise ValueError("Conflicting replacement and deletion")
    for record in records:
        if digest(checked_path(staging, record["path"])) != record["sha256"]:
            raise ValueError("Staging hash mismatch")
    inventory = [*paths, *removed, state_path]
    items = [{"path": p, "existed": checked_path(root, p).is_file()} for p in inventory]
    ensure_space(
        root,
        sum(checked_path(root, p).stat().st_size for p in inventory if checked_path(root, p).is_file())
        + sum(checked_path(staging, p).stat().st_size for p in paths),
    )
    operation = checked_path(root, OPERATION)
    journal = checked_path(operation, "journal.json")
    state = {"phase": "preparing", "files": items}
    atomic_json(journal, state)
    checkpoint("preparing")
    try:
        for index, item in enumerate(items):
            if item["existed"]:
                source = checked_path(root, item["path"])
                backup = checked_path(operation, f"backup/{index}")
                atomic_copy(source, backup)
                item["sha256"] = digest(backup)
            checkpoint("backup")
        state["phase"] = "prepared"
        atomic_json(journal, state)
        checkpoint("prepared")
        for record in records:
            atomic_copy(
                checked_path(staging, record["path"]),
                checked_path(root, record["path"]),
                expected_sha256=record["sha256"],
            )
            checkpoint("replace")
        for path in removed:
            unlink_file(checked_path(root, path), missing_ok=True)
        atomic_json(checked_path(root, state_path), new_state)
        checkpoint("state")
        state["phase"] = "committed"
        atomic_json(journal, state)
        checkpoint("committed")
    except Exception:
        _recover_python(root)
        raise
    _recover_python(root)


class _TransactionIO:
    """Existing path/handle and journal IO, called synchronously by Rust.

    No process-global transaction state. The caller still owns update_lock.
    """

    def __init__(self, root, staging=None, records=(), removed=(), state_path=None, new_state=None):
        self.root = Path(root)
        self.staging = Path(staging) if staging is not None else None
        self.records = records
        self.removed = removed
        self.state_path = state_path
        self.new_state = new_state

    def operation(self):
        return checked_path(self.root, OPERATION)

    def load_journal(self):
        journal = checked_path(self.operation(), "journal.json")
        if not journal.exists():
            return None
        with journal.open("rb") as stream:
            state = json.loads(read_limited(stream))
        if not isinstance(state, dict) or state.get("phase") not in {"preparing", "prepared", "committed"}:
            raise ValueError("Invalid file transaction journal")
        items = state.get("files")
        if not isinstance(items, list) or not items:
            raise ValueError("Invalid file transaction inventory")
        paths = [item["path"] for item in items]
        validate_paths(self.root, [p for p in paths if p not in STATES], ROOTS)
        if len({p.casefold() for p in paths}) != len(paths):
            raise ValueError("Duplicate transaction path")
        for item in items:
            checked_path(self.root, item["path"])
            if type(item.get("existed")) is not bool:
                raise ValueError("Invalid transaction existence flag")
        return state

    def cleanup_orphan(self):
        if self.operation().exists():
            self.cleanup()

    def cleanup(self):
        remove_owned_tree(self.root, OPERATION)

    def write_journal(self, state):
        atomic_json(checked_path(self.operation(), "journal.json"), state)

    def checkpoint(self, phase):
        checkpoint(phase)

    def check_backup(self, index, item):
        if item["existed"]:
            backup = checked_path(self.operation(), f"backup/{index}")
            if not backup.is_file() or digest(backup) != item.get("sha256"):
                raise ValueError("Corrupt transaction backup; installation retained, launch blocked")

    def restore(self, index, item):
        target = checked_path(self.root, item["path"])
        if item["existed"]:
            atomic_copy(checked_path(self.operation(), f"backup/{index}"), target, expected_sha256=item["sha256"])
        else:
            unlink_file(target, missing_ok=True)

    def validate_state_path(self):
        if self.state_path not in STATES:
            raise ValueError("Invalid state destination")

    def prepare(self):
        paths = [record["path"] for record in self.records]
        validate_paths(self.root, paths, ROOTS)
        validate_paths(self.staging, paths, ROOTS)
        validate_paths(self.root, self.removed, ROOTS)
        validate_paths(self.root, [*paths, *self.removed], ROOTS)
        if set(paths) & set(self.removed):
            raise ValueError("Conflicting replacement and deletion")
        for record in self.records:
            if digest(checked_path(self.staging, record["path"])) != record["sha256"]:
                raise ValueError("Staging hash mismatch")
        inventory = [*paths, *self.removed, self.state_path]
        items = [{"path": p, "existed": checked_path(self.root, p).is_file()} for p in inventory]
        ensure_space(
            self.root,
            sum(checked_path(self.root, p).stat().st_size for p in inventory if checked_path(self.root, p).is_file())
            + sum(checked_path(self.staging, p).stat().st_size for p in paths),
        )
        return {"phase": "preparing", "files": items}

    def backup(self, index, item):
        if item["existed"]:
            source = checked_path(self.root, item["path"])
            backup = checked_path(self.operation(), f"backup/{index}")
            atomic_copy(source, backup)
            item["sha256"] = digest(backup)

    def replace(self, record):
        atomic_copy(checked_path(self.staging, record["path"]), checked_path(self.root, record["path"]),
                    expected_sha256=record["sha256"])

    def delete(self, path):
        unlink_file(checked_path(self.root, path), missing_ok=True)

    def write_state(self):
        atomic_json(checked_path(self.root, self.state_path), self.new_state)


def _native_transactions():
    if _native is None or not hasattr(_native, "TRANSACTION_API_VERSION"):
        return False
    if _native.TRANSACTION_API_VERSION != 1:
        raise ImportError("Incompatible NEXUS native transaction API")
    return True


def recover(root):
    if _native_transactions():
        return _native.transaction_recover(_TransactionIO(root))
    return _recover_python(root)


def apply(root, staging, records, removed, state_path, new_state):
    if _native_transactions():
        return _native.transaction_apply(_TransactionIO(Path(root), Path(staging), records, removed, state_path, new_state))
    return _apply_python(root, staging, records, removed, state_path, new_state)
