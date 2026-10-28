from pathlib import Path
root = Path(SPEC).resolve().parents[2]
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    [str(root / "nexus_launcher" / "modern_main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'assets'), 'assets')],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='NexusLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(root / 'assets' / 'icon.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='NexusLauncher',
)
