import hashlib
import json
from pathlib import Path
import runpy
import zipfile

import pytest

repack = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/repack_review_candidate.py'))['repack']


def fixture(tmp_path):
    source = tmp_path / 'ci.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('NEXUS Launcher/NEXUS Launcher.exe', b'synthetic bytes, never executed')
        z.writestr('NEXUS Launcher/_internal/COPYRIGHT.md', b'old attribution')
    notices = tmp_path / 'notices'
    notices.mkdir()
    (notices / 'LICENSE').write_bytes(b'upstream notice')
    (notices / 'inventory.json').write_text(json.dumps({'schema': 1, 'kind': 'notice-bundle', 'files': [{'path': 'LICENSE', 'sha256': hashlib.sha256(b'upstream notice').hexdigest()}]}))
    copyright_file = tmp_path / 'copyright.md'
    copyright_file.write_bytes(b'owner-approved attribution')
    return source, notices, copyright_file


def test_repack_preserves_executable_bytes_without_executing(tmp_path):
    source, notices, copyright_file = fixture(tmp_path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / 'review.zip'
    result = repack(source, digest, notices, copyright_file, output)
    assert result['exe_sha256'] == hashlib.sha256(b'synthetic bytes, never executed').hexdigest()
    with zipfile.ZipFile(output) as z:
        assert z.read('NEXUS Launcher/_internal/COPYRIGHT.md') == b'owner-approved attribution'
        assert z.read('NEXUS Launcher/_internal/third-party-notices/LICENSE') == b'upstream notice'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert result['signing'] == 'NOT SIGNED'


def test_wrong_parent_hash_creates_no_output(tmp_path):
    source, notices, copyright_file = fixture(tmp_path)
    with pytest.raises(ValueError, match='checksum'):
        repack(source, '0' * 64, notices, copyright_file, tmp_path / 'review.zip')
    assert not (tmp_path / 'review.zip').exists()
