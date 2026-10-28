from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nexus_launcher.process_utils import hidden_process_kwargs
from nexus_launcher.projects import ServerProfile
from nexus_launcher.secure_http import open_https


@dataclass
class RuntimeServerState:
    status: str = "stopped"
    pid: int | None = None
    started_at: float | None = None
    exit_code: int | None = None
    last_error: str = ""
    cpu_percent: float = 0.0
    memory_bytes: int = 0
    memory_limit_bytes: int = 0
    disk_bytes: int = 0
    pack_version: str = ""
    expected_mods: int = 0
    installed_mods: int = 0
    missing_mods: int = 0
    extra_mods: int = 0
    pack_checked_at: float = 0.0

    @property
    def uptime(self) -> int:
        return int(time.time() - self.started_at) if self.started_at else 0


def denied_authorization(_permission):
    raise PermissionError("Local controller requires live authorization")


class ServerController(ABC):
    @abstractmethod
    def start(self) -> bool: ...

    @abstractmethod
    def stop(self, timeout: float = 20) -> None: ...

    @abstractmethod
    def restart(self) -> None: ...

    @abstractmethod
    def send_command(self, command: str) -> bool: ...

    @abstractmethod
    def latest_log(self, lines: int = 500) -> str: ...

    def refresh(self) -> None:
        """Refresh externally managed state when supported."""
        return None


