"""H1: real SQLite/session/controller chain, with no OS/provider effects."""
import ast
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus_launcher.projects import ServerProfile
from nexus_launcher.security import AuthorizationService, PermissionDeniedError
from nexus_launcher.server_controller import LocalServerController, PterodactylServerController
pytest_plugins = ("tests.test_security",)  # Explicitly reviewed temporary-DB/memory-keyring fixtures.


@pytest.fixture
def actor(security, owner):
    uid = security.create_user(owner, "runner", "Runner", "amber planet river lantern", "operator", ["project"])
    return uid, security.authenticate("runner", "amber planet river lantern")


class FakeKeyring:
    def __init__(self):
        self.calls = 0

    def get_password(self, *_args):
        self.calls += 1
        return "fixture-only-token"


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return b"{}"


def panel(security, session):
    effects, keyring = [], FakeKeyring()

    def opener(request, timeout):
        effects.append((request.full_url, request.method))
        return Response()

    server = ServerProfile("nexus_launcher.main", "Fixture", "fixture.invalid", management_type="pterodactyl",
                           panel_url="https://fixture.invalid", panel_server_id="fixture")
    controller = PterodactylServerController(
        server, opener=opener, keyring_module=keyring,
        authorization=lambda permission: security.operation_authorization(session, permission, "project", "nexus_launcher.main"))
    return controller, effects, keyring


@pytest.mark.parametrize("change", ["disable", "demote", "project_scope", "server_scope", "permissions", "expired", "revoked"])
def test_retained_session_denied_before_provider_effect(security, owner, actor, change):
    uid, session = actor
    controller, effects, keyring = panel(security, session)
    assert AuthorizationService.can(session, "servers.start", "project", "nexus_launcher.main")
    if change == "disable":
        security.set_user_active(owner, uid, False)
    elif change == "demote":
        security.update_user_access(owner, uid, "observer", ["project"])
    elif change == "project_scope":
        security.update_user_access(owner, uid, "operator", ["other"])
    elif change == "server_scope":
        security.update_user_access(owner, uid, "operator", ["*"], ["other/main"])
    else:
        with security.connect() as db:
            if change == "permissions":
                db.execute("UPDATE roles SET permissions='[]' WHERE id='operator'")
            elif change == "expired":
                db.execute("UPDATE sessions SET inactivity_expires_at=0 WHERE user_id=?", (uid,))
            else:
                db.execute("UPDATE sessions SET revoked_at='fixture' WHERE user_id=?", (uid,))
    assert not AuthorizationService.can(session, "servers.start", "project", "nexus_launcher.main")
    assert not controller.start()
    assert not effects and keyring.calls == 0
    if change == "disable":
        assert not security.validate_session(session)


def test_active_user_still_dispatches_and_ui_cache_cannot_escalate(security, actor):
    _uid, session = actor
    controller, effects, keyring = panel(security, session)
    assert controller.start() and controller.send_command("list")
    assert len(effects) == 2 and keyring.calls == 2
    forged = replace(session, permissions=frozenset({"*"}), allowed_project_ids=frozenset({"*"}),
                     allowed_server_ids=frozenset({"*"}), role_id="owner", mfa_verified=True)
    assert not AuthorizationService.can(forged, "users.manage_owner")
    assert not AuthorizationService.can(forged, "servers.start", "other", "nexus_launcher.main")


