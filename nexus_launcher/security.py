# ruff: noqa: E501 -- SQL statements are kept intact for schema readability.

from __future__ import annotations

import hashlib
import json
import math
import platform
import secrets
import sqlite3
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from nexus_launcher.mfa_service import MFA_REQUIRED_ROLES, MfaService, PendingMfaSetup
from nexus_launcher.password_security import PasswordAssessment, PasswordService

PERMISSIONS = (
    "nexus_launcher.projects.view",
    "nexus_launcher.projects.create",
    "nexus_launcher.projects.edit",
    "nexus_launcher.projects.delete",
    "servers.view",
    "servers.create",
    "servers.edit",
    "servers.delete",
    "servers.start",
    "servers.stop",
    "servers.restart",
    "servers.command",
    "console.view",
    "logs.view",
    "metrics.view",
    "players.view",
    "players.kick",
    "players.ban",
    "players.unban",
    "players.whitelist",
    "backups.view",
    "backups.create",
    "backups.restore",
    "backups.delete",
    "builds.view",
    "builds.publish",
    "launcher.view",
    "launcher.manage",
    "users.view",
    "users.create",
    "users.edit",
    "users.disable",
    "users.manage_owner",
    "users.security.reset_mfa",
    "sessions.revoke",
    "roles.view",
    "roles.manage",
    "audit.view",
    "nexus_launcher.security.manage",
)

DEFAULT_ROLES = {
    "owner": ("Owner", {"*"}),
    "administrator": (
        "Administrator",
        set(PERMISSIONS) - {"users.manage_owner", "nexus_launcher.security.manage"},
    ),
    "technical-admin": (
        "Technical Admin",
        {
            "nexus_launcher.projects.view",
            "servers.view",
            "servers.edit",
            "servers.start",
            "servers.stop",
            "servers.restart",
            "servers.command",
            "console.view",
            "logs.view",
            "metrics.view",
            "players.view",
            "backups.view",
            "backups.create",
            "launcher.view",
        },
    ),
    "operator": (
        "Operator",
        {
            "nexus_launcher.projects.view",
            "servers.view",
            "servers.start",
            "servers.stop",
            "servers.restart",
            "servers.command",
            "console.view",
            "logs.view",
            "metrics.view",
            "players.view",
            "launcher.view",
        },
    ),
    "observer": (
        "Observer",
        {
            "nexus_launcher.projects.view",
            "servers.view",
            "console.view",
            "logs.view",
            "metrics.view",
            "players.view",
            "launcher.view",
        },
    ),
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PermissionDeniedError(PermissionError):
    pass


class AuthenticationError(ValueError):
    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class MfaRequiredError(AuthenticationError):
    pass


class MfaEnrollmentRequiredError(AuthenticationError):
    pass


@dataclass(frozen=True)
class PendingAuthentication:
    user_id: int
    username: str
    display_name: str
    role_id: str
    role_name: str
    permissions: frozenset[str]
    allowed_project_ids: frozenset[str]
    allowed_server_ids: frozenset[str]
    must_change_password: bool
    mfa_enabled: bool
    mfa_required: bool
    created_at: float


@dataclass(frozen=True)
class Session:
    id: str
    user_id: int
    username: str
    display_name: str
    role_id: str
    role_name: str
    permissions: frozenset[str]
    allowed_project_ids: frozenset[str]
    allowed_server_ids: frozenset[str]
    created_at: str
    must_change_password: bool = False
    mfa_verified: bool = False
    last_activity_at: float = 0.0
    expires_at: float = 0.0
    absolute_expires_at: float = 0.0
    strong_auth_at: float = 0.0
    authority: SQLiteSecurityStore | None = field(default=None, repr=False, compare=False)


class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, username: str, password: str) -> Session: ...


class UserRepository(ABC):
    @abstractmethod
    def list_users(self) -> list[dict]: ...


class RoleRepository(ABC):
    @abstractmethod
    def list_roles(self) -> list[dict]: ...


class AuditRepository(ABC):
    @abstractmethod
    def list_audit(self, limit: int = 500) -> list[dict]: ...


class SecretStore(ABC):
    """OS-backed secret storage boundary for future remote credentials."""

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> str | None: ...