class PterodactylServerController(ServerController):
    """Bisquit/Pterodactyl client API controller; credentials stay in OS keyring."""

    KEYRING_SERVICE = "NEXUS Control Panel Server API"
    CLIENT_ONLY_MODS = {
        "ambientsounds_neoforge_v6.3.8_mc1.21.1.jar",
        "appleskin-neoforge-mc1.21-3.0.9.jar",
        "chat_heads-0.15.3-neoforge-1.21.jar",
        "craftpresence-2.7.1%2b1.21.1-neoforge.jar",
        "create-dyn-light-forge-1.21.1-2.0.1.jar",
        "customskinloader_universal-15.0.1.jar",
        "dynamic-fps-3.11.4%2bminecraft-1.21.0-neoforge.jar",
        "entity_model_features-3.2.4-1.21-neoforge.jar",
        "entity_texture_features_1.21-neoforge-7.1.jar",
        "entityculling-neoforge-1.10.5-mc1.21.1.jar",
        "highlighter-1.21-neoforge-1.1.11.jar",
        "iris-neoforge-1.8.14-beta.1%2bmc1.21.1.jar",
        "jade-1.21.1-neoforge-15.10.5.jar",
        "jei-1.21.1-neoforge-19.39.0.370.jar",
        "legendarytooltips-1.21.1-neoforge-1.5.5.jar",
        "melody_neoforge_1.0.10_mc_1.21.jar",
        "mousetweaks-neoforge-mc1.21-2.26.1.jar",
        "notenoughanimations-neoforge-1.12.4-mc1.21.1.jar",
        "particle_core-0.3.3%2b1.21%2bneoforge.jar",
        "prism-1.21.1-neoforge-1.0.11.jar",
        "reeses-sodium-options-neoforge-2.2.3%2bmc1.21.1.jar",
        "screenshot_viewer-1.3.4-neoforge-mc1.21.1.jar",
        "skinlayers3d-neoforge-1.11.2-mc1.21.1.jar",
        "smoothswapping-0.9.3.2-1.21.1-neoforge.jar",
        "sodium-extra-neoforge-0.9.3%2bmc1.21.1.jar",
        "sodium-neoforge-0.8.12%2bmc1.21.1.jar",
        "sodiumdynamiclights-neoforge-1.0.10-1.21.1.jar",
    }

    def __init__(self, server: ServerProfile, event_callback=None, opener=None, keyring_module=None, authorization=None):
        self._authorization = authorization or denied_authorization
        self.server = server
        self.state = RuntimeServerState()
        self.console = deque(maxlen=7500)
        self.process = None
        self._callback = event_callback or (lambda _kind, _value: None)
        self._opener = opener or open_https
        if keyring_module is None:
            import keyring as keyring_module
        self._keyring = keyring_module
        self._refresh_lock = threading.Lock()

    @property
    def credential_key(self) -> str:
        return self.server.credential_key or f"server/{self.server.id}"

    def _token(self) -> str:
        token = self._keyring.get_password(self.KEYRING_SERVICE, self.credential_key)
        if not token:
            raise PermissionError(
                "API-токен Bisquit Host не настроен. Откройте настройки сервера и вставьте Client API key."
            )
        return token

    def _request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        base = self.server.panel_url.rstrip("/")
        identifier = self.server.panel_server_id.strip()
        if not base.startswith("https://") or not identifier:
            raise ValueError("Неверно настроены URL панели или ID сервера")
        body = json.dumps(payload).encode() if payload is not None else None
        permission = (f"servers.{payload['signal']}" if path == "/power" and payload
                      else "servers.command" if path == "/command" else "servers.view")
        try:
            with self._authorization(permission):
                request = urllib.request.Request(
                    f"{base}/api/client/servers/{identifier}{path}", data=body, method=method,
                    headers={"Authorization": f"Bearer {self._token()}",
                             "Accept": "application/json", "Content-Type": "application/json"},
                )
                with self._opener(request, timeout=12) as response:
                    raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise PermissionError("Bisquit Host отклонил API-токен или его права") from error
            raise ConnectionError(f"Bisquit Host API: HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise ConnectionError(f"Bisquit Host недоступен: {error.reason}") from error

    def _power(self, signal: str) -> bool:
        try:
            self.state.status = "starting" if signal == "start" else "stopping"
            self._callback("state", self.state)
            self._request("/power", "POST", {"signal": signal})
            self.console.append(f"[NEXUS] Отправлен power signal: {signal}")
            return True
        except Exception as error:
            self.state.status = "error"
            self.state.last_error = str(error)
            self._callback("state", self.state)
            self._callback("error", str(error))
            return False

    def start(self) -> bool:
        return self._power("start")

    def stop(self, timeout: float = 20) -> None:
        self._power("stop")

    def restart(self) -> None:
        self._power("restart")

    def send_command(self, command: str) -> bool:
        command = command.strip()
        if not command or len(command) > 1000:
            return False
        try:
            self._request("/command", "POST", {"command": command})
            self.console.append(f"> {command}")
            return True
        except Exception as error:
            self.state.last_error = str(error)
            self._callback("error", str(error))
            return False

    def refresh(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            payload = self._request("/resources")
            # Bisquit currently returns metrics at the top level while the
            # stock Pterodactyl API wraps them in `attributes`. Support both.
            data = payload.get("attributes") or payload.get("resources") or {}
            current = str(data.get("current_state", data.get("state", "offline")))
            self.state.status = {"running": "running", "starting": "starting", "stopping": "stopping"}.get(
                current, "stopped"
            )
            self.state.last_error = ""
            self.state.cpu_percent = float(data.get("cpu_absolute", 0) or 0)
            self.state.memory_bytes = int(data.get("memory_bytes", 0) or 0)
            self.state.memory_limit_bytes = int(data.get("memory_limit_bytes", 0) or 0)
            self.state.disk_bytes = int(data.get("disk_bytes", 0) or 0)
            uptime_ms = int(data.get("uptime", 0) or 0)
            if self.state.status == "running":
                self.state.started_at = (
                    time.time() - uptime_ms / 1000 if uptime_ms else (self.state.started_at or time.time())
                )
            if self.state.status == "stopped":
                self.state.started_at = None
                self.state.cpu_percent = 0.0
                self.state.memory_bytes = 0
            if self.server.manifest_url and time.time() - self.state.pack_checked_at >= 60:
                self._refresh_pack_status()
            self._callback("state", self.state)
        except ConnectionError as error:
            # Keep the last known state during host throttling instead of
            # replacing a healthy server with a red false-positive error.
            if "HTTP 429" in str(error):
                self.state.last_error = "API временно ограничил частоту — повторю автоматически"
                self._callback("state", self.state)
            else:
                self.state.status = "error"
                self.state.last_error = str(error)
        except Exception as error:
            self.state.status = "error"
            self.state.last_error = str(error)
        finally:
            self._refresh_lock.release()

    def _refresh_pack_status(self) -> None:
        request = urllib.request.Request(
            self.server.manifest_url, headers={"Accept": "application/json", "User-Agent": "NEXUS-Control-Panel/0.3.2"}
        )
        with self._authorization("servers.view"):
            with self._opener(request, timeout=20) as response:
                manifest = json.loads(response.read())
        expected = {
            Path(str(item.get("path", ""))).name.lower()
            for item in manifest.get("files", [])
            if str(item.get("path", "")).startswith("mods/")
        } - self.CLIENT_ONLY_MODS
        installed: set[str] = set()
        page = 1
        while True:
            listing = self._request(f"/files/list?directory=/mods&per_page=100&page={page}")
            entries = listing.get("entries", {})
            installed.update(str(item.get("name", "")).lower() for item in entries.get("data", []) if item.get("file"))
            if page * 100 >= int(entries.get("total", 0)):
                break
            page += 1
        self.state.pack_version = str(manifest.get("version", ""))
        self.state.expected_mods = len(expected)
        self.state.installed_mods = len(installed)
        self.state.missing_mods = len(expected - installed)
        self.state.extra_mods = len(installed - expected)
        self.state.pack_checked_at = time.time()

    def latest_log(self, lines: int = 500) -> str:
        try:
            with self._authorization("logs.view"):
                base = self.server.panel_url.rstrip("/")
                identifier = self.server.panel_server_id.strip()
                request = urllib.request.Request(
                    f"{base}/api/client/servers/{identifier}/files/contents?file=/logs/latest.log",
                    headers={"Authorization": f"Bearer {self._token()}", "Accept": "text/plain"},
                )
                with self._opener(request, timeout=20) as response:
                    text = response.read().decode("utf-8", errors="replace")
            return "\n".join(text.splitlines()[-max(1, lines) :])
        except Exception as error:
            return f"Не удалось получить logs/latest.log: {error}"


class LocalServerController(ServerController):
    def __init__(
        self,
        server: ServerProfile,
        event_callback: Callable[[str, object], None] | None = None,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        authorization=None,
    ):
        self._authorization = authorization or denied_authorization
        self.server = server
        self.state = RuntimeServerState()
        self.process: subprocess.Popen | None = None
        self.console = deque(maxlen=7500)
        self._callback = event_callback or (lambda _kind, _value: None)
        self._process_factory = process_factory
        self._lock = threading.RLock()

    @property
    def working_directory(self) -> Path:
        return Path(self.server.working_directory).expanduser()

    def _java(self) -> str:
        configured = self.server.java_path.strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Java не найдена: {path}")
            return str(path)
        detected = shutil.which("java")
        if not detected:
            raise FileNotFoundError("Java не найдена. Укажите java.exe в настройках сервера.")
        return detected

    def build_command(self) -> list[str]:
        directory = self.working_directory
        if not self.server.working_directory or not directory.is_dir():
            raise FileNotFoundError("Рабочая папка сервера не существует")
        jar = Path(self.server.server_jar)
        jar = jar if jar.is_absolute() else directory / jar
        if not jar.is_file():
            raise FileNotFoundError(f"Server JAR не найден: {jar}")
        minimum = int(self.server.min_memory_mb)
        maximum = int(self.server.max_memory_mb)
        if minimum < 256 or maximum < minimum:
            raise ValueError("RAM должна быть не менее 256 MB, а Maximum RAM — не меньше Minimum RAM")
        extras = shlex.split(self.server.additional_arguments, posix=True)
        return [self._java(), f"-Xms{minimum}M", f"-Xmx{maximum}M", *extras, "-jar", str(jar), "nogui"]

    def _check_eula(self) -> None:
        eula = self.working_directory / "eula.txt"
        if eula.exists() and "eula=false" in eula.read_text(encoding="utf-8", errors="replace").lower():
            raise PermissionError("Для запуска сервера необходимо принять Minecraft EULA в eula.txt")

    def start(self) -> bool:
        return self._start_with_permission("servers.start")

    def _start_with_permission(self, permission) -> bool:
        with self._lock:
            if self.process and self.process.poll() is None:
                return False
            self.state = RuntimeServerState(status="starting")
            self._callback("state", self.state)
            try:
                command = self.build_command()
                self._check_eula()
                flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                with self._authorization(permission):
                    self.process = self._process_factory(
                        command,
                        cwd=self.working_directory,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                        shell=False,
                        **hidden_process_kwargs(flags),
                    )
                self.state.status = "running"
                self.state.pid = self.process.pid
                self.state.started_at = time.time()
                self._callback("state", self.state)
                threading.Thread(target=self._read_output, daemon=True).start()
                threading.Thread(target=self._wait_for_exit, daemon=True).start()
                return True
            except Exception as error:
                self.state.status = "error"
                self.state.last_error = str(error)
                self._callback("state", self.state)
                self._callback("error", str(error))
                return False

    def _read_output(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        for line in iter(process.stdout.readline, ""):
            clean = line.rstrip("\r\n")
            self.console.append(clean)
            self._callback("console", clean)

    def _wait_for_exit(self) -> None:
        process = self.process
        if not process:
            return
        code = process.wait()
        with self._lock:
            if self.process is not process:
                return
            self.state.exit_code = code
            self.state.pid = None
            self.state.started_at = None
            if self.state.status == "stopping" or code == 0:
                self.state.status = "stopped"
            else:
                self.state.status = "error"
                self.state.last_error = f"Сервер завершился с ошибкой. Exit code: {code}"
            self._callback("state", self.state)

    def stop(self, timeout: float = 20) -> None:
        self._stop_with_permission(timeout, "servers.stop")

    def _stop_with_permission(self, timeout, permission) -> None:
        with self._lock:
            process = self.process
            if not process or process.poll() is not None:
                self.state.status = "stopped"
                self._callback("state", self.state)
                return
            self.state.status = "stopping"
            self._callback("state", self.state)
        threading.Thread(target=self._graceful_stop, args=(process, timeout, permission), daemon=True).start()

    def _stop_effect(self, process, action, permission) -> bool:
        try:
            with self._authorization(permission):
                getattr(process, action)()
            return True
        except PermissionError:
            self.state.last_error = "Local stop authority revoked or unavailable"
            self._callback("error", self.state.last_error)
            return False

    def _graceful_stop(self, process: subprocess.Popen, timeout: float, permission="servers.stop") -> None:
        try:
            if process.stdin:
                with self._authorization(permission):
                    process.stdin.write("stop\n")
                    process.stdin.flush()
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if not self._stop_effect(process, "terminate", permission):
                return
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._stop_effect(process, "kill", permission)
        except PermissionError:
            self.state.last_error = "Local stop authority revoked or unavailable"
            self._callback("error", self.state.last_error)
        except (BrokenPipeError, OSError):
            self._stop_effect(process, "terminate", permission)

    def restart(self) -> None:
        def worker():
            process = self.process
            if process and process.poll() is None:
                self._stop_with_permission(20, ("servers.restart", "servers.stop"))
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    return
            self._start_with_permission(("servers.restart", "servers.start"))

        threading.Thread(target=worker, daemon=True).start()

    def send_command(self, command: str) -> bool:
        command = command.strip()
        process = self.process
        if not command or not process or process.poll() is not None or not process.stdin:
            return False
        try:
            with self._authorization("servers.command"):
                process.stdin.write(command + "\n")
                process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, PermissionError):
            return False

    def latest_log(self, lines: int = 500) -> str:
        path = self.working_directory / "logs" / "latest.log"
        if not path.is_file():
            return "Файл logs/latest.log пока не создан."
        with self._authorization("logs.view"):
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                return "".join(deque(stream, maxlen=max(1, lines)))