@pytest.mark.parametrize("failure", ["unavailable", "malformed_scope", "missing_role", "corrupt_file", "missing_file"])
def test_authority_failure_denies_without_adapter(security, actor, monkeypatch, failure):
    uid, session = actor
    controller, effects, keyring = panel(security, session)
    if failure == "unavailable":
        def unavailable():
            raise sqlite3.OperationalError("fixture unavailable")
        monkeypatch.setattr(security, "connect", unavailable)
    elif failure in {"corrupt_file", "missing_file"}:
        # Only a different disposable path is damaged; never touch real user DB.
        security.path = security.path.parent / "bad-fixture.db"
        if failure == "corrupt_file":
            security.path.write_bytes(b"not sqlite")
    else:
        with security.connect() as db:
            if failure == "malformed_scope":
                db.execute("UPDATE users SET allowed_projects=? WHERE id=?", (json.dumps({"*": True}), uid))
            else:
                db.execute("UPDATE users SET role_id='observer' WHERE id=?", (uid,))
                db.execute("DELETE FROM roles WHERE id='operator'")
                # Broken role binding simulated after disabling fixture FK enforcement.
                db.execute("PRAGMA foreign_keys=OFF")
        if failure == "missing_role":
            with sqlite3.connect(security.path) as db:
                db.execute("UPDATE users SET role_id='missing-fixture' WHERE id=?", (uid,))
    assert not security.validate_session(session)
    assert not AuthorizationService.can(session, "servers.start", "project", "nexus_launcher.main")
    assert not controller.start() and not effects and keyring.calls == 0


class FakeProcess:
    pid = 123
    stdout = None

    def __init__(self):
        self.writes = []
        self.stdin = self

    def poll(self):
        return None

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        pass

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.writes.append("TERMINATE")

    def kill(self):
        self.writes.append("KILL")


class QueuedThread:
    pending = []

    def __init__(self, target, args=(), daemon=False):
        self.target, self.args = target, args

    def start(self):
        self.pending.append((self.target, self.args))


def local(security, session, tmp_path, monkeypatch):
    effects = []
    server = ServerProfile("nexus_launcher.main", "Fixture", "localhost", working_directory=str(tmp_path))
    controller = LocalServerController(server,
        process_factory=lambda *args, **kwargs: effects.append("SPAWN") or FakeProcess(),
        authorization=lambda permission: security.operation_authorization(session, permission, "project", "nexus_launcher.main"))
    monkeypatch.setattr(controller, "build_command", lambda: ["never-executed-fixture"])
    QueuedThread.pending = []
    monkeypatch.setattr("nexus_launcher.server_controller.threading.Thread", QueuedThread)
    return controller, effects


def test_revoke_between_ui_check_and_local_spawn(security, owner, actor, tmp_path, monkeypatch):
    uid, session = actor
    controller, effects = local(security, session, tmp_path, monkeypatch)
    assert AuthorizationService.can(session, "servers.start", "project", "nexus_launcher.main")
    def build_then_revoke():
        security.set_user_active(owner, uid, False)
        return ["never-executed-fixture"]
    monkeypatch.setattr(controller, "build_command", build_then_revoke)
    assert not controller.start() and not effects


@pytest.mark.parametrize("operation", ["restart", "stop"])
def test_queued_worker_rechecks_authority(security, owner, actor, tmp_path, monkeypatch, operation):
    uid, session = actor
    controller, effects = local(security, session, tmp_path, monkeypatch)
    process = FakeProcess()
    if operation == "stop":
        controller.process = process
    getattr(controller, operation)()
    assert len(QueuedThread.pending) == 1
    security.set_user_active(owner, uid, False)
    target, args = QueuedThread.pending.pop(0)
    target(*args)
    assert not effects and not process.writes


def test_valid_local_spawn_and_command_then_revoke(security, owner, actor, tmp_path, monkeypatch):
    uid, session = actor
    controller, effects = local(security, session, tmp_path, monkeypatch)
    assert controller.start() and effects == ["SPAWN"]
    assert controller.send_command("list")
    security.set_user_active(owner, uid, False)
    assert not controller.send_command("list")
    assert controller.process.writes == ["list\n"]


def test_controller_without_authority_fails_closed(tmp_path):
    controller = LocalServerController(ServerProfile("nexus_launcher.main", "Fixture", "localhost", working_directory=str(tmp_path)),
                                       process_factory=lambda *args, **kwargs: pytest.fail("unguarded effect"))
    controller.build_command = lambda: ["fixture"]
    assert not controller.start()