class AuthorizationService:
    @staticmethod
    def can(session: Session, permission: str, project_id: str | None = None, server_id: str | None = None) -> bool:
        if session.authority is None:
            return False
        try:
            with session.authority.connect() as db:
                current = session.authority._live_session(db, session)
            return AuthorizationService._can_snapshot(current, permission, project_id, server_id)
        except (sqlite3.Error, ValueError, TypeError, KeyError, PermissionDeniedError):
            return False

    @staticmethod
    def _can_snapshot(session: Session, permission: str, project_id=None, server_id=None) -> bool:
        if session.role_id in MFA_REQUIRED_ROLES and not session.mfa_verified:
            return False
        if "*" not in session.permissions and permission not in session.permissions:
            return False
        if project_id and "*" not in session.allowed_project_ids and project_id not in session.allowed_project_ids:
            return False
        if server_id:
            full_id = f"{project_id}/{server_id}" if project_id else server_id
            project_grants_access = project_id and project_id in session.allowed_project_ids
            if (
                "*" not in session.allowed_server_ids
                and full_id not in session.allowed_server_ids
                and not project_grants_access
            ):
                return False
        return True

    @staticmethod
    def has_fresh_reauthentication(session: Session, maximum_age: int = 300) -> bool:
        return session.strong_auth_at > 0 and time.time() - session.strong_auth_at <= maximum_age

    @classmethod
    def require(
        cls, session: Session, permission: str, project_id: str | None = None, server_id: str | None = None
    ) -> None:
        if not cls.can(session, permission, project_id, server_id):
            raise PermissionDeniedError(f"Недостаточно прав: {permission}")


