"""No UAC prompts or existing-folder ACL changes in automated tests."""
import os
from pathlib import Path
import pytest

from nexus_launcher.installer_location import default_directory
from nexus_launcher.installer_permissions import validate_request

SID = 'S-1-5-21-111-222-333-1001'


def test_default_is_a_dedicated_sibling_not_downloads_itself(tmp_path):
    executable = tmp_path / 'Downloads' / 'NEXUS-Setup.exe'
    assert default_directory(executable) == executable.parent / 'NEXUS Launcher'


@pytest.mark.parametrize('sid', ['S-1-1-0', 'S-1-5-18', SID + ' /T', '', 'Everyone'])
def test_broad_or_injected_sids_are_rejected(tmp_path, sid):
    with pytest.raises(ValueError):
        validate_request(tmp_path / 'new', sid)
    assert not (tmp_path / 'new').exists()


def test_existing_directories_volume_roots_and_missing_parents_are_refused(tmp_path):
    old = tmp_path / 'existing'
    old.mkdir()
    sentinel = old / 'player-data'
    sentinel.write_bytes(b'PRESERVE')
    for directory in [old, Path(tmp_path.anchor), Path('relative'), tmp_path / 'missing' / 'new']:
        with pytest.raises(ValueError):
            validate_request(directory, SID)
    assert sentinel.read_bytes() == b'PRESERVE'
    assert validate_request(tmp_path / 'new', SID) == tmp_path / 'new'


@pytest.mark.skipif(os.name != 'nt' or not os.environ.get('NEXUS_PERMISSION_HELPER'), reason='Built native Windows directory helper required')
def test_native_prepare_only_new_owned_directory(tmp_path):
    from nexus_launcher.installer_permissions import current_sid
    import subprocess
    sid = current_sid()
    directory = tmp_path / 'new-NEXUS'
    subprocess.run([os.environ['NEXUS_PERMISSION_HELPER'], str(directory), sid], check=True, timeout=30)
    (directory / 'write-probe').write_bytes(b'OWNED TEST FILE')
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run([os.environ['NEXUS_PERMISSION_HELPER'], str(directory), sid], check=True, timeout=30)
    assert (directory / 'write-probe').read_bytes() == b'OWNED TEST FILE'
