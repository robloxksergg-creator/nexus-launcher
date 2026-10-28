"""Cooperative Python UI-test guards, never an OS/native sandbox.

Install only in a fresh test process before importing launcher or Qt modules.
No persistent credentials, DNS resolution, external connections or subprocesses.
Native Qt/Chromium and file-dialog coverage requires separate admission.
"""
import ipaddress
import os
from pathlib import Path
import sys
import types


class OfflineEffectDenied(RuntimeError):
    pass


def loopback_address(address):
    """Numeric loopback only; hostnames, wildcards and mapped IPs are refused."""
    if not isinstance(address, tuple) or len(address) not in (2, 4):
        return False
    host, port = address[:2]
    if not isinstance(host, str) or type(port) is not int or not 0 <= port <= 65535:
        return False
    try:
        return host in {"127.0.0.1", "::1"} and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OfflineUIPolicy:
    def __init__(self, profile, *, read_roots=()):
        self.profile = Path(profile).resolve(strict=True)
        if not self.profile.is_dir() or any(self.profile.iterdir()):
            raise OfflineEffectDenied("A new empty test profile is required")
        self.counts = {"network_denied": 0, "process_denied": 0, "keyring_denied": 0,
                       "file_dialog_denied": 0, "desktop_url_denied": 0, "file_denied": 0}
        self.counts["media_denied"] = 0
        self.read_roots = (self.profile, Path(__file__).resolve().parents[1],
                           Path(sys.base_prefix).resolve(),
                           *(Path(root).resolve(strict=True) for root in read_roots))
        self.installed = False
        self.qt_guards_installed = False
        self.native_isolation_verified = False

    def audit(self, event, args):
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if type(path) is int:
                path = self._profile_fd_path(path)
            self.check_path(path, write=bool(writing))
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.truncate"}:
            self.check_path(args[0], write=True)
            # dir_fd could redirect a relative path outside the selected profile.
            if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"} and args[-1] not in (-1, None):
                self._deny_file()
        elif event in {"os.rename", "os.link", "os.symlink"}:
            self.check_path(args[0], write=True)
            self.check_path(args[1], write=True)
            # Links can cross future resolution boundaries. They are unnecessary here.
            if event != "os.rename" or any(value not in (-1, None) for value in args[2:]):
                self._deny_file()
        elif event in {"os.listdir", "os.scandir", "sqlite3.connect"}:
            self.check_path(args[0], write=event == "sqlite3.connect")
        elif event in {"socket.connect", "socket.bind", "socket.sendto"}:
            if not args or not loopback_address(args[-1]):
                self.counts["network_denied"] += 1
                raise OfflineEffectDenied("Non-loopback network operation denied")
        elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"}:
            self.counts["network_denied"] += 1
            raise OfflineEffectDenied("DNS operation denied")
        elif event.startswith(("subprocess.", "os.exec", "os.spawn", "os.startfile")) or event == "os.system":
            self.counts["process_denied"] += 1
            raise OfflineEffectDenied("Process operation denied")

    def _deny_file(self):
        self.counts["file_denied"] += 1
        raise OfflineEffectDenied("File operation outside test contract denied")

    def _profile_fd_path(self, fd):
        # Atomic configuration writes use fdopen(mkstemp()). Resolve the actual
        # Windows handle rather than trusting an integer supplied by a caller.
        if os.name != 'nt':
            self._deny_file()
        import ctypes
        from ctypes import wintypes
        import msvcrt
        try:
            handle = msvcrt.get_osfhandle(fd)
            api = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
            api.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
            api.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            size = api(handle, buffer, len(buffer), 0)
            if not size or size >= len(buffer) or buffer.value.startswith('\\\\?\\UNC\\'):
                self._deny_file()
            path = buffer.value.removeprefix('\\\\?\\')
            self.check_path(path, write=True)
            return path
        except (OSError, ValueError, OverflowError):
            self._deny_file()

    def check_path(self, path, *, write=False):
        if not isinstance(path, (str, bytes, os.PathLike)):
            self._deny_file()  # untracked fd-based access
        try:
            raw = os.fsdecode(path)
            if raw.startswith(('\\', '//')) or ':' in os.path.splitdrive(raw)[1]:
                self._deny_file()  # UNC/device paths and alternate data streams
            candidate = Path(raw).resolve()
        except (OSError, ValueError, TypeError):
            self._deny_file()
        # Never accept secret-named files even under a permitted code root.
        if any(part.lower().startswith('.env') or part.lower() in {'.dev.vars', '.ssh', 'credentials'}
               for part in candidate.parts):
            self._deny_file()
        if candidate.suffix.lower() in {'.key', '.pem', '.pfx', '.p12'}:
            self._deny_file()
        roots = (self.profile,) if write else self.read_roots
        # Frozen Python imports read their appended PYZ from this exact EXE.
        frozen_archive = (not write and getattr(sys, 'frozen', False)
                          and candidate == Path(sys.executable).resolve())
        if not frozen_archive and not any(candidate.is_relative_to(root) for root in roots):
            self._deny_file()
        if not candidate.is_relative_to(self.profile) and candidate.suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:
            self._deny_file()

    def install(self):
        if self.installed or "keyring" in sys.modules or "PySide6" in sys.modules or "nexus_launcher.modern_main" in sys.modules:
            raise OfflineEffectDenied("Guard must precede application and native imports")
        keyring = types.ModuleType("keyring")
        errors = types.ModuleType("keyring.errors")
        errors.PasswordDeleteError = type("PasswordDeleteError", (Exception,), {})

        def deny_keyring(*_args, **_kwargs):
            self.counts["keyring_denied"] += 1
            raise OfflineEffectDenied("Persistent credential access denied")

        keyring.get_password = keyring.set_password = keyring.delete_password = deny_keyring
        keyring.errors = errors
        sys.modules["keyring"] = keyring
        sys.modules["keyring.errors"] = errors
        for name in ("APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE", "TEMP", "TMP", "XDG_CONFIG_HOME"):
            os.environ[name] = str(self.profile)
        os.environ["NEXUS_DISABLE_SELF_UPDATE"] = "1"
        sys.addaudithook(self.audit)
        self.installed = True

    def require_installed(self):
        if not self.installed:
            raise OfflineEffectDenied("Offline guard is not installed")

    def install_qt_guards(self):
        """Intercept the exported Python Qt APIs before application imports.

        These are deliberately synthetic UI adapters, not native I/O isolation.
        Unknown settings APIs fail rather than falling back to the real registry.
        """
        self.require_installed()
        if self.qt_guards_installed or "nexus_launcher.nexus_platform.support_page" in sys.modules or "nexus_launcher.instance_ui" in sys.modules:
            raise OfflineEffectDenied("Qt adapters must precede application imports")
        from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
        policy = self
        stores = {}

        class MemorySettings:
            def __init__(self, *args, **kwargs):
                if args != ("NEXUS", "Support") or kwargs:
                    raise OfflineEffectDenied("Unknown settings contract denied")
                self.values = stores.setdefault(args, {})

            def value(self, key, default=None):
                return self.values.get(key, default)

            def setValue(self, key, value):
                self.values[key] = value

            def remove(self, key):
                self.values.pop(key, None)

        class BlockedFileDialog:
            def __init__(self, *_args, **_kwargs):
                policy.counts["file_dialog_denied"] += 1
                raise OfflineEffectDenied("Native file dialog denied")

            @staticmethod
            def getOpenFileName(*_args, **_kwargs):
                policy.counts["file_dialog_denied"] += 1
                return "", ""

            getSaveFileName = getOpenFileName

            @staticmethod
            def getOpenFileNames(*_args, **_kwargs):
                policy.counts["file_dialog_denied"] += 1
                return [], ""

            @staticmethod
            def getExistingDirectory(*_args, **_kwargs):
                policy.counts["file_dialog_denied"] += 1
                return ""

        def deny_desktop_url(*_args, **_kwargs):
            policy.counts["desktop_url_denied"] += 1
            return False

        class BlockedProcess:
            def __init__(self, *_args, **_kwargs):
                policy.counts["process_denied"] += 1
                raise OfflineEffectDenied("Native process adapter denied")

            @staticmethod
            def startDetached(*_args, **_kwargs):
                policy.counts["process_denied"] += 1
                raise OfflineEffectDenied("Native process adapter denied")

            execute = startDetached

        QtCore.QSettings = MemorySettings
        QtCore.QProcess = BlockedProcess
        QtWidgets.QFileDialog = BlockedFileDialog
        QtGui.QDesktopServices.openUrl = deny_desktop_url
        original_media_source = QtMultimedia.QMediaPlayer.setSource

        def bounded_media_source(player, url):
            if url.isEmpty():
                return original_media_source(player, url)
            if not url.isLocalFile():
                policy.counts["media_denied"] += 1
                return None
            raw = url.toLocalFile()
            if raw.startswith(('\\', '//')) or ':' in os.path.splitdrive(raw)[1]:
                policy.counts["media_denied"] += 1
                return None
            path = Path(raw).resolve()
            asset_root = Path(__file__).resolve().parents[1] / 'assets'
            if not path.is_relative_to(policy.profile) and not path.is_relative_to(asset_root):
                policy.counts["media_denied"] += 1
                return None
            policy.check_path(path)
            return original_media_source(player, url)

        def deny_media_device(*_args, **_kwargs):
            policy.counts["media_denied"] += 1
            raise OfflineEffectDenied("Unknown media device denied")

        QtMultimedia.QMediaPlayer.setSource = bounded_media_source
        QtMultimedia.QMediaPlayer.setSourceDevice = deny_media_device
        self.qt_guards_installed = True
