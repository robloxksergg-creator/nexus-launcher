"""Retain macOS download quarantine; assessment never changes OS policy."""
import errno
import ctypes
from functools import lru_cache
import os
import subprocess
import sys
import time
import uuid

from nexus_launcher.startup_update_flow import OSApprovalRequired

ATTRIBUTE = 'com.apple.quarantine'
MAX_ATTRIBUTE_BYTES = 65536
XATTR_NOFOLLOW = 0x0001


@lru_cache(maxsize=1)
def _libc():
    # Darwin's six-argument ABI differs from Linux; Python exposes no os.*xattr
    # functions on macOS. Load only the platform library, never a search path.
    library = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    arguments = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                 ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    library.getxattr.argtypes = arguments
    library.getxattr.restype = ctypes.c_ssize_t
    library.setxattr.argtypes = arguments
    library.setxattr.restype = ctypes.c_int
    return library


def _path_bytes(path):
    encoded = os.fsencode(path)
    if b'\x00' in encoded:
        raise ValueError('Embedded NUL in attribute path')
    return encoded


def _checked(result):
    if result < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    return result


def _get_attribute(path):
    function = _libc().getxattr
    arguments = (_path_bytes(path), ATTRIBUTE.encode('ascii'))
    size = _checked(function(*arguments, None, 0, 0, XATTR_NOFOLLOW))
    if size > MAX_ATTRIBUTE_BYTES:
        raise OSError(errno.E2BIG, 'Quarantine attribute exceeds bound')
    buffer = ctypes.create_string_buffer(max(size, 1))
    actual = _checked(function(*arguments, buffer, max(size, 1), 0, XATTR_NOFOLLOW))
    if actual != size:
        raise OSError(errno.EAGAIN, 'Quarantine attribute changed while reading')
    return buffer.raw[:actual]


def _set_attribute(path, value):
    if not isinstance(value, bytes) or len(value) > MAX_ATTRIBUTE_BYTES:
        raise ValueError('Invalid quarantine attribute')
    buffer = ctypes.create_string_buffer(value, max(len(value), 1))
    _checked(_libc().setxattr(_path_bytes(path), ATTRIBUTE.encode('ascii'),
                            buffer, len(value), 0, XATTR_NOFOLLOW))


def read(path):
    if sys.platform != 'darwin':
        return None
    try:
        return _get_attribute(path)
    except OSError as error:
        absent = {getattr(errno, 'ENOATTR', 93)}
        if error.errno in absent:
            return None
        raise


def preserve(source, target):
    value = read(source)
    if value is not None:
        _set_attribute(target, value)


def mark_download(path):
    if sys.platform == 'darwin':
        value = ('0081;' + format(int(time.time()), 'x') + ';NEXUS;' + str(uuid.uuid4())).encode('ascii')
        _set_attribute(path, value)


def assess(bundle, environment):
    if read(bundle) is None:
        return
    try:
        subprocess.run(['/usr/sbin/spctl', '--assess', '--type', 'execute', str(bundle)],
                       check=True, capture_output=True, timeout=30, env=environment)
    except (OSError, subprocess.SubprocessError) as error:
        raise OSApprovalRequired('macOS approval required') from error