class SQLiteSecurityStore(AuthProvider, UserRepository, RoleRepository, AuditRepository):
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.passwords = PasswordHasher()
        self.password_policy = PasswordService()
        self.mfa = MfaService()
        self.failures: dict[str, tuple[int, float]] = {}
        self.mfa_failures: dict[int, tuple[int, float]] = {}
        self._initialize()

    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    permissions TEXT NOT NULL,
                    builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role_id TEXT NOT NULL REFERENCES roles(id),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    allowed_projects TEXT NOT NULL DEFAULT '[]',
                    allowed_servers TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT,
                    password_changed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id INTEGER,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    success INTEGER NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS audit_time_idx ON audit(timestamp DESC);
                CREATE TABLE IF NOT EXISTS authenticators (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    type TEXT NOT NULL,
                    secret_reference TEXT NOT NULL,
                    enabled_at TEXT NOT NULL,
                    last_used_step INTEGER
                );
                CREATE TABLE IF NOT EXISTS recovery_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    code_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    inactivity_expires_at REAL NOT NULL,
                    absolute_expires_at REAL NOT NULL,
                    mfa_verified INTEGER NOT NULL,
                    strong_auth_at REAL NOT NULL,
                    device TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS password_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "password_changed_at" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
            timestamp = now_iso()
            for role_id, (name, permissions) in DEFAULT_ROLES.items():
                db.execute(
                    "INSERT INTO roles(id,name,permissions,builtin,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name, permissions=excluded.permissions, updated_at=excluded.updated_at",
                    (role_id, name, json.dumps(sorted(permissions)), 1, timestamp, timestamp),
                )

    def has_users(self) -> bool:
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    def assess_password(self, password: str, username: str = "") -> PasswordAssessment:
        return self.password_policy.assess(password, username, ("NEXUS Control Panel",))

    def validate_password(self, password: str, username: str = "") -> None:
        self.password_policy.validate(password, username, ("NEXUS Control Panel",))

    def create_owner(self, username: str, display_name: str, password: str) -> int:
        if self.has_users():
            raise PermissionDeniedError("Первичная настройка уже выполнена")
        self.validate_password(password, username)
        timestamp = now_iso()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO users(username,display_name,password_hash,role_id,is_active,allowed_projects,allowed_servers,created_at,updated_at) "
                "VALUES(?,?,?,?,1,'[\"*\"]','[\"*\"]',?,?)",
                (username.strip(), display_name.strip(), self.passwords.hash(password), "owner", timestamp, timestamp),
            )
            user_id = int(cursor.lastrowid)
        self.audit(None, "nexus_launcher.security.owner_created", "user", str(user_id), True, {"username": username})
        return user_id

    def _pending_from_row(self, row: sqlite3.Row) -> PendingAuthentication:
        return PendingAuthentication(
            user_id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"]),
            role_id=str(row["role_id"]),
            role_name=str(row["role_name"]),
            permissions=frozenset(json.loads(row["permissions"])),
            allowed_project_ids=frozenset(json.loads(row["allowed_projects"])),
            allowed_server_ids=frozenset(json.loads(row["allowed_servers"])),
            must_change_password=bool(row["must_change_password"]),
            mfa_enabled=bool(row["mfa_enabled"]),
            mfa_required=str(row["role_id"]) in MFA_REQUIRED_ROLES,
            created_at=time.time(),
        )

    def authenticate_password(self, username: str, password: str) -> PendingAuthentication:
        normalized = username.strip().lower()
        failures, retry_at = self.failures.get(normalized, (0, 0.0))
        retry_after = max(0, int(retry_at - time.monotonic() + 0.999))
        if retry_after:
            raise AuthenticationError(f"Слишком много попыток. Повторите через {retry_after} сек.", retry_after)
        with self.connect() as db:
            row = db.execute(
                "SELECT users.*, roles.name role_name, roles.permissions, "
                "EXISTS(SELECT 1 FROM authenticators WHERE authenticators.user_id=users.id) mfa_enabled "
                "FROM users JOIN roles ON roles.id=users.role_id "
                "WHERE users.username=?",
                (username.strip(),),
            ).fetchone()
        valid = False
        if row and row["is_active"]:
            try:
                valid = self.passwords.verify(str(row["password_hash"]), password)
            except VerifyMismatchError:
                valid = False
        if not valid:
            failures += 1
            delay = 0 if failures < 5 else 5 if failures == 5 else 15 if failures == 6 else 30 if failures == 7 else 60
            self.failures[normalized] = (failures, time.monotonic() + delay)
            self.audit(None, "auth.login_failed", "user", normalized, False, {})
            raise AuthenticationError("Неверное имя пользователя или пароль", delay)
        self.failures.pop(normalized, None)
        return self._pending_from_row(row)

    def authenticate(self, username: str, password: str) -> Session:
        pending = self.authenticate_password(username, password)
        if pending.mfa_required and not pending.mfa_enabled:
            raise MfaEnrollmentRequiredError("Для этой роли требуется настройка 2FA")
        if pending.mfa_enabled:
            raise MfaRequiredError("Требуется код двухфакторной аутентификации")
        return self._create_session(pending, False)

    def complete_password_login(self, pending: PendingAuthentication) -> Session:
        if pending.mfa_enabled:
            raise MfaRequiredError("Требуется код двухфакторной аутентификации")
        if pending.mfa_required:
            raise MfaEnrollmentRequiredError("Для этой роли требуется настройка 2FA")
        return self._create_session(pending, False)

    def _create_session(self, pending: PendingAuthentication, mfa_verified: bool) -> Session:
        token = secrets.token_urlsafe(32)
        now = time.time()
        inactivity = now + 45 * 60
        absolute = now + 12 * 60 * 60
        session = Session(
            id=token,
            user_id=pending.user_id,
            username=pending.username,
            display_name=pending.display_name,
            role_id=pending.role_id,
            role_name=pending.role_name,
            permissions=pending.permissions,
            allowed_project_ids=pending.allowed_project_ids,
            allowed_server_ids=pending.allowed_server_ids,
            created_at=now_iso(),
            must_change_password=pending.must_change_password,
            mfa_verified=mfa_verified,
            last_activity_at=now,
            expires_at=inactivity,
            absolute_expires_at=absolute,
            strong_auth_at=now,
            authority=self,
        )
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        timestamp = now_iso()
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions(token_hash,user_id,created_at,last_seen_at,inactivity_expires_at,absolute_expires_at,"
                "mfa_verified,strong_auth_at,device) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    token_hash,
                    pending.user_id,
                    timestamp,
                    timestamp,
                    inactivity,
                    absolute,
                    int(mfa_verified),
                    now,
                    f"{platform.system()} {platform.release()}",
                ),
            )
            db.execute(
                "UPDATE users SET last_login_at=?,updated_at=? WHERE id=?", (timestamp, timestamp, pending.user_id)
            )
        self.audit(session, "auth.login.success", "user", str(session.user_id), True, {"mfa": mfa_verified})
        return session

    def begin_mfa_setup(self, pending_or_session: PendingAuthentication | Session) -> PendingMfaSetup:
        return self.mfa.begin_setup(pending_or_session.user_id, pending_or_session.username)

    def confirm_mfa_setup(self, pending: PendingAuthentication, code: str) -> tuple[Session, list[str]]:
        reference, step = self.mfa.confirm_setup(pending.user_id, code)
        codes = self.mfa.generate_recovery_codes()
        timestamp = now_iso()
        with self.connect() as db:
            db.execute(
                "INSERT INTO authenticators(user_id,type,secret_reference,enabled_at,last_used_step) VALUES(?,?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET secret_reference=excluded.secret_reference,enabled_at=excluded.enabled_at,"
                "last_used_step=excluded.last_used_step",
                (pending.user_id, "totp", reference, timestamp, step),
            )
            db.execute("DELETE FROM recovery_codes WHERE user_id=?", (pending.user_id,))
            db.executemany(
                "INSERT INTO recovery_codes(user_id,code_hash,created_at) VALUES(?,?,?)",
                [(pending.user_id, self.mfa.recovery_hash(code_value), timestamp) for code_value in codes],
            )
        session = self._create_session(pending, True)
        self.audit(session, "auth.mfa.enabled", "user", str(pending.user_id), True, {})
        return session, codes

    def confirm_mfa_setup_current(self, session: Session, code: str) -> tuple[Session, list[str]]:
        reference, step = self.mfa.confirm_setup(session.user_id, code)
        codes = self.mfa.generate_recovery_codes()
        timestamp = now_iso()
        with self.connect() as db:
            db.execute(
                "INSERT INTO authenticators(user_id,type,secret_reference,enabled_at,last_used_step) VALUES(?,?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET secret_reference=excluded.secret_reference,enabled_at=excluded.enabled_at,"
                "last_used_step=excluded.last_used_step",
                (session.user_id, "totp", reference, timestamp, step),
            )
            db.execute("DELETE FROM recovery_codes WHERE user_id=?", (session.user_id,))
            db.executemany(
                "INSERT INTO recovery_codes(user_id,code_hash,created_at) VALUES(?,?,?)",
                [(session.user_id, self.mfa.recovery_hash(value), timestamp) for value in codes],
            )
        refreshed = Session(**(session.__dict__ | {"mfa_verified": True, "strong_auth_at": time.time()}))
        self.audit(refreshed, "auth.mfa.enabled", "user", str(session.user_id), True, {})
        return refreshed, codes

    def mfa_status(self, user_id: int) -> dict:
        with self.connect() as db:
            authenticator = db.execute(
                "SELECT type,enabled_at FROM authenticators WHERE user_id=?", (user_id,)
            ).fetchone()
        return {
            "enabled": bool(authenticator),
            "type": authenticator["type"] if authenticator else None,
            "enabled_at": authenticator["enabled_at"] if authenticator else None,
            "recovery_codes": self.recovery_codes_remaining(user_id),
        }

    def complete_mfa_login(self, pending: PendingAuthentication, code: str, recovery: bool = False) -> Session:
        if not pending.mfa_enabled:
            raise MfaEnrollmentRequiredError("2FA не настроена")
        failures, retry_at = self.mfa_failures.get(pending.user_id, (0, 0.0))
        retry_after = max(0, int(retry_at - time.monotonic() + 0.999))
        if retry_after:
            raise AuthenticationError(f"Слишком много попыток. Повторите через {retry_after} сек.", retry_after)
        try:
            if recovery:
                self._use_recovery_code(pending.user_id, code)
                action = "auth.recovery_code.used"
            else:
                with self.connect() as db:
                    authenticator = db.execute(
                        "SELECT * FROM authenticators WHERE user_id=?", (pending.user_id,)
                    ).fetchone()
                step = self.mfa.verify_reference(
                    authenticator["secret_reference"], code, authenticator["last_used_step"]
                )
                with self.connect() as db:
                    db.execute("UPDATE authenticators SET last_used_step=? WHERE user_id=?", (step, pending.user_id))
                action = "auth.mfa.success"
        except ValueError as error:
            failures += 1
            delay = min(60, 5 * 2 ** max(0, failures - 4)) if failures >= 4 else 0
            self.mfa_failures[pending.user_id] = (failures, time.monotonic() + delay)
            self.audit(None, "auth.mfa.failed", "user", str(pending.user_id), False, {})
            raise AuthenticationError(str(error), delay) from error
        self.mfa_failures.pop(pending.user_id, None)
        session = self._create_session(pending, True)
        self.audit(session, action, "user", str(pending.user_id), True, {})
        return session

    def _use_recovery_code(self, user_id: int, code: str) -> None:
        code_hash = self.mfa.recovery_hash(code)
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM recovery_codes WHERE user_id=? AND code_hash=? AND used_at IS NULL",
                (user_id, code_hash),
            ).fetchone()
            if not row:
                raise ValueError("Неверный или уже использованный резервный код")
            db.execute("UPDATE recovery_codes SET used_at=? WHERE id=?", (now_iso(), row["id"]))

    def audit(
        self,
        session: Session | None,
        action: str,
        resource_type: str | None,
        resource_id: str | None,
        success: bool,
        metadata: dict,
    ) -> None:
        safe = self._redact(metadata)
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit(timestamp,user_id,username,action,resource_type,resource_id,success,metadata) VALUES(?,?,?,?,?,?,?,?)",
                (
                    now_iso(),
                    session.user_id if session else None,
                    session.username if session else "system",
                    action,
                    resource_type,
                    resource_id,
                    int(success),
                    json.dumps(safe, ensure_ascii=False),
                ),
            )

    @staticmethod
    def _redact(metadata: dict) -> dict:
        safe = {}
        for key, value in metadata.items():
            lowered = key.lower()
            if any(secret in lowered for secret in ("password", "token", "secret", "private_key")):
                safe[key] = "[REDACTED]"
            elif key == "command" and any(secret in str(value).lower() for secret in ("token", "password", "login")):
                safe[key] = "[REDACTED]"
            else:
                safe[key] = value
        return safe

    def list_users(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT users.id,username,display_name,role_id,roles.name role_name,is_active,must_change_password,"
                "allowed_projects,allowed_servers,created_at,updated_at,last_login_at,password_changed_at,"
                "EXISTS(SELECT 1 FROM authenticators WHERE authenticators.user_id=users.id) mfa_enabled,"
                "(SELECT COUNT(*) FROM recovery_codes WHERE recovery_codes.user_id=users.id AND used_at IS NULL) recovery_codes "
                "FROM users JOIN roles ON roles.id=users.role_id "
                "ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_roles(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM roles ORDER BY builtin DESC,name").fetchall()
        return [dict(row) | {"permissions": json.loads(row["permissions"])} for row in rows]

    def list_audit(self, limit: int = 500) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (max(1, min(limit, 5000)),)).fetchall()
        return [dict(row) | {"metadata": json.loads(row["metadata"])} for row in rows]

    def create_user(
        self,
        actor: Session,
        username: str,
        display_name: str,
        password: str,
        role_id: str,
        allowed_projects: list[str],
        allowed_servers: list[str] | None = None,
        must_change_password: bool = True,
    ) -> int:
        AuthorizationService.require(actor, "users.create")
        if role_id == "owner":
            AuthorizationService.require(actor, "users.manage_owner")
        self.validate_password(password, username)
        timestamp = now_iso()
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM roles WHERE id=?", (role_id,)).fetchone():
                raise ValueError("Роль не существует")
            cursor = db.execute(
                "INSERT INTO users(username,display_name,password_hash,role_id,is_active,must_change_password,allowed_projects,"
                "allowed_servers,created_at,updated_at) VALUES(?,?,?,?,1,?,?,?,?,?)",
                (
                    username.strip(),
                    display_name.strip(),
                    self.passwords.hash(password),
                    role_id,
                    int(must_change_password),
                    json.dumps(allowed_projects),
                    json.dumps(allowed_servers or []),
                    timestamp,
                    timestamp,
                ),
            )
            user_id = int(cursor.lastrowid)
        self.audit(actor, "user.create", "user", str(user_id), True, {"username": username, "role": role_id})
        return user_id

    def set_user_active(self, actor: Session, user_id: int, active: bool) -> None:
        AuthorizationService.require(actor, "users.disable")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._live_session(db, actor)
            if not AuthorizationService._can_snapshot(current, "users.disable"):
                raise PermissionDeniedError("Local account change denied")
            target = db.execute("SELECT role_id,is_active FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise ValueError("Пользователь не найден")
            if not active and target["role_id"] == "owner" and target["is_active"]:
                owners = db.execute("SELECT COUNT(*) FROM users WHERE role_id='owner' AND is_active=1").fetchone()[0]
                if owners <= 1:
                    raise PermissionDeniedError("Нельзя отключить последнего активного Owner")
            db.execute("UPDATE users SET is_active=?,updated_at=? WHERE id=?", (int(active), now_iso(), user_id))
        self.audit(actor, "user.enabled" if active else "user.disabled", "user", str(user_id), True, {})

    def update_user_access(
        self,
        actor: Session,
        user_id: int,
        role_id: str,
        allowed_projects: list[str],
        allowed_servers: list[str] | None = None,
    ) -> None:
        AuthorizationService.require(actor, "users.edit")
        if role_id == "owner":
            AuthorizationService.require(actor, "users.manage_owner")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._live_session(db, actor)
            if not AuthorizationService._can_snapshot(current, "users.edit"):
                raise PermissionDeniedError("Local account change denied")
            if role_id == "owner" and not AuthorizationService._can_snapshot(current, "users.manage_owner"):
                raise PermissionDeniedError("Local Owner assignment denied")
            target = db.execute("SELECT role_id,is_active FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise ValueError("Пользователь не найден")
            if not db.execute("SELECT 1 FROM roles WHERE id=?", (role_id,)).fetchone():
                raise ValueError("Роль не существует")
            if target["role_id"] == "owner" and role_id != "owner" and target["is_active"]:
                owners = db.execute("SELECT COUNT(*) FROM users WHERE role_id='owner' AND is_active=1").fetchone()[0]
                if owners <= 1:
                    raise PermissionDeniedError("Нельзя понизить роль последнего активного Owner")
            db.execute(
                "UPDATE users SET role_id=?,allowed_projects=?,allowed_servers=?,updated_at=? WHERE id=?",
                (role_id, json.dumps(allowed_projects), json.dumps(allowed_servers or []), now_iso(), user_id),
            )
        self.audit(actor, "user.access_changed", "user", str(user_id), True, {"role": role_id})

    def create_role(self, actor: Session, role_id: str, name: str, permissions: list[str]) -> None:
        AuthorizationService.require(actor, "roles.manage")
        unknown = set(permissions) - set(PERMISSIONS)
        if unknown:
            raise ValueError(f"Неизвестные permissions: {', '.join(sorted(unknown))}")
        timestamp = now_iso()
        with self.connect() as db:
            db.execute(
                "INSERT INTO roles(id,name,permissions,builtin,created_at,updated_at) VALUES(?,?,?,0,?,?)",
                (role_id.strip(), name.strip(), json.dumps(sorted(set(permissions))), timestamp, timestamp),
            )
        self.audit(actor, "role.create", "role", role_id, True, {"name": name})

    def change_password(self, session: Session, old_password: str, new_password: str) -> Session:
        with self.connect() as db:
            row = db.execute(
                "SELECT users.*,roles.name role_name,roles.permissions,"
                "EXISTS(SELECT 1 FROM authenticators WHERE authenticators.user_id=users.id) mfa_enabled "
                "FROM users JOIN roles ON roles.id=users.role_id WHERE users.id=?",
                (session.user_id,),
            ).fetchone()
            try:
                valid = row and self.passwords.verify(row["password_hash"], old_password)
            except VerifyMismatchError:
                valid = False
            if not valid:
                raise AuthenticationError("Текущий пароль указан неверно")
        self._set_password(session.user_id, session.username, new_password)
        pending = self._pending_for_user(session.user_id)
        self.revoke_all_sessions(session.user_id)
        refreshed = self._create_session(pending, session.mfa_verified)
        self.audit(refreshed, "auth.password.changed", "user", str(session.user_id), True, {})
        return refreshed

    def change_temporary_password(self, pending: PendingAuthentication, new_password: str) -> PendingAuthentication:
        if not pending.must_change_password:
            return pending
        self._set_password(pending.user_id, pending.username, new_password)
        self.audit(None, "auth.password.changed", "user", str(pending.user_id), True, {"temporary": True})
        return self._pending_for_user(pending.user_id)

    def _set_password(self, user_id: int, username: str, new_password: str) -> None:
        self.validate_password(new_password, username)
        with self.connect() as db:
            current = db.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
            history = db.execute(
                "SELECT password_hash FROM password_history WHERE user_id=? ORDER BY id DESC LIMIT 3", (user_id,)
            ).fetchall()
            for previous in [current, *history]:
                if not previous:
                    continue
                try:
                    if self.passwords.verify(previous["password_hash"], new_password):
                        raise ValueError("Нельзя повторно использовать один из последних паролей")
                except VerifyMismatchError:
                    pass
            timestamp = now_iso()
            db.execute(
                "INSERT INTO password_history(user_id,password_hash,created_at) VALUES(?,?,?)",
                (user_id, current["password_hash"], timestamp),
            )
            db.execute(
                "UPDATE users SET password_hash=?,must_change_password=0,password_changed_at=?,updated_at=? WHERE id=?",
                (self.passwords.hash(new_password), timestamp, timestamp, user_id),
            )

    def _pending_for_user(self, user_id: int) -> PendingAuthentication:
        with self.connect() as db:
            row = db.execute(
                "SELECT users.*,roles.name role_name,roles.permissions,"
                "EXISTS(SELECT 1 FROM authenticators WHERE authenticators.user_id=users.id) mfa_enabled "
                "FROM users JOIN roles ON roles.id=users.role_id WHERE users.id=?",
                (user_id,),
            ).fetchone()
        if not row:
            raise AuthenticationError("Пользователь не найден")
        return self._pending_from_row(row)

    @staticmethod
    def _string_set(value: str) -> frozenset[str]:
        parsed = json.loads(value)
        if not isinstance(parsed, list) or any(not isinstance(item, str) or not item for item in parsed):
            raise PermissionDeniedError("Invalid local authority data")
        return frozenset(parsed)

    def _live_session(self, db, session: Session) -> Session:
        row = db.execute(
            "SELECT s.*, u.username, u.display_name, u.role_id, u.is_active, "
            "u.must_change_password, u.allowed_projects, u.allowed_servers, "
            "r.name role_name, r.permissions FROM sessions s "
            "JOIN users u ON u.id=s.user_id JOIN roles r ON r.id=u.role_id "
            "WHERE s.token_hash=? AND s.user_id=? AND s.revoked_at IS NULL",
            (hashlib.sha256(session.id.encode()).hexdigest(), session.user_id),
        ).fetchone()
        now = time.time()
        if (not row or row["is_active"] != 1 or row["mfa_verified"] not in (0, 1)
                or not math.isfinite(row["inactivity_expires_at"])
                or not math.isfinite(row["absolute_expires_at"])
                or now >= row["inactivity_expires_at"]
                or now >= row["absolute_expires_at"]):
            raise PermissionDeniedError("Local session unavailable or revoked")
        return replace(session, username=row["username"], display_name=row["display_name"],
                       role_id=row["role_id"], role_name=row["role_name"],
                       permissions=self._string_set(row["permissions"]),
                       allowed_project_ids=self._string_set(row["allowed_projects"]),
                       allowed_server_ids=self._string_set(row["allowed_servers"]),
                       mfa_verified=bool(row["mfa_verified"]) and session.mfa_verified,
                       strong_auth_at=min(row["strong_auth_at"], session.strong_auth_at),
                       must_change_password=bool(row["must_change_password"]))

    @contextmanager
    def operation_authorization(self, session: Session, permission: str | tuple[str, ...], project_id: str, server_id: str):
        # Serialize dispatch against SQLite role/scope/revocation writes. This does
        # not recall effects already dispatched to a process or external provider.
        db = None
        try:
            db = self.connect()
            db.execute("BEGIN IMMEDIATE")
            current = self._live_session(db, session)
            required = (permission,) if isinstance(permission, str) else permission
            if not required or any(not AuthorizationService._can_snapshot(current, item, project_id, server_id) for item in required):
                raise PermissionDeniedError("Local operation denied")
        except (sqlite3.Error, ValueError, TypeError, KeyError) as error:
            if db is not None:
                db.close()
            raise PermissionDeniedError("Local authority unavailable") from error
        except PermissionDeniedError:
            if db is not None:
                db.close()
            raise
        try:
            yield
        finally:
            db.rollback()
            db.close()

    def validate_session(self, session: Session, touch: bool = True) -> bool:
        try:
            with self.connect() as db:
                self._live_session(db, session)
                if touch:
                    db.execute(
                        "UPDATE sessions SET last_seen_at=?,inactivity_expires_at="
                        "MIN(?,absolute_expires_at) WHERE token_hash=?",
                        (now_iso(), time.time() + 45 * 60, hashlib.sha256(session.id.encode()).hexdigest()),
                    )
            return True
        except (sqlite3.Error, ValueError, TypeError, KeyError, PermissionDeniedError):
            return False

    def list_sessions(self, user_id: int) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT token_hash,created_at,last_seen_at,inactivity_expires_at,absolute_expires_at,device,revoked_at "
                "FROM sessions WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_all_sessions(self, user_id: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_iso(), user_id))

    def revoke_other_sessions(self, session: Session) -> None:
        token_hash = hashlib.sha256(session.id.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET revoked_at=? WHERE user_id=? AND token_hash<>? AND revoked_at IS NULL",
                (now_iso(), session.user_id, token_hash),
            )
        self.audit(session, "auth.sessions.revoked", "user", str(session.user_id), True, {})

    def reauthenticate(self, session: Session, password: str, code: str = "") -> Session:
        pending = self.authenticate_password(session.username, password)
        if pending.user_id != session.user_id:
            raise AuthenticationError("Неверные данные для подтверждения")
        if pending.mfa_enabled:
            with self.connect() as db:
                authenticator = db.execute(
                    "SELECT * FROM authenticators WHERE user_id=?", (session.user_id,)
                ).fetchone()
            step = self.mfa.verify_reference(authenticator["secret_reference"], code, authenticator["last_used_step"])
            with self.connect() as db:
                db.execute("UPDATE authenticators SET last_used_step=? WHERE user_id=?", (step, session.user_id))
        refreshed = Session(**(session.__dict__ | {"strong_auth_at": time.time()}))
        token_hash = hashlib.sha256(session.id.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET strong_auth_at=? WHERE token_hash=?", (refreshed.strong_auth_at, token_hash)
            )
        self.audit(refreshed, "auth.reauthenticated", "user", str(session.user_id), True, {})
        return refreshed

    def recovery_codes_remaining(self, user_id: int) -> int:
        with self.connect() as db:
            return int(
                db.execute(
                    "SELECT COUNT(*) FROM recovery_codes WHERE user_id=? AND used_at IS NULL", (user_id,)
                ).fetchone()[0]
            )

    def regenerate_recovery_codes(self, session: Session) -> list[str]:
        if not AuthorizationService.has_fresh_reauthentication(session):
            raise PermissionDeniedError("Требуется повторное подтверждение личности")
        codes = self.mfa.generate_recovery_codes()
        timestamp = now_iso()
        with self.connect() as db:
            db.execute("DELETE FROM recovery_codes WHERE user_id=?", (session.user_id,))
            db.executemany(
                "INSERT INTO recovery_codes(user_id,code_hash,created_at) VALUES(?,?,?)",
                [(session.user_id, self.mfa.recovery_hash(value), timestamp) for value in codes],
            )
        self.audit(session, "auth.recovery_codes.regenerated", "user", str(session.user_id), True, {})
        return codes

    def disable_mfa(self, session: Session) -> None:
        if not AuthorizationService.has_fresh_reauthentication(session):
            raise PermissionDeniedError("Требуется повторное подтверждение личности")
        with self.connect() as db:
            row = db.execute(
                "SELECT secret_reference FROM authenticators WHERE user_id=?", (session.user_id,)
            ).fetchone()
            if row:
                self.mfa.secrets.delete(row["secret_reference"])
            db.execute("DELETE FROM authenticators WHERE user_id=?", (session.user_id,))
            db.execute("DELETE FROM recovery_codes WHERE user_id=?", (session.user_id,))
        self.audit(session, "auth.mfa.disabled", "user", str(session.user_id), True, {"severity": "high"})

    def reset_user_mfa(self, actor: Session, user_id: int) -> None:
        AuthorizationService.require(actor, "users.security.reset_mfa")
        if not AuthorizationService.has_fresh_reauthentication(actor):
            raise PermissionDeniedError("Требуется повторное подтверждение личности")
        with self.connect() as db:
            row = db.execute("SELECT secret_reference FROM authenticators WHERE user_id=?", (user_id,)).fetchone()
            if row:
                self.mfa.secrets.delete(row["secret_reference"])
            db.execute("DELETE FROM authenticators WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM recovery_codes WHERE user_id=?", (user_id,))
            db.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_iso(), user_id))
        self.audit(actor, "auth.mfa.reset", "user", str(user_id), True, {"severity": "high"})

    def logout(self, session: Session) -> None:
        token_hash = hashlib.sha256(session.id.encode()).hexdigest()
        with self.connect() as db:
            db.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=?", (now_iso(), token_hash))
        self.audit(session, "auth.logout", "user", str(session.user_id), True, {})
