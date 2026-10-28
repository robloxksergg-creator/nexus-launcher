import json
from dataclasses import replace

import pyotp
import pytest
from nexus_launcher.mfa_service import MfaService
from nexus_launcher.security import (
    AuthenticationError,
    AuthorizationService,
    MfaEnrollmentRequiredError,
    MfaRequiredError,
    PermissionDeniedError,
    SQLiteSecurityStore,
)


class MemorySecretStore:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def security(tmp_path):
    store = SQLiteSecurityStore(tmp_path / "security.db")
    store.mfa = MfaService(MemorySecretStore())
    store.create_owner("ikram", "Ikram", "coffee river satellite winter bridge")
    return store


@pytest.fixture
def owner(security):
    pending = security.authenticate_password("ikram", "coffee river satellite winter bridge")
    setup = security.begin_mfa_setup(pending)
    session, _codes = security.confirm_mfa_setup(pending, pyotp.TOTP(setup.secret).now())
    return session


def test_owner_password_uses_argon2id_and_owner_can_everything(security, owner):
    with security.connect() as db:
        stored = db.execute("SELECT password_hash FROM users WHERE username='ikram'").fetchone()[0]
    assert stored.startswith("$argon2id$")
    assert "coffee river" not in stored
    assert AuthorizationService.can(owner, "nexus_launcher.security.manage", "any-project", "any-server")


def test_technical_admin_permissions_and_resource_scope(security, owner):
    security.create_user(
        owner,
        "starfox",
        "StarFox",
        "temporary secure phrase",
        "technical-admin",
        ["nexusmc"],
    )
    pending = security.authenticate_password("starfox", "temporary secure phrase")
    pending = security.change_temporary_password(pending, "star fox orbital river station")
    setup = security.begin_mfa_setup(pending)
    technical, _codes = security.confirm_mfa_setup(pending, pyotp.TOTP(setup.secret).now())
    assert AuthorizationService.can(technical, "servers.start", "nexusmc", "nexus_launcher.main")
    assert AuthorizationService.can(technical, "servers.restart", "nexusmc", "nexus_launcher.main")
    assert AuthorizationService.can(technical, "servers.command", "nexusmc", "nexus_launcher.main")
    assert not AuthorizationService.can(technical, "users.create")
    assert not AuthorizationService.can(technical, "servers.delete", "nexusmc", "nexus_launcher.main")
    assert not AuthorizationService.can(technical, "servers.restart", "northstar", "nexus_launcher.main")


def test_observer_is_read_only_and_backend_rejects_bypass(security, owner):
    security.create_user(owner, "viewer", "Viewer", "observer secure phrase", "observer", ["nexusmc"])
    observer = security.authenticate("viewer", "observer secure phrase")
    assert AuthorizationService.can(observer, "servers.view", "nexusmc", "nexus_launcher.main")
    assert AuthorizationService.can(observer, "logs.view", "nexusmc", "nexus_launcher.main")
    assert not AuthorizationService.can(observer, "servers.start", "nexusmc", "nexus_launcher.main")
    with pytest.raises(PermissionDeniedError):
        AuthorizationService.require(observer, "servers.restart", "nexusmc", "nexus_launcher.main")


def test_project_scopes_separate_administrators(security, owner):
    security.create_user(owner, "admin-a", "Admin A", "admin a secure phrase", "operator", ["nexusmc"])
    security.create_user(owner, "admin-b", "Admin B", "admin b secure phrase", "operator", ["northstar"])
    admin_a = security.authenticate("admin-a", "admin a secure phrase")
    admin_b = security.authenticate("admin-b", "admin b secure phrase")
    assert AuthorizationService.can(admin_a, "servers.view", "nexusmc", "nexus_launcher.main")
    assert not AuthorizationService.can(admin_a, "servers.view", "northstar", "nexus_launcher.main")
    assert AuthorizationService.can(admin_b, "servers.view", "northstar", "nexus_launcher.main")
    assert not AuthorizationService.can(admin_b, "servers.view", "nexusmc", "nexus_launcher.main")
    assert AuthorizationService.can(owner, "servers.view", "nexusmc", "nexus_launcher.main")
    assert AuthorizationService.can(owner, "servers.view", "northstar", "nexus_launcher.main")


def test_last_owner_cannot_be_disabled(security, owner):
    with pytest.raises(PermissionDeniedError):
        security.set_user_active(owner, owner.user_id, False)
    with pytest.raises(PermissionDeniedError):
        security.update_user_access(owner, owner.user_id, "administrator", ["*"])


