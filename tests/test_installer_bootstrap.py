import subprocess
import sys
from pathlib import Path


def test_installer_import_needs_no_launcher_assets(tmp_path):
    source = Path(__file__).resolve().parents[1]
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(source)!r}); "
        f"sys._MEIPASS = {str(tmp_path)!r}; "
        "import nexus_launcher.installer_main; "
        "assert 'nexus_launcher.release_metadata' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=15)
