# Single EXE, no embedded launcher ZIP, no UAC elevation request.
from pathlib import Path
import os,runpy
root=Path(SPEC).resolve().parents[2]
notices=Path(os.environ['NEXUS_CANDIDATE_NOTICES']).resolve()
runpy.run_path(str(root/'packaging/verify_notices.py'))['verify'](notices)
a=Analysis([str(root/'nexus_launcher/online_installer_main.py')],pathex=[str(root)],
 datas=[(str(root/'assets/release.json'),'assets'),(str(root/'assets/icon.ico'),'assets'),(str(root/'assets/nexus-mark.svg'),'assets'),(str(root/'LICENSE'),'.'),(str(root/'COPYRIGHT.md'),'.'),(str(notices),'third-party-notices')],
 binaries=[],hiddenimports=['nexus_launcher.github_updates','nexus_launcher.public_update_identity'],hookspath=[str(root/'packaging/hooks')],runtime_hooks=[],
 excludes=['PySide6.QtWebEngineWidgets','PySide6.QtWebEngineCore','PySide6.QtMultimedia'],noarchive=False,optimize=0)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='NEXUS-Setup',console=False,debug=False,strip=False,upx=False,uac_admin=False,
 disable_windowed_traceback=True,version=str(root/'packaging/metadata/public_bootstrap_version_info.txt'),icon=str(root/'assets/icon.ico'))
