from pathlib import Path
import PySide6

root = Path(SPEC).resolve().parents[2]
qt_root = Path(PySide6.__file__).parent
runtime_names = {
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll",
}
a = Analysis(
    [str(root / "nexus_launcher" / "portable_main.py")], pathex=[str(root)],
    binaries=[(str(qt_root / name), ".") for name in runtime_names if (qt_root / name).is_file()],
    datas=[(str(root / "assets"), "assets")],
    hiddenimports=["keyring.backends.Windows", "nexus_launcher.nexus_platform.registration", "nexus_launcher.frozen_smoke",
                   "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"],
    runtime_hooks=[str(root / "nexus_launcher" / "pyi_rth_qt_dll_path.py")],
    hookspath=[], hooksconfig={}, excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="NEXUS-2.0-Portable-v23", console=False, debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    disable_windowed_traceback=False, icon=str(root / "assets" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NEXUS-2.0-Portable-v23")


