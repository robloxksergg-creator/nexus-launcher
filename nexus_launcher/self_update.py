from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from nexus_launcher.platform_support import app_data_dir, architecture_id, platform_id
from nexus_launcher.release_metadata import CURRENT_VERSION
from nexus_launcher.resource_limits import ensure_space, read_limited
from nexus_launcher.safe_paths import checked_path, replace_file
from nexus_launcher.secure_http import open_https
from nexus_launcher.signed_release import verify_envelope
from nexus_launcher.update_state import remember_release, serialized

MANIFEST_URL = "https://nexusmc-site.robloxksergg.workers.dev/api/launcher/update"
FALLBACK_MANIFEST_URL = "https://nexusmc.flux-productions.com/api/launcher/update"
MAX_LAUNCHER_BYTES = 200 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
DOWNLOAD_PAGE = "https://nexusmc.flux-productions.com/download"
TRUSTED_HOSTS = {"nexusmc-site.robloxksergg.workers.dev", "nexusmc.flux-productions.com"}
startup_release = None


def validate_url(url: str) -> None:
    # urlsplit silently strips some control characters and leading whitespace.
    # Reject ambiguous input before normalization or any network operation.
    if not isinstance(url, str) or not url or url != url.strip() or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("Некорректный адрес обновления")
    parts = urllib.parse.urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in TRUSTED_HOSTS
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.fragment
    ):
        raise ValueError("Недоверенный адрес обновления")


class TrustedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_release_url(request, timeout):
    validate_url(request.full_url)
    return open_https(request, timeout=timeout, allowed_hosts=TRUSTED_HOSTS)


def version_tuple(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"v?\d{1,6}(?:\.\d{1,6}){2,3}", value):
        raise ValueError("Некорректная версия обновления")
    clean = value.removeprefix("v")
    return tuple(int(part) for part in clean.split("."))


@dataclass(frozen=True)
class LauncherRelease:
    version: str
    url: str
    sha256: str
    notes: str = ""
    size: int = 0
    envelope: dict | None = None

    def validate(self):
        version_tuple(self.version)
        validate_url(self.url)
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Некорректная контрольная сумма")

    def authenticated(self):
        payload = verify_envelope(self.envelope)
        if payload.get("available") is False:
            raise ValueError("Release не разрешён к установке")
        if (
            payload.get("version") != self.version
            or payload.get("url") != self.url
            or payload.get("sha256") != self.sha256
            or payload.get("size") != self.size
            or type(self.size) is not int
            or not 0 < self.size <= MAX_LAUNCHER_BYTES
        ):
            raise ValueError("Поля обновления не соответствуют подписанному manifest")
        if version_tuple(self.version) <= version_tuple(CURRENT_VERSION):
            raise ValueError("Откат на предыдущую версию запрещён")
        if payload.get("platform") != platform_id() or payload.get("arch") != architecture_id():
            raise ValueError("Обновление не подходит этой системе")
        return payload


