"""Native Linux build only. No Windows bootstrap or update channel."""
from pathlib import Path
import os
import runpy
import sys

if not sys.platform.startswith('linux'):
    raise RuntimeError('Build this package on Linux')
root = Path(SPEC).resolve().parents[2]
notices = Path(os.environ['NEXUS_CANDIDATE_NOTICES']).resolve()
runpy.run_path(str(root / 'packaging/verify_notices.py'))['verify'](notices)
asset_datas = runpy.run_path(str(root / 'packaging/portable_assets.py'))['asset_datas']
a = Analysis(
    [str(root / 'nexus_launcher/linux_main.py')], pathex=[str(root)],
    binaries=[],
    datas=asset_datas(root) + [(str(root / 'LICENSE'), '.'),
           (str(root / 'COPYRIGHT.md'), '.'), (str(notices), 'third-party-notices')],
    hiddenimports=['_nexus_launcher_core', 'keyring.backends.SecretService',
                   'keyring.backends.kwallet', 'nexus_launcher.nexus_platform.registration',
                   'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets'],
    hookspath=[str(root / 'packaging/hooks')], hooksconfig={},
    runtime_hooks=[], excludes=['nexus_launcher.windows_bootstrap_process',
                                'nexus_launcher.online_installer_main'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='nexus-launcher',
          console=False, debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='NEXUS-Linux-x64', strip=False, upx=False)
