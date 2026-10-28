# Separate acceptance build; never invokes stable_main or private staging identity.
from pathlib import Path

import PySide6
import os

root = Path(SPEC).resolve().parents[2]
qt_root = Path(PySide6.__file__).parent
runtime_names = {
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll",
}
a = Analysis(
    [str(root / "nexus_launcher" / "tester_main.py")], pathex=[str(root)],
    binaries=[(str(qt_root / name), ".") for name in runtime_names if (qt_root / name).is_file()],
    datas=[(str(Path(os.environ["NEXUS_TESTER_ASSET_ROOT"])), "assets")],
    hiddenimports=["keyring.backends.Windows", "nexus_launcher.nexus_platform.registration", "nexus_launcher.frozen_smoke",
                   "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"],
    runtime_hooks=[str(root / "nexus_launcher" / "pyi_rth_qt_dll_path.py")],
    hookspath=[], hooksconfig={}, excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="NexusLauncher", console=False, debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    runtime_tmpdir=None, disable_windowed_traceback=True,
    icon=str(root / "assets" / "icon.ico"), version=os.environ["NEXUS_TESTER_VERSION_INFO"],
)
