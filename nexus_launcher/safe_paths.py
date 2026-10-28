"""Portable path policy for files owned by the launcher."""

import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from nexus_launcher.native_transfer import _native


def relative_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Invalid relative path")
    path = PurePosixPath(value)
    parts = value.split("/")
    if path.is_absolute() or any(
        not part
        or part in {".", ".."}
        or part[-1:] in {".", " "}
        or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
        or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", part, re.I)
        for part in parts
    ):
        raise ValueError("Invalid or ambiguous Windows path")
    return tuple(parts)


def checked_path(root: Path, relative: str) -> Path:
    parts = relative_parts(relative)
    root = Path(root).absolute()
    if os.name == "nt":
        if not re.fullmatch(r"[a-zA-Z]:", root.drive):
            raise ValueError("UNC/network/device paths are not supported")
        import ctypes

        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        if get_drive_type(root.anchor) == 4:
            raise ValueError("Mapped network drives are not supported")
        if root.parts[1:]:
            relative_parts("/".join(root.parts[1:]))
    # Do not legitimize a junction hidden above the caller's nominal root.
    for ancestor in reversed((root, *root.parents)):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Symlink/junction/reparse point is not allowed")
    current = root
    for part in (None, *parts):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Symlink/junction/reparse point is not allowed")
    current.resolve().relative_to(root.resolve())
    return current


