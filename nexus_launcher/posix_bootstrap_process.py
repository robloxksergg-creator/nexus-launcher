"""POSIX launcher lifecycle: private inherited pipes and inherited flock lease.

Only a concrete Popen child may acknowledge readiness. A nonce never travels
through arguments, the environment or a filesystem marker. This is not a
sandbox against another process controlled by the same desktop user.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import select
import stat
import struct
import subprocess
import sys
import time
import uuid

from nexus_launcher.portable_bootstrap import HealthChallenge, valid_health_ack
from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.signed_release import canonical
from nexus_launcher.startup_update_flow import LaunchUncertain

PIPE_ENV = 'NEXUS_POSIX_BOOTSTRAP_FDS'
MAX_FRAME = 4096


def _write(fd, data):
    while data:
        n = os.write(fd, data)
        if n <= 0:
            raise OSError('Private pipe closed')
        data = data[n:]


def _encode(value):
    raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode('ascii')
    if not 0 < len(raw) <= MAX_FRAME:
        raise ValueError('Private IPC frame too large')
    return struct.pack('!I', len(raw)) + raw


def _read_frame(fd, timeout):
    end = time.monotonic() + timeout
    data, length = bytearray(), 4
    while len(data) < length:
        remaining = end - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError('Private IPC deadline exceeded')
        block = os.read(fd, length - len(data))
        if not block:
            raise OSError('Private pipe closed')
        data.extend(block)
        if len(data) == 4:
            size = struct.unpack('!I', data)[0]
            if not 0 < size <= MAX_FRAME:
                raise ValueError('Invalid private IPC length')
            length = size + 4
    return json.loads(data[4:].decode('ascii'))


def child_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('NEXUS_BOOTSTRAP_', 'NEXUS_POSIX_BOOTSTRAP_', '_PYI_'))}
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    # Do not load a new release against the old PyInstaller bundle's libraries.
    for name in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH'):
        original = env.pop(name + '_ORIG', None)
        env.pop(name, None)
        if original is not None:
            env[name] = original
    return env


class PosixLaunchLease:
    def __init__(self, root):
        if os.name != 'posix':
            raise OSError('POSIX host required')
        import fcntl
        self.fd = None
        with pinned_directory(root, create=True):
            path = checked_path(root, 'process.lock')
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError('Invalid launcher lease file')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        if self.fd is not None:
            # Never LOCK_UN: the child retains the same open file description.
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PosixProcessAdapter:
    def __init__(self, lease, *, health_timeout=60, stop_timeout=5):
        if not isinstance(lease, PosixLaunchLease) or lease.fd is None:
            raise ValueError('Live POSIX lease required')
        if not 0 < health_timeout <= 120 or not 0 < stop_timeout <= 10:
            raise ValueError('Invalid native process deadlines')
        self.lease, self.health_timeout, self.stop_timeout = lease, health_timeout, stop_timeout

    def wait_parent(self):
        return self.lease.fd is not None

    def _argv(self, executable):
        return [str(executable)]

    def _validate(self, executable, cwd):
        relative = executable.relative_to(cwd).as_posix()
        if checked_path(cwd, relative) != executable or not os.access(executable, os.X_OK):
            raise ValueError('Invalid verified POSIX executable')
        if sys.platform == 'darwin':
            bundle = cwd / 'NEXUS Launcher.app'
            # A developer signature/notarization is never invented or bypassed.
            for args in (['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)],
                         ['/usr/bin/lipo', '-archs', str(executable)]):
                result = subprocess.run(args, check=True, capture_output=True, timeout=30,
                                        env=child_environment())
                if args[0].endswith('lipo') and result.stdout.strip() != b'arm64':
                    raise ValueError('Wrong macOS architecture')
            from nexus_launcher.posix_quarantine import assess
            assess(bundle, child_environment())
        elif sys.platform.startswith('linux'):
            with executable.open('rb') as stream:
                header = stream.read(20)
            if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00':
                raise ValueError('Wrong Linux executable architecture')
        else:
            raise OSError('Unsupported native launcher host')

    def launch(self, executable, cwd, challenge):
        executable, cwd = Path(executable).absolute(), Path(cwd).absolute()
        self._validate(executable, cwd)
        read_fd, write_fd = os.pipe()
        ack_read, ack_write = os.pipe()
        owned = {read_fd, write_fd, ack_read, ack_write}
        try:
            _write(write_fd, _encode({'operation_id': challenge.operation_id,
                                     'candidate_identity': challenge.candidate_identity,
                                     'nonce': challenge.nonce}))
            os.close(write_fd)
            owned.remove(write_fd)
            env = child_environment()
            env[PIPE_ENV] = ','.join(map(str, (read_fd, ack_write, self.lease.fd)))
            child = subprocess.Popen(self._argv(executable), cwd=cwd, env=env,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, close_fds=True,
                                     pass_fds=(read_fd, ack_write, self.lease.fd), start_new_session=True)
            child._nexus_ack_fd = ack_read
            owned.remove(ack_read)
            return child
        finally:
            for fd in owned:
                os.close(fd)

    def await_health(self, child, challenge):
        fd = child._nexus_ack_fd
        try:
            return _read_frame(fd, self.health_timeout)
        finally:
            os.close(fd)
            child._nexus_ack_fd = None

    def stop_and_wait(self, child):
        fd = getattr(child, '_nexus_ack_fd', None)
        if fd is not None:
            os.close(fd)
            child._nexus_ack_fd = None
        try:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=self.stop_timeout)
            return child.poll() is not None
        except (OSError, subprocess.TimeoutExpired):
            return False

    def launch_current(self, executable, cwd):
        from nexus_launcher.portable_transition import _read
        envelope = _read(Path(cwd).parent, 'envelope.json')
        identity = hashlib.sha256(canonical(envelope['release'])).hexdigest()
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


class PosixChildSession:
    @classmethod
    def receive(cls):
        value = os.environ.pop(PIPE_ENV, '')
        parts = value.split(',')
        if len(parts) != 3 or any(not x.isascii() or not x.isdigit() or int(x) < 3 for x in parts):
            raise ValueError('Private POSIX descriptors required')
        fds = list(map(int, parts))
        if len(set(fds)) != 3:
            raise ValueError('Duplicate POSIX descriptor')
        try:
            for fd in fds:
                os.set_inheritable(fd, False)
            if not all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in fds[:2]):
                raise ValueError('Private pipes required')
            if not stat.S_ISREG(os.fstat(fds[2]).st_mode):
                raise ValueError('Launcher lease missing')
            request = _read_frame(fds[0], 5)
            if not isinstance(request, dict) or set(request) != {'operation_id', 'candidate_identity', 'nonce'}:
                raise ValueError('Invalid native challenge')
            for name, length in [('operation_id', 32), ('candidate_identity', 64), ('nonce', 64)]:
                if not isinstance(request[name], str) or not re.fullmatch('[0-9a-f]{' + str(length) + '}', request[name]):
                    raise ValueError('Invalid native challenge field')
            session = cls()
            session.challenge, session.ack_fd, session.lease_fd = HealthChallenge(**request), fds[1], fds[2]
            return session
        except BaseException:
            for fd in fds[1:]:
                os.close(fd)
            raise
        finally:
            os.close(fds[0])

    def ready(self):
        if self.ack_fd is not None:
            fd, self.ack_fd = self.ack_fd, None
            try:
                _write(fd, _encode({'operation_id': self.challenge.operation_id,
                                    'candidate_identity': self.challenge.candidate_identity,
                                    'nonce': self.challenge.nonce, 'pid': os.getpid(), 'ready': True}))
            finally:
                os.close(fd)

    def close(self):
        for name in ('ack_fd', 'lease_fd'):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)
