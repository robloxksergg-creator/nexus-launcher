"""Installer destinations; no implicit overwrite or privilege escalation."""
from pathlib import Path
import sys


def default_directory(executable=None):
    # A dedicated sibling directory keeps unrelated Downloads/Desktop files out
    # of the installation and preserves the user's selected drive.
    return Path(executable or sys.executable).absolute().parent / 'NEXUS Launcher'
