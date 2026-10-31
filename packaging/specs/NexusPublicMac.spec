"""Apple Silicon review bundle. Ad-hoc signing is not Apple notarization."""
from pathlib import Path
import os
import platform
import runpy
import sys

if sys.platform != 'darwin' or platform.machine() != 'arm64':
    raise RuntimeError('Build on a native Apple Silicon macOS runner')
root = Path(SPEC).resolve().parents[2]
notices = Path(os.environ['NEXUS_CANDIDATE_NOTICES']).resolve()
runpy.run_path(str(root / 'packaging/verify_notices.py'))['verify'](notices)
asset_datas = runpy.run_path(str(root / 'packaging/portable_assets.py'))['asset_datas']
a = Analysis(
    [str(root / 'nexus_launcher/macos_main.py')], pathex=[str(root)], binaries=[],
    datas=asset_datas(root) + [(str(root / 'LICENSE'), '.'), (str(root / 'COPYRIGHT.md'), '.'),
                             (str(notices), 'third-party-notices')],
    hiddenimports=['_nexus_launcher_core', 'keyring.backends.macOS',
                   'nexus_launcher.nexus_platform.registration',
                   'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets'],
    hookspath=[str(root / 'packaging/hooks')], hooksconfig={}, runtime_hooks=[],
    excludes=['nexus_launcher.windows_bootstrap_process', 'nexus_launcher.online_installer_main'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NEXUS Launcher',
          console=False, debug=False, strip=False, upx=False, target_arch='arm64',
          codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name='NEXUS-macOS-arm64', strip=False, upx=False)
app = BUNDLE(coll, name='NEXUS Launcher.app', icon=str(root / 'assets/icon.icns'),
             bundle_identifier='com.forcecore.nexus.launcher', info_plist={
                 'CFBundleDisplayName': 'NEXUS Launcher',
                 'CFBundleShortVersionString': '1.0.2', 'CFBundleVersion': '102',
                 'LSMinimumSystemVersion': '15.0', 'NSHighResolutionCapable': True,
                 'LSApplicationCategoryType': 'public.app-category.games',
             })
