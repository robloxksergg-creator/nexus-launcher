"""Local migration regression guard: protected source matches except package imports."""
from pathlib import Path
import os
import re

import pytest

BASELINE = Path(os.environ.get("NEXUS_MIGRATION_BASELINE", "E:/nexus-work/work/rc-1.0.0-rc.1-source"))
PROTECTED = (
    "launcher_core.py", "loader_providers.py", "nexus_account.py", "secure_http.py",
    "updater.py", "signed_release.py", "self_update.py", "build_file_manifest.py",
    "runtime_settings.py", "projects.py", "user_instances.py", "assets/release.json",
)


def normalize_import_paths(source: str) -> str:
    lines = []
    for line in source.splitlines(keepends=True):
        if line.lstrip().startswith(("import ", "from ")):
            line = re.sub(
                r"\bimport nexus_launcher\.([A-Za-z_]\w*) as \1\b",
                r"import \1",
                line,
            )
            line = line.replace("nexus_launcher.nexus_platform.", "nexus_platform.")
            line = line.replace("nexus_launcher.", "")
        lines.append(line)
    return "".join(lines)


@pytest.mark.parametrize("relative", PROTECTED)
def test_protected_migration_source_matches_baseline(relative):
    if not BASELINE.is_dir():
        pytest.skip("Local audited baseline is unavailable")
    root = Path(__file__).resolve().parents[1]
    candidate = root / ("nexus_launcher" if relative.endswith(".py") else "") / relative
    current = normalize_import_paths(candidate.read_text(encoding="utf-8"))
    baseline = normalize_import_paths((BASELINE / relative).read_text(encoding="utf-8"))
    assert current == baseline, relative
