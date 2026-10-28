import json

import pytest

from nexus_launcher.portable_bootstrap import HealthChallenge, run_prepared_transition, valid_health_ack
from nexus_launcher.portable_transition import prepare_transition, recover_transition
from tests.test_portable_transition import environment


class Child:
    pid = 1234
    exited = False

    def poll(self):
        return 1 if self.exited else None


class Adapter:
    def __init__(self, mode="healthy"):
        self.mode, self.calls = mode, []
        self.child = Child()

    def wait_parent(self):
        self.calls.append("wait")
        return self.mode != "parent-unknown"

    def launch(self, executable, cwd, challenge):
        self.calls.append("launch")
        assert executable.parent == cwd
        assert executable.read_bytes() == b"fixture-not-executable"
        if self.mode == "spawn-unknown":
            raise OSError("synthetic ambiguous spawn")
        return self.child

    def await_health(self, child, challenge):
        self.calls.append("health")
        if self.mode in {"timeout", "unstoppable"}:
            raise TimeoutError("synthetic timeout")
        nonce = "0" * 64 if self.mode == "bad-ack" else challenge.nonce
        return {"operation_id": challenge.operation_id, "candidate_identity": challenge.candidate_identity,
                "nonce": nonce, "pid": child.pid, "ready": True}

    def stop_and_wait(self, child):
        self.calls.append("stop")
        child.exited = self.mode != "unstoppable"
        return child.exited


@pytest.mark.parametrize("mode,phase", [("healthy", "COMPLETE"), ("bad-ack", "ROLLED_BACK"),
                                       ("timeout", "ROLLED_BACK"), ("unstoppable", "UNKNOWN"),
                                       ("parent-unknown", "UNKNOWN"), ("spawn-unknown", "UNKNOWN")])
def test_health_and_rollback_require_confirmed_process_outcome(tmp_path, mode, phase):
    root, old, new, keys, *_ = environment(tmp_path)
    prepare_transition(root, new.name, old.name, platform="windows", arch="x64", keys=keys)
    adapter = Adapter(mode)
    assert run_prepared_transition(root, adapter=adapter, keys=keys)["phase"] == phase
    assert json.loads((root / "active.json").read_text())["slot"] == (new.name if phase == "COMPLETE" else old.name)
    assert (root / "user-data.json").read_text() == "unchanged synthetic data"
    if mode == "parent-unknown":
        assert adapter.calls == ["wait"]
    if phase == "UNKNOWN":
        with pytest.raises(ValueError):
            run_prepared_transition(root, adapter=adapter, keys=keys)


@pytest.mark.parametrize("change", ["pid", "bool-pid", "operation", "candidate", "nonce", "unicode", "ready", "extra"])
def test_health_ack_cannot_be_forged_or_reused(change):
    challenge = HealthChallenge("operation", "candidate", "a" * 64)
    ack = {"operation_id": "operation", "candidate_identity": "candidate", "nonce": "a" * 64,
           "pid": 1234, "ready": True}
    if change == "pid":
        ack["pid"] = 999
    elif change == "bool-pid":
        ack["pid"] = True
    elif change == "operation":
        ack["operation_id"] = "old-operation"
    elif change == "candidate":
        ack["candidate_identity"] = "another-package"
    elif change == "nonce":
        ack["nonce"] = "b" * 64
    elif change == "unicode":
        ack["nonce"] = "é" * 64
    elif change == "ready":
        ack["ready"] = 1
    else:
        ack["extra"] = "unexpected"
    assert not valid_health_ack(ack, challenge, 1234)


def test_candidate_changed_before_launch_has_zero_dispatch(tmp_path):
    root, old, new, keys, *_ = environment(tmp_path)
    prepare_transition(root, new.name, old.name, platform="windows", arch="x64", keys=keys)
    (new / "files/launcher.exe").write_bytes(b"tampered")
    adapter = Adapter()
    with pytest.raises(ValueError):
        run_prepared_transition(root, adapter=adapter, keys=keys)
    assert adapter.calls == []


def test_restart_after_claim_never_spawns_again(tmp_path):
    root, old, new, keys, *_ = environment(tmp_path)
    prepare_transition(root, new.name, old.name, platform="windows", arch="x64", keys=keys)
    journal = json.loads((root / "transition.json").read_text())
    journal["phase"] = "LAUNCHING"
    (root / "transition.json").write_text(json.dumps(journal))
    assert recover_transition(root)["phase"] == "UNKNOWN"
    adapter = Adapter()
    with pytest.raises(ValueError):
        run_prepared_transition(root, adapter=adapter, keys=keys)
    assert adapter.calls == []
