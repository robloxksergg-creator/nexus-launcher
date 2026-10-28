from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

import keyring
import pyotp

MFA_REQUIRED_ROLES = frozenset({"owner", "administrator", "technical-admin"})


class WindowsCredentialSecretStore:
    SERVICE = "NEXUS Control Panel"

    def set(self, key: str, value: str) -> None:
        keyring.set_password(self.SERVICE, key, value)

    def get(self, key: str) -> str | None:
        return keyring.get_password(self.SERVICE, key)

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(self.SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass


@dataclass(frozen=True)
class PendingMfaSetup:
    user_id: int
    username: str
    secret: str
    uri: str
    expires_at: float


class MfaService:
    def __init__(self, secrets_store: WindowsCredentialSecretStore | None = None):
        self.secrets = secrets_store or WindowsCredentialSecretStore()
        self.pending: dict[int, PendingMfaSetup] = {}

    @staticmethod
    def secret_reference(user_id: int) -> str:
        return f"totp:user:{user_id}"

    def begin_setup(self, user_id: int, username: str) -> PendingMfaSetup:
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret, digits=6, interval=30).provisioning_uri(
            name=username, issuer_name="NEXUS Control Panel"
        )
        setup = PendingMfaSetup(user_id, username, secret, uri, time.time() + 600)
        self.pending[user_id] = setup
        return setup

    def confirm_setup(self, user_id: int, code: str) -> tuple[str, int]:
        setup = self.pending.get(user_id)
        if not setup or setup.expires_at < time.time():
            self.pending.pop(user_id, None)
            raise ValueError("Срок настройки 2FA истёк. Начните настройку заново.")
        step = self.verify_secret(setup.secret, code, None)
        reference = self.secret_reference(user_id)
        self.secrets.set(reference, setup.secret)
        self.pending.pop(user_id, None)
        return reference, step

    def verify_reference(self, reference: str, code: str, last_used_step: int | None) -> int:
        secret = self.secrets.get(reference)
        if not secret:
            raise ValueError("Секрет 2FA недоступен в Windows Credential Manager")
        return self.verify_secret(secret, code, last_used_step)

    @staticmethod
    def verify_secret(secret: str, code: str, last_used_step: int | None) -> int:
        if not code.isdigit() or len(code) != 6:
            raise ValueError("Введите 6-значный код")
        totp = pyotp.TOTP(secret, digits=6, interval=30)
        current = int(time.time() // 30)
        for offset in (-1, 0, 1):
            step = current + offset
            if totp.verify(code, for_time=step * 30, valid_window=0):
                if last_used_step is not None and step <= last_used_step:
                    raise ValueError("Этот одноразовый код уже использован")
                return step
        raise ValueError("Неверный код. Проверьте дату и время на устройстве.")

    @staticmethod
    def generate_recovery_codes(count: int = 10) -> list[str]:
        return [f"{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}" for _ in range(count)]

    @staticmethod
    def recovery_hash(code: str) -> str:
        return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()