class SelfUpdater:
    def __init__(self, manifest_url: str = MANIFEST_URL, timeout: int = 8):
        validate_url(manifest_url)
        self.manifest_url = manifest_url
        self.timeout = timeout
        self.update_dir = app_data_dir() / "updates"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    @serialized
    def check(self) -> LauncherRelease | None:
        candidates = [self.manifest_url]
        if self.manifest_url == MANIFEST_URL:
            candidates.append(FALLBACK_MANIFEST_URL)
        last_error: Exception | None = None
        payload = None
        for candidate in candidates:
            try:
                request = urllib.request.Request(
                    candidate
                    + ("&" if "?" in candidate else "?")
                    + urllib.parse.urlencode({"platform": platform_id(), "arch": architecture_id()}),
                    headers={"Accept": "application/json", "User-Agent": f"NEXUS-Launcher/{CURRENT_VERSION}"},
                )
                with open_release_url(request, timeout=self.timeout) as response:
                    try:
                        raw = read_limited(response, MAX_MANIFEST_BYTES, timeout=self.timeout * 2)
                    except ValueError as error:
                        raise ValueError("Манифест обновления слишком большой") from error
                    payload = json.loads(raw)
                break
            except (OSError, urllib.error.URLError, TimeoutError) as error:
                last_error = error
        if payload is None:
            if last_error is not None:
                raise last_error
            raise ValueError("Пустой манифест обновления")
        if not isinstance(payload, dict):
            raise ValueError("Некорректный манифест обновления")
        if payload.get("available") is False:
            return None
        envelope = payload if payload.get("schema") == 2 else None
        if envelope:
            payload = verify_envelope(envelope)
            if payload.get("available") is False:
                return None
        release = LauncherRelease(
            str(payload["version"]),
            str(payload["url"]),
            str(payload["sha256"]).lower(),
            str(payload.get("notes", "")),
            payload.get("size", 0),
            envelope,
        )
        release.validate()
        if version_tuple(release.version) <= version_tuple(CURRENT_VERSION):
            return None
        if envelope:
            release.authenticated()
            remember_release(self.update_dir, envelope)
        # The binary is the authoritative identity of an installed release.
        # This also breaks an update loop if an EXE was accidentally packaged
        # with an older CURRENT_VERSION string.
        if getattr(sys, "frozen", False):
            current = Path(sys.executable).resolve()
            try:
                if current.is_file() and self._sha256(current) == release.sha256:
                    return None
            except OSError:
                pass
        return release

    @serialized
    def download(self, release: LauncherRelease, progress=lambda _done, _total: None) -> Path:
        release.validate()
        release.authenticated()
        remember_release(self.update_dir, release.envelope)
        checked_path(self.update_dir, "pending")
        self.update_dir.mkdir(parents=True, exist_ok=True)
        ensure_space(self.update_dir, release.size * 2)
        suffix = ".dmg" if sys.platform == "darwin" else ".exe" if sys.platform == "win32" else ".AppImage"
        checked_path(self.update_dir, "pending")
        operation = Path(tempfile.mkdtemp(prefix="release-", dir=self.update_dir))
        target = checked_path(operation, f"NEXUS-Launcher-{release.version}{suffix}")
        temporary = checked_path(operation, "payload.part")
        digest = hashlib.sha256()
        done = 0
        request = urllib.request.Request(release.url, headers={"User-Agent": f"NEXUS-Launcher/{CURRENT_VERSION}"})
        try:
            deadline = time.monotonic() + 300
            with open_release_url(request, timeout=60) as response, temporary.open("xb") as output:
                total = int(response.headers.get("Content-Length", str(release.size)))
                if total != release.size:
                    raise ValueError("Обновление лаунчера слишком большое")
                read = getattr(response, "read1", response.read)
                while block := read(1024 * 1024):
                    if time.monotonic() > deadline:
                        raise TimeoutError("Время загрузки обновления истекло")
                    done += len(block)
                    if done > MAX_LAUNCHER_BYTES:
                        raise ValueError("Обновление лаунчера слишком большое")
                    digest.update(block)
                    output.write(block)
                    progress(done, total or done)
                output.flush()
                os.fsync(output.fileno())
            if not done or (total and total != done) or digest.hexdigest() != release.sha256:
                raise ValueError("Контрольная сумма обновления не совпала")
            replace_file(temporary, target, expected_sha256=release.sha256)
            from nexus_launcher.user_instances import atomic_json

            atomic_json(checked_path(operation, "manifest.json"), release.envelope)
            return target
        finally:
            checked_path(operation, temporary.name).unlink(missing_ok=True)

    def install_after_exit(self, downloaded: Path) -> None:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            raise RuntimeError("Автоустановка отключена вне собранного Windows EXE")
        from nexus_launcher.launcher_update_job import start_update

        start_update(self.update_dir, downloaded, Path(sys.executable), os.getpid())


def try_startup_update(progress=lambda _text, _done, _total: None) -> bool:
    """Notify only. Never download, replace, or execute an update at startup."""
    global startup_release
    startup_release = None
    if not getattr(sys, "frozen", False):
        return False
    try:
        progress("Проверка новой версии…", 0, 0)
        startup_release = SelfUpdater().check()
        progress("Новая версия доступна на сайте" if startup_release else "Лаунчер обновлён", 1, 1)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, urllib.error.URLError):
        progress("Проверка обновлений недоступна — продолжаю запуск", 1, 1)
    return False
