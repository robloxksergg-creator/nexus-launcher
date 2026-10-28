from pathlib import Path
import runpy
import os
import json
import PySide6

root = Path(SPEC).resolve().parents[2]
qt_root = Path(PySide6.__file__).parent
asset_datas = runpy.run_path(str(root / 'packaging' / 'portable_assets.py'))['asset_datas']
notices = Path(os.environ['NEXUS_CANDIDATE_NOTICES']).resolve()
if not notices.is_dir() or not (notices / 'inventory.json').is_file():
    raise RuntimeError('Candidate notices inventory is required')
# This is a review candidate, not a declaration of complete license compliance.
runpy.run_path(str(root / 'packaging' / 'verify_notices.py'))['verify'](notices)
runtime_names = {
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll",
}
a = Analysis(
    [str(root / "nexus_launcher" / "portable_main.py")], pathex=[str(root)],
    binaries=[(str(qt_root / name), ".") for name in runtime_names if (qt_root / name).is_file()],
    datas=asset_datas(root) + [(str(root / 'LICENSE'), '.'), (str(root / 'COPYRIGHT.md'), '.'), (str(notices), 'third-party-notices')],
    hiddenimports=["_nexus_launcher_core", "tuf", "securesystemslib", "keyring.backends.Windows", "nexus_launcher.nexus_platform.registration", "nexus_launcher.frozen_smoke",
                   "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"],
    runtime_hooks=[str(root / "nexus_launcher" / "pyi_rth_qt_dll_path.py")],
    hookspath=[str(root / "packaging" / "hooks")], hooksconfig={}, excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="NEXUS Launcher", console=False, debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    version=str(root / "packaging" / "metadata" / "version_info.txt"),
    disable_windowed_traceback=False, icon=str(root / "assets" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NEXUS Launcher")
