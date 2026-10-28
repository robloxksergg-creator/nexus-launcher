import hashlib
from pathlib import Path
import runpy

import pytest

inventory = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/candidate_inventory.py'))['inventory']


def test_dotfiles_are_included(tmp_path):
    hidden = tmp_path / '.hidden'
    hidden.mkdir()
    (hidden / 'LICENSE').write_bytes(b'notice')
    result = inventory(tmp_path)
    assert result['files'] == [{'path': '.hidden/LICENSE', 'sha256': hashlib.sha256(b'notice').hexdigest(), 'bytes': 6}]


def test_portable_data_is_rejected(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'user.json').write_bytes(b'synthetic')
    with pytest.raises(ValueError, match='user data'):
        inventory(tmp_path)
