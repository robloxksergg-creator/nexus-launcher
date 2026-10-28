import hashlib
import io
from pathlib import Path
import runpy
import tarfile

import pytest

collect = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/collect_locked_rust_notices.py'))['collect_locked']


def fixture(tmp_path, version='1.0.0'):
    cache = tmp_path / 'cache'
    cache.mkdir()
    prefix = 'example-' + version
    path = cache / (prefix + '.crate')
    with tarfile.open(path, 'w:gz') as archive:
        info = tarfile.TarInfo(prefix + '/LICENSE')
        info.size = len(b'upstream notice')
        archive.addfile(info, io.BytesIO(b'upstream notice'))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lock = tmp_path / 'Cargo.lock'
    lock.write_text('[[package]]\nname="example"\nversion="' + version + '"\nsource="registry+https://github.com/rust-lang/crates.io-index"\nchecksum="' + digest + '"\n')
    return cache, path, lock


def test_uses_exact_cached_source_without_network(tmp_path):
    cache, path, lock = fixture(tmp_path)
    result = collect(lock, [cache], tmp_path / 'output')
    assert result['registry_archives_verified'] == 1
    assert (tmp_path / 'output/example-1.0.0/LICENSE').read_bytes() == b'upstream notice'
    assert result['license_clearance'] == 'NOT ESTABLISHED'


def test_tampered_cache_refuses_before_output(tmp_path):
    cache, path, lock = fixture(tmp_path)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        collect(lock, [cache], tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_missing_cache_refuses_before_output(tmp_path):
    cache, path, lock = fixture(tmp_path)
    path.unlink()
    with pytest.raises(ValueError, match='Missing'):
        collect(lock, [cache], tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_semver_build_metadata_is_supported(tmp_path):
    cache, path, lock = fixture(tmp_path, '1.0.0+build')
    result = collect(lock, [cache], tmp_path / 'output')
    assert result['registry_archives_verified'] == 1
    assert (tmp_path / 'output/example-1.0.0+build/LICENSE').is_file()
