"""Consistent child-process policy for a GUI launcher."""
from __future__ import annotations

import re
import subprocess
import sys


GAME_ENVIRONMENT_KEYS = frozenset({
    'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'TMPDIR',
    'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'HOME', 'APPDATA', 'LOCALAPPDATA',
    'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432',
    'ALLUSERSPROFILE', 'PUBLIC', 'USERNAME', 'USERDOMAIN', 'OS',
    'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS',
    'LANG', 'LANGUAGE', 'LC_ALL', 'LC_CTYPE', 'DISPLAY', 'WAYLAND_DISPLAY',
    'XAUTHORITY', 'XDG_RUNTIME_DIR', 'XDG_SESSION_TYPE', 'DBUS_SESSION_BUS_ADDRESS',
})



def _runtime_policy():
    # Bootstrap callers importing hidden_process_kwargs do not load the extension.
    from nexus_launcher.native_transfer import _native
    if _native is not None and hasattr(_native, "LAUNCH_POLICY_API_VERSION"):
        if _native.LAUNCH_POLICY_API_VERSION != 1:
            raise ImportError("Incompatible NEXUS launch policy API")
        return _native
    return None


def launch_username_valid(value):
    native = _runtime_policy()
    if native is not None:
        return native.launch_username_valid(value)
    return bool(re.fullmatch(r"[A-Za-z0-9_]{3,16}", value))


def redact_launch_command(command):
    native = _runtime_policy()
    if native is not None:
        return native.launch_redact_command(command)
    return [
        "-Dnexus.gameTicket=<redacted>"
        if part.startswith("-Dnexus.gameTicket=")
        else "<access-token>"
        if index and command[index - 1] in {"--accessToken", "--clientId"}
        else part
        for index, part in enumerate(command)
    ]


def game_environment(source, ticket=''):
    """Do not expose launcher/service credentials or JVM injection variables to mods."""
    native = _runtime_policy()
    if native is None:
        result = {key: source[key] for key in source if key.upper() in GAME_ENVIRONMENT_KEYS}
    else:
        keys = list(source)
        mask = native.launch_environment_mask([key.upper() for key in keys])
        if len(mask) != len(keys) or any(type(value) is not bool for value in mask):
            raise ValueError("Invalid native environment policy result")
        result = {key: source[key] for key, allowed in zip(keys, mask) if allowed}
    if ticket:
        result['NEXUS_GAME_TICKET'] = ticket
    return result


def hidden_process_kwargs(additional_flags: int = 0) -> dict:
    """Prevent transient console windows for non-interactive Windows children."""
    if sys.platform != "win32":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW | additional_flags,
        "startupinfo": startup,
    }
