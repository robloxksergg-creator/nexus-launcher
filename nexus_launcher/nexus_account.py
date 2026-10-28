from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

import keyring
import nexus_launcher.build_channel as build_channel
from nexus_launcher.launcher_diagnostics import record as record_diagnostic
from keyring.errors import KeyringError, PasswordDeleteError
from nexus_launcher.resource_limits import read_limited
from nexus_launcher.secure_http import open_https, origin
from nexus_launcher.release_metadata import CURRENT_VERSION

# The workers.dev endpoint avoids local DNS/proxy issues that can affect the
# custom website domain while still reaching the same deployed Worker.
API_BASE = (
    "https://nexusmc-control-plane-staging.robloxksergg.workers.dev"
    if os.environ.get("NEXUS_ENVIRONMENT") == "staging"
    else "https://nexusmc-site.robloxksergg.workers.dev"
)
KEYRING_SERVICE = "NEXUS Launcher"
KEYRING_ACCOUNT = "launcher-session"


class AccountError(RuntimeError):
    def __init__(self, message, *, code=None, setup_url=None, http_status=None, outcome=None):
        super().__init__(message)
        self.code = code
        self.setup_url = setup_url
        self.http_status = http_status
        self.outcome = outcome


class SessionRejected(AccountError):
    """The account service explicitly rejected the bearer credential (401)."""


class TransportError(AccountError):
    """Transient transport/server failure; stored credentials remain valid."""


class OfflineError(TransportError):
    """Connection unavailable; do not erase the saved session."""


class ProtocolError(AccountError):
    """Malformed or unsafe response; do not invalidate the stored session."""


@dataclass(frozen=True)
class NexusProfile:
    minecraft_nick: str
    email: str
    skin_url: str | None = None
    skin_png: bytes | None = None
    skin_model: str = "default"
    is_admin: bool = False
    username: str = ""
    display_name: str = ""
    tester: bool = False
    user_id: str = ""
    profile_completed: bool = False


