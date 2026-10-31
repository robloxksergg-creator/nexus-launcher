"""Per-user ShellLink creation through Windows COM, never a shell command."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
import uuid


class GUID(ctypes.Structure):
    _fields_ = [('bytes', ctypes.c_ubyte * 16)]

    @classmethod
    def parse(cls, text):
        return cls((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le))


def desktop_directory():
    if os.name != 'nt':
        raise OSError('Windows desktop shortcut required')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    ole = ctypes.OleDLL('ole32')
    shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                                         wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    result = ctypes.c_void_p()
    folder = GUID.parse('B4BFCC3A-DB2C-424C-B029-7FE99A87C641')
    status = shell.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(result))
    if status < 0:
        raise OSError('Desktop directory unavailable')
    try:
        return Path(ctypes.wstring_at(result))
    finally:
        ole.CoTaskMemFree(result)


def create_shortcut(executable, directory):
    """Never replace an existing desktop item. Tests may supply an owned folder."""
    if os.name != 'nt':
        raise OSError('Windows desktop shortcut required')
    executable = Path(executable).absolute()
    if not executable.is_file():
        raise OSError('Installed executable missing')
    from nexus_launcher.safe_paths import pinned_directory
    ole = ctypes.OleDLL('ole32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    status = ole.CoInitializeEx(None, 2)
    if status < 0:
        raise OSError('Shortcut COM initialization failed')
    link = ctypes.c_void_p()
    persist = ctypes.c_void_p()
    temporary = None

    def method(pointer, index, result, *arguments):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[index])

    def checked(result):
        if result < 0:
            raise OSError('Could not create desktop shortcut')

    try:
        clsid = GUID.parse('00021401-0000-0000-C000-000000000046')
        iid = GUID.parse('000214F9-0000-0000-C000-000000000046')
        checked(ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(link)))
        for index, value in [(20, str(executable)), (9, str(executable.parent)),
                             (7, 'NEXUS Launcher — ForceCore')]:
            checked(method(link, index, ctypes.c_long, wintypes.LPCWSTR)(link, value))
        checked(method(link, 17, ctypes.c_long, wintypes.LPCWSTR, ctypes.c_int)(link, str(executable), 0))
        iid_file = GUID.parse('0000010B-0000-0000-C000-000000000046')
        checked(method(link, 0, ctypes.c_long, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
            link, ctypes.byref(iid_file), ctypes.byref(persist)))
        with pinned_directory(directory):
            fd, name = tempfile.mkstemp(prefix='.nexus-shortcut-', suffix='.lnk', dir=directory)
            os.close(fd)
            temporary = Path(name)
            checked(method(persist, 6, ctypes.c_long, wintypes.LPCWSTR, wintypes.BOOL)(persist, str(temporary), True))
            for number in range(1, 100):
                destination = Path(directory) / ('NEXUS Launcher' + (f' ({number})' if number > 1 else '') + '.lnk')
                try:
                    # Windows rename refuses an existing destination atomically.
                    os.rename(temporary, destination)
                    temporary = None
                    return destination
                except FileExistsError:
                    continue
            raise OSError('No unused desktop shortcut name')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if persist:
            method(persist, 2, wintypes.ULONG)(persist)
        if link:
            method(link, 2, wintypes.ULONG)(link)
        ole.CoUninitialize()
