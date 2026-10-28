"""Preserve the build interpreter's supplemental SSL rejection policy.

Some build runtimes load this public PEM next to ssl.py. Frozen ssl.__file__
resolves inside _MEIPASS, so the same file must accompany the frozen module.
Do not remove the ssl.py policy or substitute a different certificate bundle.
"""
from pathlib import Path

from PyInstaller.utils.hooks import get_module_file_attribute

source = Path(get_module_file_attribute("ssl"))
policy = source.with_name("codex-rejected-cas.pem")
datas = []
if policy.is_file():
    datas.append((str(policy), "."))
elif "codex-rejected-cas.pem" in source.read_text(encoding="utf-8"):
    raise RuntimeError("Build interpreter SSL policy file is missing")
