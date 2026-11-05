"""Retain macOS download quarantine; assessment never changes OS policy."""
import errno
import os
import subprocess
import sys
import time
import uuid

from nexus_launcher.startup_update_flow import OSApprovalRequired

ATTRIBUTE = 'com.apple.quarantine'


def read(path):
    if sys.platform != 'darwin':
        return None
    try:
        return os.getxattr(path, ATTRIBUTE, follow_symlinks=False)
    except OSError as error:
        absent = {getattr(errno, 'ENODATA', -1), getattr(errno, 'ENOATTR', -2)}
        if error.errno in absent:
            return None
        raise


def preserve(source, target):
    value = read(source)
    if value is not None:
        os.setxattr(target, ATTRIBUTE, value, follow_symlinks=False)


def mark_download(path):
    if sys.platform == 'darwin':
        value = ('0081;' + format(int(time.time()), 'x') + ';NEXUS;' + str(uuid.uuid4())).encode('ascii')
        os.setxattr(path, ATTRIBUTE, value, follow_symlinks=False)


def assess(bundle, environment):
    if read(bundle) is None:
        return
    try:
        subprocess.run(['/usr/sbin/spctl', '--assess', '--type', 'execute', str(bundle)],
                       check=True, capture_output=True, timeout=30, env=environment)
    except (OSError, subprocess.SubprocessError) as error:
        raise OSApprovalRequired('macOS approval required') from error
