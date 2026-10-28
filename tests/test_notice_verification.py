import hashlib
import json
from pathlib import Path
import runpy

import pytest

verify = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/verify_notices.py'))['verify']


def collection(root, name='LICENSE', digest=None):
    (root / 'LICENSE').write_bytes(b'upstream notice\n')
    entry = {'path': name, 'sha256': digest or hashlib.sha256(b'upstream notice\n').hexdigest()}
    (root / 'inventory.json').write_text(json.dumps({'distributions': [{'files': [entry]}]}))


def test_verifies_bytes_without_granting_clearance(tmp_path):
    collection(tmp_path)
    assert verify(tmp_path) == {'files_verified': 1, 'license_clearance': 'NOT ESTABLISHED'}


def test_tamper_is_rejected(tmp_path):
    collection(tmp_path)
    (tmp_path / 'LICENSE').write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        verify(tmp_path)


def test_bundle_manifest_uses_the_same_byte_checks(tmp_path):
    collection(tmp_path)
    p = tmp_path / 'inventory.json'
    entries = json.loads(p.read_text())['distributions'][0]['files']
    p.write_text(json.dumps({'schema': 1, 'kind': 'notice-bundle', 'files': entries}))
    assert verify(tmp_path)['files_verified'] == 1


def test_rust_collection_checks_each_notice(tmp_path):
    collection(tmp_path)
    p = tmp_path / 'inventory.json'
    entries = json.loads(p.read_text())['distributions'][0]['files']
    p.write_text(json.dumps({'packages': [{'name': 'example', 'notices': entries}]}))
    assert verify(tmp_path)['files_verified'] == 1
    (tmp_path / 'LICENSE').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='checksum'):
        verify(tmp_path)


@pytest.mark.parametrize('name', ['../LICENSE', '/LICENSE', 'C:/LICENSE', 'a\\LICENSE', './LICENSE'])
def test_unsafe_paths_are_rejected(tmp_path, name):
    collection(tmp_path, name)
    with pytest.raises(ValueError):
        verify(tmp_path)


def test_unlisted_content_is_rejected(tmp_path):
    collection(tmp_path)
    (tmp_path / 'unreviewed.txt').write_bytes(b'extra')
    with pytest.raises(ValueError, match='Unlisted'):
        verify(tmp_path)


def test_duplicate_windows_path_is_rejected(tmp_path):
    collection(tmp_path)
    p = tmp_path / 'inventory.json'
    data = json.loads(p.read_text())
    entry = dict(data['distributions'][0]['files'][0], path='license')
    data['distributions'][0]['files'].append(entry)
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Duplicate'):
        verify(tmp_path)
