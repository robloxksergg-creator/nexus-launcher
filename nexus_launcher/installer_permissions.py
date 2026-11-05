"""Explicit UAC for one new installation directory, never for game execution."""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import re
import subprocess
import sys

from nexus_launcher.safe_paths import checked_path


def validate_request(directory, sid):
    directory = Path(directory)
    if not directory.is_absolute() or directory == Path(directory.anchor):
        raise ValueError('Invalid installation directory')
    if not re.fullmatch(r'S-1-5-21-(?:[0-9]{1,10}-){3}[0-9]{1,10}', sid):
        raise ValueError('Only a concrete Windows account SID is permitted')
    checked_path(directory, 'probe')
    if directory.exists() or not directory.parent.is_dir():
        raise ValueError('UAC preparation requires a new folder in an existing parent')
    return directory


def current_sid():
    if os.name != 'nt':
        raise OSError('Windows required')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    api.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    api.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    api.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    token = w.HANDLE()
    if not api.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = w.DWORD()
        api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 0 < size.value <= 65536:
            raise OSError('Invalid token information size')
        buffer = ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = w.LPWSTR()
        if not api.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


class PermissionRequest:
    def __init__(self, directory, owner):
        if os.name != 'nt' or not getattr(sys, 'frozen', False):
            raise OSError('Frozen Windows installer required')
        sid = current_sid()
        directory = validate_request(directory, sid)
        class ExecuteInfo(ctypes.Structure):
            _fields_ = [('cbSize', w.DWORD), ('fMask', w.ULONG), ('hwnd', w.HWND),
                        ('lpVerb', w.LPCWSTR), ('lpFile', w.LPCWSTR), ('lpParameters', w.LPCWSTR),
                        ('lpDirectory', w.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', w.HINSTANCE),
                        ('lpIDList', ctypes.c_void_p), ('lpClass', w.LPCWSTR), ('hkeyClass', w.HKEY),
                        ('dwHotKey', w.DWORD), ('hIcon', w.HANDLE), ('hProcess', w.HANDLE)]
        info = ExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x40 | 0x100  # keep owned process handle; no async shell work
        info.hwnd = owner
        info.lpVerb = 'runas'
        helper = checked_path(Path(sys._MEIPASS), 'installer-tools/NEXUS-Directory-Helper.exe')
        if not helper.is_file():
            raise OSError('Native directory helper missing')
        info.lpFile = str(helper)
        info.lpParameters = subprocess.list2cmdline([str(directory), sid])
        info.lpDirectory = str(Path(sys.executable).parent)
        info.nShow = 0
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ExecuteInfo)]
        shell.ShellExecuteExW.restype = w.BOOL
        ole = ctypes.WinDLL('ole32')
        ole.CoInitializeEx.argtypes = [ctypes.c_void_p, w.DWORD]
        ole.CoInitializeEx.restype = ctypes.c_long
        initialized = ole.CoInitializeEx(None, 2)
        if initialized not in (0, 1, -2147417850):  # RPC_E_CHANGED_MODE: already initialized
            raise OSError('COM initialization failed')
        try:
            if not shell.ShellExecuteExW(ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if initialized in (0, 1):
                ole.CoUninitialize()
        if not info.hProcess:
            raise OSError('Missing elevated helper handle')
        self.handle = info.hProcess

    def poll(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        result = kernel.WaitForSingleObject(self.handle, 0)
        if result == 258:
            return None
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = w.DWORD()
        try:
            if not kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value
        finally:
            kernel.CloseHandle(self.handle)
            self.handle = None
