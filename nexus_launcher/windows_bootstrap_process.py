"""Windows bootstrap process boundary: inherited private pipes and lifetime lease.

Handle numbers are public routing information; the challenge never enters argv,
environment variables, disk or logs. No network listener or shared nonce file.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import threading
import time
import uuid

from nexus_launcher.portable_bootstrap import HealthChallenge, valid_health_ack
from nexus_launcher.signed_release import canonical
from nexus_launcher.startup_update_flow import LaunchUncertain

PIPE_ENV = "NEXUS_BOOTSTRAP_HANDLES"
MAX_FRAME = 4096
_spawn_lock = threading.Lock()


def _kernel():
    if os.name != "nt":
        raise OSError("Windows bootstrap only")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _encode(value):
    raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(raw) > MAX_FRAME:
        raise ValueError("IPC frame too large")
    return struct.pack("!I", len(raw)) + raw


def _write(fd, data):
    while data:
        count = os.write(fd, data)
        if count <= 0:
            raise OSError("IPC write failed")
        data = data[count:]


def _read_frame(fd, *, timeout):
    import msvcrt
    kernel = _kernel()
    peek = kernel.PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                     ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    peek.restype = wintypes.BOOL
    deadline, received, expected = time.monotonic() + timeout, bytearray(), 4
    while len(received) < expected:
        if time.monotonic() >= deadline:
            raise TimeoutError("IPC deadline exceeded")
        available = wintypes.DWORD()
        if not peek(msvcrt.get_osfhandle(fd), None, 0, None, ctypes.byref(available), None):
            raise OSError("IPC closed")
        if not available.value:
            time.sleep(.02)
            continue
        block = os.read(fd, min(available.value, expected - len(received)))
        if not block:
            raise OSError("IPC closed")
        received.extend(block)
        if len(received) == 4:
            size = struct.unpack("!I", received)[0]
            if not 0 < size <= MAX_FRAME:
                raise ValueError("Invalid IPC frame length")
            expected = 4 + size
    return json.loads(received[4:].decode("ascii"))


class WindowsLaunchLease:
    """Object existence is the lease; inherited handle keeps it alive in child.

    Does not use a mutex ownership handover (which would introduce a launch gap).
    Local namespace scopes it to the interactive Windows session. The default
    Windows security descriptor is used; this is not protection from same-user
    malware or an administrator.
    """
    def __init__(self, root):
        kernel = _kernel()
        create = kernel.CreateMutexW
        create.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        create.restype = wintypes.HANDLE
        name = "Local\\NEXUS-Startup-" + hashlib.sha256(str(Path(root).absolute()).casefold().encode()).hexdigest()
        ctypes.set_last_error(0)
        handle = create(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError("Cannot establish startup lease")
        self.handle = handle
        if error == 183:  # ERROR_ALREADY_EXISTS
            self.close()
            raise RuntimeError("NEXUS is already starting or running")

    def close(self):
        if getattr(self, "handle", None):
            close = _kernel().CloseHandle
            close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
            close(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class WindowsProcessAdapter:
    def __init__(self, lease, *, health_timeout=60, stop_timeout=5):
        if not isinstance(lease, WindowsLaunchLease) or not lease.handle:
            raise ValueError("Live Windows startup lease required")
        if not 0 < health_timeout <= 120 or not 0 < stop_timeout <= 10:
            raise ValueError("Invalid process deadline")
        self.lease, self.health_timeout, self.stop_timeout = lease, health_timeout, stop_timeout

    def wait_parent(self):
        # This is the startup bootstrap, before any launcher has been started.
        # The lifetime lease rejects a second bootstrap while a child survives.
        return bool(self.lease.handle)

    def _argv(self, executable):
        return [str(executable)]

    def launch(self, executable, cwd, challenge):
        import msvcrt
        executable, cwd = Path(executable).absolute(), Path(cwd).absolute()
        if executable.parent != cwd or executable.suffix.lower() != ".exe":
            raise ValueError("Invalid managed executable")
        request_read, request_write = os.pipe()
        ack_read, ack_write = os.pipe()
        fds = {request_read, request_write, ack_read, ack_write}
        try:
            _write(request_write, _encode({"operation_id": challenge.operation_id,
                                          "candidate_identity": challenge.candidate_identity,
                                          "nonce": challenge.nonce}))
            os.close(request_write)
            fds.remove(request_write)
            handles = [msvcrt.get_osfhandle(request_read), msvcrt.get_osfhandle(ack_write), self.lease.handle]
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith("NEXUS_BOOTSTRAP_")}
            environment[PIPE_ENV] = ",".join(str(handle) for handle in handles)
            info = subprocess.STARTUPINFO()
            info.lpAttributeList = {"handle_list": handles}
            # Windows requires listed handles to be temporarily inheritable.
            # This standalone process never launches other children concurrently.
            with _spawn_lock:
                try:
                    for handle in handles:
                        os.set_handle_inheritable(handle, True)
                    child = subprocess.Popen(self._argv(executable), cwd=cwd, env=environment,
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, close_fds=True, startupinfo=info,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
                finally:
                    for handle in handles:
                        os.set_handle_inheritable(handle, False)
            child._nexus_ack_fd = ack_read
            fds.remove(ack_read)
            return child
        finally:
            for fd in fds:
                os.close(fd)

    def await_health(self, child, challenge):
        fd = child._nexus_ack_fd
        try:
            return _read_frame(fd, timeout=self.health_timeout)
        finally:
            os.close(fd)
            child._nexus_ack_fd = None

    def stop_and_wait(self, child):
        try:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=self.stop_timeout)
            return child.poll() is not None
        except (OSError, subprocess.TimeoutExpired):
            return False

    def launch_current(self, executable, cwd):
        # The backend has reverified this exact installed envelope and all files.
        from nexus_launcher.portable_transition import _read
        envelope = _read(Path(cwd).parent, "envelope.json")
        identity = hashlib.sha256(canonical(envelope["release"])).hexdigest()
        challenge = HealthChallenge(uuid.uuid4().hex, identity, secrets.token_hex(32))
        child = self.launch(executable, cwd, challenge)
        try:
            ack = self.await_health(child, challenge)
            if child.poll() is None and valid_health_ack(ack, challenge, child.pid):
                return True
        except Exception:
            pass
        self.stop_and_wait(child)
        raise LaunchUncertain()


class BootstrapChildSession:
    """Read a prewritten challenge before app imports; retain only ACK + lease."""
    @classmethod
    def receive(cls):
        import msvcrt
        value = os.environ.pop(PIPE_ENV, "")
        parts = value.split(",")
        if len(parts) != 3 or any(not p.isascii() or not p.isdigit() or int(p) <= 0 for p in parts):
            raise ValueError("Private bootstrap handles required")
        handles = list(map(int, parts))
        if len(set(handles)) != 3:
            raise ValueError("Duplicate bootstrap handle")
        for handle in handles:
            os.set_handle_inheritable(handle, False)
        read_fd = msvcrt.open_osfhandle(handles[0], os.O_RDONLY | os.O_BINARY)
        ack_fd = msvcrt.open_osfhandle(handles[1], os.O_WRONLY | os.O_BINARY)
        try:
            request = _read_frame(read_fd, timeout=5)
            if not isinstance(request, dict) or set(request) != {"operation_id", "candidate_identity", "nonce"}:
                raise ValueError("Invalid bootstrap challenge")
            challenge = HealthChallenge(**request)
            import re
            if (not isinstance(challenge.operation_id, str) or not re.fullmatch("[0-9a-f]{32}", challenge.operation_id)
                    or not isinstance(challenge.candidate_identity, str) or not re.fullmatch("[0-9a-f]{64}", challenge.candidate_identity)
                    or not isinstance(challenge.nonce, str) or not re.fullmatch("[0-9a-f]{64}", challenge.nonce)):
                raise ValueError("Invalid bootstrap challenge")
            session = cls()
            session.challenge, session.ack_fd, session.lease_handle = challenge, ack_fd, handles[2]
            return session
        except BaseException:
            os.close(ack_fd)
            raise
        finally:
            os.close(read_fd)

    def ready(self):
        if self.ack_fd is None:
            return
        fd, self.ack_fd = self.ack_fd, None
        try:
            value = {"operation_id": self.challenge.operation_id,
                     "candidate_identity": self.challenge.candidate_identity,
                     "nonce": self.challenge.nonce, "pid": os.getpid(), "ready": True}
            _write(fd, _encode(value))
        finally:
            os.close(fd)

    def close(self):
        if self.ack_fd is not None:
            os.close(self.ack_fd)
            self.ack_fd = None
        if self.lease_handle is not None:
            close = _kernel().CloseHandle
            close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
            close(self.lease_handle)
            self.lease_handle = None
