from pathlib import Path

from nexus_launcher.portable_main import portable_data_root


def test_portable_root_is_adjacent_to_exe_and_not_temporary(monkeypatch, tmp_path):
    executable = tmp_path / 'NEXUS' / 'NEXUS.exe'
    monkeypatch.setattr('sys.executable', str(executable))
    assert portable_data_root() == executable.parent / 'data'
    assert portable_data_root() != Path('C:/Users/user/AppData/Local/Temp')
