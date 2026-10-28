# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
root = Path(SPEC).resolve().parents[2]
import PySide6

qt_root = Path(PySide6.__file__).parent
qt_runtime_names = {
    'concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
    'msvcp140_codecvt_ids.dll', 'vcruntime140.dll', 'vcruntime140_1.dll',
}
qt_runtime_binaries = [
    (str(qt_root / name), '.') for name in qt_runtime_names if (qt_root / name).is_file()
]

a = Analysis(
    [str(root / "nexus_launcher" / "stable_main.py")],
    pathex=[str(root)],
    binaries=qt_runtime_binaries,
    datas=[(str(root / 'assets'), 'assets')],
    hiddenimports=[
        'nexus_launcher.modern_main',
        'nexus_launcher.nexus_platform',
        'nexus_launcher.nexus_platform.config',
        'nexus_launcher.nexus_platform.models',
        'nexus_launcher.nexus_platform.widgets',
        'nexus_launcher.nexus_platform.pages',
        'nexus_launcher.nexus_platform.window',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "nexus_launcher" / "pyi_rth_qt_dll_path.py")],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NEXUS-Launcher-1.0.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=['Qt6*.dll', 'PySide6/*.dll', 'shiboken6/*.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(root / 'assets' / 'icon.ico')],
    version=str(root / 'packaging' / 'metadata' / 'version_info.txt'),
)
