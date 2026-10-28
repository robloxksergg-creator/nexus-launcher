from pathlib import Path
root = Path(SPEC).resolve().parents[2]
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    [str(root / "nexus_launcher" / "modern_main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'assets'), 'assets')],
    hiddenimports=['keyring.backends.macOS'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NEXUS Launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='macos/entitlements.plist',
    icon=str(root / 'assets' / 'icon.icns'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='NEXUS Launcher')
app = BUNDLE(
    coll,
    name='NEXUS Launcher.app',
    icon=str(root / 'assets' / 'icon.icns'),
    bundle_identifier='com.forcecore.nexus.launcher',
    info_plist={
        'CFBundleDisplayName': 'NEXUS Launcher',
        'CFBundleName': 'NEXUS Launcher',
        'CFBundleShortVersionString': '0.9.6',
        'CFBundleVersion': '96',
        'LSMinimumSystemVersion': '12.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.games',
    },
)
