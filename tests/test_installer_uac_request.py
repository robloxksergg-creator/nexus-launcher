"""Mock ShellExecuteEx: no real UAC, privileged process or network operation."""
import ctypes
import os
from types import SimpleNamespace
import subprocess
import sys

import pytest
from nexus_launcher import installer_permissions as permissions

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows ctypes ABI')


def test_only_folder_helper_uses_runas_and_owned_handle_is_reaped(monkeypatch, tmp_path):
    sid = 'S-1-5-21-111-222-333-1001'
    directory = tmp_path / 'NEXUS folder'
    calls = []
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    tools = tmp_path / 'installer-tools'
    tools.mkdir()
    (tools / 'NEXUS-Directory-Helper.exe').write_bytes(b'NOT EXECUTABLE; MOCK ONLY')
    monkeypatch.setattr(permissions, 'current_sid', lambda: sid)
    def execute(pointer):
        info = pointer._obj
        calls.append((info.lpVerb, info.lpFile, info.lpParameters, info.hwnd))
        assert info.fMask & 0x40
        info.hProcess = 1234
        return True
    shell = SimpleNamespace(ShellExecuteExW=execute)
    ole = SimpleNamespace(CoInitializeEx=lambda *_: 0, CoUninitialize=lambda: calls.append('COM closed'))
    waits = iter([258, 0])
    def exit_code(handle, output):
        assert handle == 1234
        output._obj.value = 0
        return True
    kernel = SimpleNamespace(WaitForSingleObject=lambda *_: next(waits), GetExitCodeProcess=exit_code,
                             CloseHandle=lambda handle: calls.append(('closed', handle)))
    monkeypatch.setattr(permissions.ctypes, 'WinDLL', lambda name, **_: {'shell32': shell, 'ole32': ole, 'kernel32': kernel}[name])
    request = permissions.PermissionRequest(directory, 77)
    assert calls[0] == ('runas', str(tools / 'NEXUS-Directory-Helper.exe'), subprocess.list2cmdline(
        [str(directory), sid]), 77)
    assert request.poll() is None
    assert request.poll() == 0 and request.handle is None
    assert calls[-1] == ('closed', 1234)
    assert not directory.exists()


def test_uac_cancellation_creates_nothing_and_is_not_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    tools = tmp_path / 'installer-tools'
    tools.mkdir()
    (tools / 'NEXUS-Directory-Helper.exe').write_bytes(b'NOT EXECUTABLE; MOCK ONLY')
    monkeypatch.setattr(permissions, 'current_sid', lambda: 'S-1-5-21-111-222-333-1001')
    calls = []
    def cancelled(_):
        calls.append('requested once')
        ctypes.set_last_error(1223)
        return False
    shell = SimpleNamespace(ShellExecuteExW=cancelled)
    ole = SimpleNamespace(CoInitializeEx=lambda *_: 0, CoUninitialize=lambda: None)
    monkeypatch.setattr(permissions.ctypes, 'WinDLL', lambda name, **_: {'shell32': shell, 'ole32': ole}[name])
    with pytest.raises(OSError) as error:
        permissions.PermissionRequest(tmp_path / 'new', 0)
    assert error.value.winerror == 1223
    assert calls == ['requested once']
    assert not (tmp_path / 'new').exists()
