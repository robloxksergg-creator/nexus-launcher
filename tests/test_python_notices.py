import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import runpy

_module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging/collect_python_notices.py"))
collect = _module["collect"]
metadata = _module["metadata"]


def distribution(root, files):
    return SimpleNamespace(files=files, metadata={'Name': 'example'}, version='1.0',
                           locate_file=lambda entry: root / str(entry))


def test_collect_preserves_text_and_records_hash(monkeypatch, tmp_path):
    (tmp_path / 'LICENSE').write_bytes(b'upstream copyright\n')
    monkeypatch.setattr(metadata, 'distribution', lambda name: distribution(tmp_path, ['LICENSE']))
    result = collect(['example'], tmp_path / 'output')
    entry = result['distributions'][0]['files'][0]
    assert (tmp_path / 'output' / entry['path']).read_bytes() == b'upstream copyright\n'
    assert entry['sha256'] == hashlib.sha256(b'upstream copyright\n').hexdigest()
    assert result['complete_frozen_inventory'] is False


def test_missing_notices_refuse_before_output(monkeypatch, tmp_path):
    monkeypatch.setattr(metadata, 'distribution', lambda name: distribution(tmp_path, ['module.py', '../LICENSE']))
    with pytest.raises(ValueError, match='No license'):
        collect(['example'], tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_existing_output_is_preserved(tmp_path):
    marker = tmp_path / 'original'
    marker.write_bytes(b'keep')
    with pytest.raises(ValueError, match='new directory'):
        collect(['example'], tmp_path)
    assert marker.read_bytes() == b'keep'


@pytest.mark.parametrize('names', [[], ['../secret'], ['example', 'EXAMPLE']])
def test_invalid_input_refuses_without_output(monkeypatch, tmp_path, names):
    (tmp_path / 'LICENSE').write_bytes(b'license')
    monkeypatch.setattr(metadata, 'distribution', lambda name: distribution(tmp_path, ['LICENSE']))
    with pytest.raises(ValueError):
        collect(names, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