@contextmanager
def pinned_directory(directory: Path, *, create=False):
    """Pin each Windows ancestor without following reparse points or sharing DELETE.

    This prevents directory rename/junction substitution for the duration of I/O.
    It is not a substitute for exclusive creation / validation of leaf files.
    """
    directory = Path(directory).absolute()
    checked_path(directory, "probe")
    if os.name != "nt":
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        yield directory
        return
    if _native is not None and hasattr(_native, "SAFE_IO_API_VERSION"):
        if _native.SAFE_IO_API_VERSION != 1:
            raise ImportError("Incompatible NEXUS native safe-IO API")
        pin = _native.WindowsDirectoryPin(str(directory), create)
        try:
            yield directory
        finally:
            pin.close()
        return
    import ctypes
    from ctypes import wintypes

    class AttributeTag(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handles = []
    try:
        for ancestor in reversed((directory, *directory.parents)):
            if create:
                ancestor.mkdir(exist_ok=True)
            # Attribute-only handles do NOT enforce the sharing check on Windows.
            # FILE_LIST_DIRECTORY is required to deny concurrent rename/delete.
            handle = kernel.CreateFileW("\\\\?\\" + str(ancestor), 0x81, 3, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = AttributeTag()
            if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400 or not info.attributes & 0x10:
                raise ValueError("Unsafe reparse point/non-directory in I/O path")
        yield directory
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def validate_paths(root: Path, paths, allowed_roots: set[str]) -> None:
    seen = set()
    for value in paths:
        parts = relative_parts(value)
        if parts[0] not in allowed_roots:
            raise ValueError("Path is outside managed roots")
        key = value.casefold()
        if key in seen:
            raise ValueError("Case-insensitive duplicate path")
        seen.add(key)
        checked_path(root, value)


def checked_tree(root: Path, relative: str) -> Path:
    """Preflight an owned cleanup tree without following reparse directories."""
    target = checked_path(root, relative)
    pending = [target] if target.is_dir() else []
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                path = checked_path(root, Path(entry.path).relative_to(root).as_posix())
                if path.is_dir():
                    pending.append(path)
    return target


def replace_file(source, target, *, expected_sha256=None):
    """Replace a file through its opened handle on Windows, not a raced source name."""
    source, target = Path(source).absolute(), Path(target).absolute()
    checked_path(source.parent, source.name)
    checked_path(target.parent, target.name)
    with pinned_directory(source.parent), pinned_directory(target.parent):
        if os.name == "nt" and _native is not None and hasattr(_native, "HANDLE_REPLACE_API_VERSION"):
            if _native.HANDLE_REPLACE_API_VERSION != 1:
                raise ImportError("Unsupported native handle replacement API")
            from nexus_launcher.resource_limits import MAX_FILE_BYTES

            _native.windows_replace_file(str(source), str(target), expected_sha256, MAX_FILE_BYTES)
            return
        if os.name != "nt":
            if expected_sha256 is not None:
                import hashlib

                with source.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
                        raise ValueError("Staged file hash mismatch")
            os.replace(source, target)
            return
        import ctypes
        import hashlib
        import time
        from ctypes import wintypes

        from nexus_launcher.resource_limits import MAX_FILE_BYTES

        class AttributeTag(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

        # Use the same extended absolute spelling as CreateFileW above/below.
        # FileRenameInfo otherwise applies MAX_PATH even to a valid long path.
        # checked_path() already rejected caller-supplied device/UNC paths.
        name = "\\\\?\\" + str(target)

        class RenameInfo(ctypes.Structure):
            _fields_ = [
                ("replace", wintypes.DWORD),
                ("root", wintypes.HANDLE),
                ("length", wintypes.DWORD),
                ("name", wintypes.WCHAR * (len(name.encode("utf-16-le")) // 2 + 1)),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # READ + DELETE; deny concurrent writes and deletes on the leaf itself.
        handle = kernel.CreateFileW("\\\\?\\" + str(source), 0x80010000, 1, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            attributes = AttributeTag()
            if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
                raise ctypes.WinError(ctypes.get_last_error())
            if attributes.attributes & (0x400 | 0x10):
                raise ValueError("Source is a reparse point/directory")
            if expected_sha256 is not None:
                kernel.ReadFile.argtypes = [
                    wintypes.HANDLE,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.c_void_p,
                ]
                buffer, count, digest = ctypes.create_string_buffer(1024 * 1024), wintypes.DWORD(), hashlib.sha256()
                total, deadline = 0, time.monotonic() + 300
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Staged file verification exceeded its time budget")
                    if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    total += count.value
                    if total > MAX_FILE_BYTES:
                        raise ValueError("Staged file exceeds byte limit")
                    if not count.value:
                        break
                    digest.update(buffer.raw[: count.value])
                if digest.hexdigest() != expected_sha256:
                    raise ValueError("Staged file hash mismatch")
            info = RenameInfo()
            info.replace, info.root, info.length, info.name = 1, None, len(name.encode("utf-16-le")), name
            rename_deadline = time.monotonic() + 2
            while not kernel.SetFileInformationByHandle(handle, 3, ctypes.byref(info), ctypes.sizeof(info)):
                error = ctypes.get_last_error()
                if error not in {5, 32, 33} or time.monotonic() >= rename_deadline:
                    raise ctypes.WinError(error)
                # Antivirus/indexers can briefly deny replacement. Handles and
                # containment remain pinned throughout this bounded retry.
                time.sleep(0.05)
        finally:
            kernel.CloseHandle(handle)


def atomic_copy(source, target, *, expected_sha256=None):
    """Copy into an exclusive owned temporary file, never through a target link."""
    import hashlib
    import tempfile

    from nexus_launcher.resource_limits import MAX_FILE_BYTES, copy_limited

    source, target = Path(source).absolute(), Path(target).absolute()
    with pinned_directory(source.parent), pinned_directory(target.parent, create=True):
        checked_path(source.parent, source.name)
        checked_path(target.parent, target.name)
        descriptor, temporary = tempfile.mkstemp(prefix="copy-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
                if os.name == "nt" and _native is not None and hasattr(_native, "COPY_STREAM_API_VERSION"):
                    if _native.COPY_STREAM_API_VERSION != 1:
                        raise ImportError("Unsupported native copy stream API")
                    import msvcrt

                    # Fresh, unused Python streams; native duplicates retain the
                    # same offsets without taking ownership of Python handles.
                    _, actual = _native.windows_copy_streams(
                        msvcrt.get_osfhandle(input_stream.fileno()),
                        msvcrt.get_osfhandle(output.fileno()), MAX_FILE_BYTES)
                else:
                    digest = hashlib.sha256()
                    copy_limited(input_stream, output, limit=MAX_FILE_BYTES, digest=digest)
                    actual = digest.hexdigest()
                output.flush()
                os.fsync(output.fileno())
            if expected_sha256 is not None and actual != expected_sha256:
                raise ValueError("Backup hash mismatch")
            replace_file(temporary, target, expected_sha256=actual)
        finally:
            Path(temporary).unlink(missing_ok=True)


def unlink_file(path, *, missing_ok=False):
    path = Path(path).absolute()
    if missing_ok and not path.parent.exists():
        return
    with pinned_directory(path.parent):
        checked_path(path.parent, path.name).unlink(missing_ok=missing_ok)


def remove_owned_tree(root, relative):
    """Delete only a validated owned tree, pinning ancestors during traversal."""
    root = Path(root).absolute()
    target = checked_tree(root, relative)
    if not target.exists():
        return
    with pinned_directory(target.parent):
        with pinned_directory(target):
            for child in target.iterdir():
                checked_path(target, child.name)
                if child.is_dir():
                    remove_owned_tree(target, child.name)
                else:
                    unlink_file(child)
        # rmdir never traverses a replacement directory/junction.
        target.rmdir()
