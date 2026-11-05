import hashlib
import io
from pathlib import Path
import runpy
import tarfile

import pytest

collect = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/collect_source_notices.py'))['collect']


def archive(tmp_path, entries):
    path = tmp_path / 'source.tar.xz'
    with tarfile.open(path, 'w:xz') as target:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            target.addfile(info, io.BytesIO(content))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_preserves_notice_bytes_without_copying_source(tmp_path):
    path, digest = archive(tmp_path, [('src/LICENSE', b'upstream\n'), ('src/code.py', b'not executed'), ('src/LICENSE-check.py', b'not executed')])
    result = collect(path, digest, tmp_path / 'output', 'src')
    assert result['files'] == [{'path': 'LICENSE', 'sha256': hashlib.sha256(b'upstream\n').hexdigest()}]
    assert (tmp_path / 'output/LICENSE').read_bytes() == b'upstream\n'
    assert not (tmp_path / 'output/code.py').exists()


def test_checksum_failure_creates_no_output(tmp_path):
    path, _ = archive(tmp_path, [('src/LICENSE', b'notice')])
    with pytest.raises(ValueError, match='checksum'):
        collect(path, '0' * 64, tmp_path / 'output', 'src')
    assert not (tmp_path / 'output').exists()


def test_spdx_text_in_licenses_directory_is_kept(tmp_path):
    path, digest = archive(tmp_path, [('src/LICENSES/MIT.txt', b'full license'), ('src/LICENSES/helper.py', b'not a license')])
    result = collect(path, digest, tmp_path / 'output', 'src')
    assert len(result['files']) == 1
    assert result['files'][0]['path'] == 'LICENSES/MIT.txt'


def test_license_checker_shim_is_not_a_license(tmp_path):
    path, digest = archive(tmp_path, [('src/LICENSE-MIT', b'license'), ('src/node_modules/.bin/license-checker', b'executable shim')])
    result = collect(path, digest, tmp_path / 'output', 'src')
    assert [entry['path'] for entry in result['files']] == ['LICENSE-MIT']


@pytest.mark.parametrize('name', ['src/../LICENSE', '/src/LICENSE', 'other/LICENSE'])
def test_source_paths_cannot_escape_prefix(tmp_path, name):
    path, digest = archive(tmp_path, [(name, b'notice')])
    with pytest.raises(ValueError, match='Unsafe'):
        collect(path, digest, tmp_path / 'output', 'src')
    assert not (tmp_path / 'output').exists()


def test_windows_case_collision_is_rejected(tmp_path):
    path, digest = archive(tmp_path, [('src/LICENSE', b'one'), ('src/license', b'two')])
    with pytest.raises(ValueError, match='collision'):
        collect(path, digest, tmp_path / 'output', 'src')
    assert not (tmp_path / 'output').exists()


def test_deep_notice_paths_are_shortened_without_losing_bytes_or_provenance(tmp_path):
    relative = 'node_modules/' * 14 + 'dependency/LICENSE'
    content = b'Original upstream license\r\nCopyright fixture\n'
    path, digest = archive(tmp_path, [('src/' + relative, content), ('src/LICENSE', b'root')])
    output = tmp_path / 'output'
    result = collect(path, digest, output, 'src')
    entry = next(e for e in result['files'] if e.get('source_path') == relative)
    assert len(entry['path']) <= 80
    assert (output / entry['path']).read_bytes() == content
    assert entry['sha256'] == hashlib.sha256(content).hexdigest()
    verify = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/verify_notices.py'))['verify']
    assert verify(output)['files_verified'] == 2
