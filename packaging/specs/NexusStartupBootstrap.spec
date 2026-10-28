# Stable bootstrap component. No initial package or live feed is implicitly added.
# Release packaging must add verified initial-package.zip + initial-envelope.json.
from pathlib import Path
root = Path(SPEC).resolve().parents[2]
a = Analysis([str(root / "nexus_launcher" / "startup_bootstrap_main.py")], pathex=[str(root)],
             datas=[(str(root/'assets/release.json'), 'assets'),
                    (str(root/'assets/tester-release.json'), 'assets'),
                    (str(root/'assets/bootstrap-release.json'), 'assets')],
             # Public v2 anchor is compiled into PYZ, never runtime JSON trust.
             # Phase 2 anchor is intentionally unprovisioned; legacy startup stays unchanged.
             binaries=[], hiddenimports=['nexus_launcher.update_v2_anchor', 'nexus_launcher.update_v2_trust'], hookspath=[], runtime_hooks=[],
             excludes=['nexus_launcher.nexus_platform.window', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore'],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NEXUS',
          console=False, debug=False, strip=False, upx=False,
          disable_windowed_traceback=True, icon=str(root / "assets" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name='NEXUS-Bootstrap-Component', strip=False, upx=False)