class NexusAccountClient:
    def __init__(self, base_url: str = API_BASE, timeout: int = 15, *, strict_restore: bool = False):
        selected_origin = origin(base_url)
        staging_origin = origin("https://nexusmc-control-plane-staging.robloxksergg.workers.dev")
        if build_channel.STAGING_BUILD and selected_origin != staging_origin:
            raise AccountError("Staging account access is restricted to the staging origin")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.strict_restore = strict_restore
        self._support_identity = None
        self.keyring_service = KEYRING_SERVICE + (" / staging" if selected_origin == staging_origin else "")

    def _device_id(self) -> str:
        if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
            root = Path(os.environ["LOCALAPPDATA"]) / "NEXUS Launcher"
        elif xdg_config := os.environ.get("XDG_CONFIG_HOME"):
            root = Path(xdg_config) / "nexus-launcher"
        else:
            root = Path.home() / ".config" / "nexus-launcher"
        path = root / "device-id"
        try:
            existing = path.read_text(encoding="ascii").strip()
            if 16 <= len(existing) <= 128:
                return existing
        except OSError:
            pass
        root.mkdir(parents=True, exist_ok=True)
        value = uuid.uuid4().hex
        temporary = path.with_suffix(".tmp")
        temporary.write_text(value, encoding="ascii")
        temporary.replace(path)
        return value

    def _token(self) -> str | None:
        try:
            return keyring.get_password(self.keyring_service, KEYRING_ACCOUNT)
        except KeyringError as error:
            raise AccountError("Не удалось прочитать сессию из системного хранилища. Проверьте доступ к нему и повторите вход.") from error

    def support_session(self, account_id: str) -> str | None:
        """Return only a credential bound to a previously verified profile."""
        token = self._token()
        return token if token and self._support_identity == (account_id, token) else None

    def _request(
        self, path: str, *, method: str = "GET", payload: dict | None = None, token: str | None = None, idempotency_key: str | None = None
    ) -> tuple[dict, bytes | None]:
        if build_channel.STAGING_BUILD and origin(self.base_url) != origin(
            "https://nexusmc-control-plane-staging.robloxksergg.workers.dev"
        ):
            raise AccountError("Staging account access is restricted to the staging origin")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "\\" in path:
            raise AccountError("Invalid account API path")
        headers = {"Accept": "application/json", "User-Agent": f"NEXUS-Launcher/{CURRENT_VERSION}"}
        headers.update(self._additional_headers(path, method))
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        operation = {
            "/api/auth/email/request-code": "registration_code",
            "/api/auth/register": "registration_confirm",
            "/api/profile/setup": "registration_profile",
        }.get(path.split("?", 1)[0], "account")
        started = time.monotonic()
        outcome, http_status = "unexpected_error", None
        try:
            with open_https(request, timeout=self.timeout) as response:
                http_status = getattr(response, "status", None)
                raw = read_limited(response)
                if response.headers.get_content_type() == "image/png":
                    outcome = "ok"
                    return {}, raw
                result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict):
                    raise ProtocolError("Сервис аккаунтов вернул неверную структуру ответа.")
                self._response_headers(path, result, response.headers)
                outcome = "ok"
                return result, None
        except urllib.error.HTTPError as error:
            outcome, http_status = "http_error", error.code
            try:
                error_body = json.loads(read_limited(error).decode("utf-8"))
                message = error_body.get("error") if isinstance(error_body, dict) else None
                if not isinstance(message, str):
                    message = None
            except (ValueError, UnicodeDecodeError):
                message = None
            error_type = (
                SessionRejected
                if error.code == 401
                else TransportError
                if error.code >= 500 or error.code == 429
                else AccountError
            )
            fields = error_body if isinstance(locals().get("error_body"), dict) else {}
            raise error_type(message or "Сервер аккаунтов отклонил запрос.",
                             code=fields.get("code"), setup_url=fields.get("setupUrl"),
                             http_status=http_status, outcome=outcome) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            outcome = "network_error"
            raise OfflineError("Не удалось подключиться к аккаунтам NEXUS.", http_status=http_status, outcome=outcome) from error
        except (ValueError, TypeError, UnicodeError) as error:
            outcome = "protocol_error"
            raise ProtocolError("Сервис аккаунтов вернул некорректный ответ.", http_status=http_status, outcome=outcome) from error
        except ProtocolError as error:
            outcome = "protocol_error"
            error.outcome, error.http_status = outcome, http_status
            raise
        finally:
            record_diagnostic(operation, outcome, http_status,
                              int((time.monotonic() - started) * 1000))
            # Fixed operation/category only: no URL, body, headers or exception text.
            logging.getLogger("nexus.account.request").info(
                "account_request operation=%s outcome=%s http_status=%s duration_ms=%d",
                operation, outcome, http_status, int((time.monotonic() - started) * 1000),
            )

    def _additional_headers(self, path, method):
        return {}

    def _response_headers(self, path, result, headers):
        pass

    def login(self, identifier: str, password: str) -> NexusProfile:
        result, _ = self._request(
            "/api/launcher/auth/login",
            method="POST",
            payload={
                "identifier": identifier,
                "password": password,
                "deviceId": self._device_id(),
            },
        )
        token = result.get("token")
        if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
            raise AccountError("Сервер не вернул сессию лаунчера.")
        profile = self._profile_from_result(result, token)
        try:
            keyring.set_password(self.keyring_service, KEYRING_ACCOUNT, token)
        except KeyringError as error:
            self._support_identity = None
            raise AccountError("Не удалось сохранить сессию в системном хранилище. Проверьте доступ к нему и повторите вход.") from error
        return profile

    def restore(self) -> NexusProfile | None:
        token = self._token()
        if not token:
            return None
        try:
            result, _ = self._request("/api/launcher/profile", token=token)
            return self._profile_from_result(result, token)
        except SessionRejected:
            try:
                keyring.delete_password(self.keyring_service, KEYRING_ACCOUNT)
            except PasswordDeleteError:
                pass
            if self.strict_restore:
                raise
            return None
        except AccountError:
            if self.strict_restore:
                raise
            # A network outage or permission error is not proof of revocation.
            return None

    def logout(self) -> None:
        token = self._token()
        error = None
        if token:
            try:
                self._request("/api/launcher/auth/logout", method="POST", token=token)
            except AccountError as exc:
                error = exc
            finally:
                try:
                    keyring.delete_password(self.keyring_service, KEYRING_ACCOUNT)
                except PasswordDeleteError:
                    pass
        if error and self.strict_restore:
            raise error

    def build_access(self) -> dict[str, dict]:
        result, _ = self._request("/api/launcher/build-access", token=self._token())
        builds = result.get("builds")
        if not isinstance(builds, dict) or any(not isinstance(value, dict) for value in builds.values()):
            raise ProtocolError("Некорректный список сборок.")
        return builds

    def game_ticket(self) -> str:
        token = self._token()
        if not token:
            raise AccountError("Войдите в зарегистрированный аккаунт NEXUS.")
        result, _ = self._request("/api/launcher/game-ticket", method="POST", token=token)
        ticket = result.get("ticket")
        if not isinstance(ticket, str) or not re.fullmatch(r"[a-f0-9]{64}", ticket):
            raise AccountError("Сервер не выдал игровой пропуск.")
        return ticket

    def game_ticket_for(self, profile: NexusProfile) -> str:
        """Issue a fresh ticket bound to the verified local account snapshot."""
        import time
        token = self.support_session(profile.user_id)
        if not token or not profile.user_id or not profile.minecraft_nick:
            raise AccountError("Аккаунт изменён. Повторите вход перед запуском.")
        result, _ = self._request("/api/launcher/game-ticket", method="POST", token=token)
        ticket = result.get("ticket")
        expires = result.get("expiresAt")
        if (self.support_session(profile.user_id) != token
                or result.get("minecraftNick") != profile.minecraft_nick
                or result.get("audience") != "nexus-minecraft"
                or result.get("operation") != "game-login"
                or type(result.get("version")) is not int or result["version"] != 1
                or type(expires) is not int or expires <= time.time() * 1000
                or not isinstance(ticket, str) or not re.fullmatch(r"[a-f0-9]{64}", ticket)):
            raise AccountError("Игровой пропуск не соответствует текущему аккаунту или истёк.")
        return ticket

    def _profile_from_result(self, result: dict, token: str) -> NexusProfile:
        user = result.get("user")
        if not isinstance(user, dict):
            raise ProtocolError("Некорректный профиль аккаунта.")
        skin_url = user.get("skinUrl")
        if skin_url is not None and not isinstance(skin_url, str):
            raise ProtocolError("Некорректный адрес скина.")
        skin_png = None
        if skin_url:
            try:
                _, skin_png = self._request(skin_url, token=token)
            except AccountError:
                skin_png = None
        skin_model = "slim" if user.get("skinModel") == "slim" else "default"
        minecraft_nick = user.get("minecraftNick")
        if not isinstance(minecraft_nick, str) or (minecraft_nick and not re.fullmatch(r"[A-Za-z0-9_]{3,16}", minecraft_nick)):
            raise ProtocolError("У аккаунта NEXUS некорректный Minecraft-ник.")
        if not isinstance(user.get("email", ""), str) or user.get("isAdmin", False) not in (True, False):
            raise ProtocolError("Некорректные поля профиля.")
        user_id = user.get("id", "")
        completed = user.get("profileCompleted", bool(minecraft_nick))
        if not isinstance(user_id, str) or not isinstance(completed, bool) or completed != bool(minecraft_nick):
            raise ProtocolError("Некорректное состояние профиля.")
        self._support_identity = (user_id, token)
        return NexusProfile(
            minecraft_nick,
            str(user.get("email") or ""),
            skin_url,
            skin_png,
            skin_model,
            bool(user.get("isAdmin", False)),
            str(user.get("username") or minecraft_nick.lower()),
            str(user.get("displayName") or minecraft_nick),
            user.get("tester") is True,
            user_id,
            completed,
        )
