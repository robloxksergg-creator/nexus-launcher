"""Register packaged Qt DLL directories before PySide6 imports QtCore."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32" and getattr(sys, "frozen", False):
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    dll_dirs = [root, root / "PySide6", root / "shiboken6"]
    existing = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(str(path) for path in dll_dirs) + os.pathsep + existing
    handles = []
    if hasattr(os, "add_dll_directory"):
        for path in dll_dirs:
            if path.is_dir():
                handles.append(os.add_dll_directory(str(path)))
    # Keep directory handles alive for the lifetime of the frozen process.
    sys._nexus_qt_dll_handles = handles
