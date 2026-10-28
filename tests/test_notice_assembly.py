import hashlib
import json
from pathlib import Path
import runpy

import pytest

assemble = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/assemble_notice_bundle.py'))['assemble']


def group(path):
    path.mkdir()
    (path / 'LICENSE').write_bytes(b'original notice')
    entry = {'path': 'LICENSE', 'sha256': hashlib.sha256(b'original notice').hexdigest()}
    (path / 'inventory.json').write_text(json.dumps({'schema': 1, 'kind': 'notice-bundle', 'files': [entry]}))
    return path


def test_combines_without_overwriting_sources(tmp_path):
    source = group(tmp_path / 'source')
    result = assemble([('python', source)], tmp_path / 'output')
    assert len(result['files']) == 2
    assert (tmp_path / 'output/python/LICENSE').read_bytes() == b'original notice'
    assert (source / 'LICENSE').read_bytes() == b'original notice'
    assert result['license_clearance'] == 'NOT ESTABLISHED'


def test_bad_input_creates_no_output(tmp_path):
    source = group(tmp_path / 'source')
    (source / 'LICENSE').write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        assemble([('python', source)], tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_duplicate_group_is_rejected(tmp_path):
    source = group(tmp_path / 'source')
    with pytest.raises(ValueError, match='duplicate'):
        assemble([('python', source), ('python', source)], tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