def test_actual_admin_factory_binds_actor_and_scope_without_gui(security, owner, actor):
    # Execute only the real factory AST, not admin module/global APPDATA/GUI imports.
    admin = Path(__file__).resolve().parents[1] / "nexus_launcher" / "admin.py"
    tree = ast.parse(admin.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ControlCenter")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_controller")
    method.returns = None
    for arg in method.args.args:
        arg.annotation = None
    namespace = {"PterodactylServerController": PterodactylServerController,
                 "LocalServerController": LocalServerController}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "admin-factory-extracted", "exec"), namespace)
    uid, session = actor
    panel = SimpleNamespace(controllers={}, security=security, session=session,
                            events=SimpleNamespace(put=lambda value: None),
                            _key=lambda project, server: f"{project.id}/{server.id}")
    project = SimpleNamespace(id="project")
    server = ServerProfile("nexus_launcher.main", "Fixture", "localhost", management_type="pterodactyl",
                           panel_url="https://fixture.invalid", panel_server_id="fixture")
    controller = namespace["_controller"](panel, project, server)
    effects, keyring = [], FakeKeyring()
    controller._opener = lambda request, timeout: effects.append("PROVIDER") or Response()
    controller._keyring = keyring
    assert controller.start() and effects == ["PROVIDER"]
    effects.clear()
    keyring.calls = 0
    panel.session = owner
    security.set_user_active(owner, uid, False)
    assert not controller.start() and not effects and keyring.calls == 0


def test_committed_revocation_wins_dispatch_fence(security, owner, actor):
    uid, session = actor
    security.set_user_active(owner, uid, False)
    with pytest.raises(PermissionDeniedError):
        with security.operation_authorization(session, "servers.start", "project", "nexus_launcher.main"):
            pytest.fail("effect must not begin")


def test_dispatch_fence_blocks_concurrent_database_writer(security, actor):
    uid, session = actor
    # A competing writer cannot commit revocation during the fenced dispatch.
    # This proves local ordering, not cancellation of a request already sent.
    with security.operation_authorization(session, "servers.start", "project", "nexus_launcher.main"):
        with sqlite3.connect(security.path, timeout=0) as competitor:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competitor.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
    with security.connect() as db:
        db.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
    assert not AuthorizationService.can(session, "servers.start", "project", "nexus_launcher.main")


def test_delayed_restart_cannot_use_retained_start_right(security, owner, actor, tmp_path, monkeypatch):
    uid, session = actor
    controller, effects = local(security, session, tmp_path, monkeypatch)
    controller.restart()
    with security.connect() as db:
        db.execute("UPDATE roles SET permissions=? WHERE id='operator'", (json.dumps(["servers.start"]),))
    assert AuthorizationService.can(session, "servers.start", "project", "nexus_launcher.main")
    target, args = QueuedThread.pending.pop(0)
    target(*args)
    assert not effects


def test_stop_timeout_does_not_escalate_after_revoke(security, owner, actor, tmp_path, monkeypatch):
    import subprocess
    uid, session = actor
    controller, _effects = local(security, session, tmp_path, monkeypatch)
    process = FakeProcess()
    def timeout_then_revoke(timeout=None):
        security.set_user_active(owner, uid, False)
        raise subprocess.TimeoutExpired("fixture", timeout)
    process.wait = timeout_then_revoke
    controller._graceful_stop(process, 1)
    assert process.writes == ["stop\n"]  # Earlier authorized effect remains; no new terminate/kill.


def test_nonfinite_or_contradictory_session_data_denied(security, actor):
    uid, session = actor
    with security.connect() as db:
        db.execute("UPDATE sessions SET absolute_expires_at=? WHERE user_id=?", (float("inf"), uid))
    assert not security.validate_session(session)
    controller, effects, keyring = panel(security, session)
    assert not controller.start() and not effects and keyring.calls == 0