def test_owner_can_reassign_user_role_and_project_scope(security, owner):
    user_id = security.create_user(
        owner, "scoped", "Scoped Admin", "river lantern orbit canvas", "observer", ["nexusmc"]
    )
    security.update_user_access(owner, user_id, "operator", ["northstar"])
    session = security.authenticate("scoped", "river lantern orbit canvas")
    assert session.role_id == "operator"
    assert AuthorizationService.can(session, "servers.restart", "northstar", "nexus_launcher.main")
    assert not AuthorizationService.can(session, "servers.view", "nexusmc", "nexus_launcher.main")


def test_failed_login_is_rate_limited_and_audited(security):
    for _index in range(4):
        with pytest.raises(AuthenticationError):
            security.authenticate("ikram", "wrong password")
    with pytest.raises(AuthenticationError) as fifth:
        security.authenticate("ikram", "wrong password")
    assert fifth.value.retry_after >= 5
    audit = security.list_audit()
    assert sum(item["action"] == "auth.login_failed" for item in audit) == 5


def test_audit_redacts_sensitive_command(security, owner):
    security.audit(owner, "server.command", "server", "nexusmc/main", True, {"command": "login secret-token"})
    entry = security.list_audit()[0]
    assert entry["metadata"]["command"] == "[REDACTED]"


def test_projects_are_not_stored_in_security_database(security):
    with security.connect() as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "nexus_launcher.projects" not in tables
    assert json.dumps(security.list_roles())


@pytest.mark.parametrize("password", ["123456", "password", "qwerty", "nexus123", "ikram123456"])
def test_weak_passwords_are_rejected(security, password):
    assessment = security.assess_password(password, "ikram")
    assert not assessment.accepted
    with pytest.raises(ValueError):
        security.validate_password(password, "ikram")


def test_long_passphrase_and_unicode_are_supported(security):
    assert security.assess_password("кофе река спутник зима мост уникальный", "ikram").accepted
    assert security.assess_password("unique orbital phrase " * 5, "ikram").accepted


def test_privileged_password_does_not_create_session_without_mfa(security):
    with pytest.raises(MfaEnrollmentRequiredError):
        security.authenticate("ikram", "coffee river satellite winter bridge")
    assert security.list_sessions(1) == []


def test_mfa_correct_wrong_replay_nearby_and_expired_codes(security, monkeypatch):
    base = 2_000_000_010.0
    monkeypatch.setattr("nexus_launcher.mfa_service.time.time", lambda: base)
    pending = security.authenticate_password("ikram", "coffee river satellite winter bridge")
    setup = security.begin_mfa_setup(pending)
    enrollment_code = pyotp.TOTP(setup.secret).at(base)
    session, _codes = security.confirm_mfa_setup(pending, enrollment_code)
    assert session.mfa_verified
    with pytest.raises(MfaRequiredError):
        security.authenticate("ikram", "coffee river satellite winter bridge")
    pending = security.authenticate_password("ikram", "coffee river satellite winter bridge")
    with pytest.raises(AuthenticationError):
        security.complete_mfa_login(pending, "000000")
    with pytest.raises(AuthenticationError):
        security.complete_mfa_login(pending, enrollment_code)
    nearby_code = pyotp.TOTP(setup.secret).at(base + 30)
    nearby_session = security.complete_mfa_login(pending, nearby_code)
    assert nearby_session.mfa_verified
    pending = security.authenticate_password("ikram", "coffee river satellite winter bridge")
    expired_code = pyotp.TOTP(setup.secret).at(base - 90)
    with pytest.raises(AuthenticationError):
        security.complete_mfa_login(pending, expired_code)


def test_recovery_code_is_single_use(security, monkeypatch):
    base = 2_000_000_010.0
    monkeypatch.setattr("nexus_launcher.mfa_service.time.time", lambda: base)
    pending = security.authenticate_password("ikram", "coffee river satellite winter bridge")
    setup = security.begin_mfa_setup(pending)
    _session, codes = security.confirm_mfa_setup(pending, pyotp.TOTP(setup.secret).at(base))
    pending = security.authenticate_password("ikram", "coffee river satellite winter bridge")
    assert security.complete_mfa_login(pending, codes[0], recovery=True).mfa_verified
    pending = security.authenticate_password("ikram", "coffee river satellite winter bridge")
    with pytest.raises(AuthenticationError):
        security.complete_mfa_login(pending, codes[0], recovery=True)


def test_mfa_bypass_and_expired_session_are_rejected(security, owner):
    unverified = replace(owner, mfa_verified=False)
    assert not AuthorizationService.can(unverified, "servers.start", "nexusmc", "nexus_launcher.main")
    with security.connect() as db:
        db.execute("UPDATE sessions SET inactivity_expires_at=0 WHERE user_id=?", (owner.user_id,))
    assert not security.validate_session(owner)


def test_disable_mfa_requires_fresh_reauthentication(security, owner):
    stale = replace(owner, strong_auth_at=0)
    with pytest.raises(PermissionDeniedError):
        security.disable_mfa(stale)
