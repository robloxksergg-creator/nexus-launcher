from pathlib import Path
import runpy

import pytest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/portable_assets.py'))


def test_real_candidate_excludes_retired_worlds_and_previews():
    root = Path(__file__).resolve().parents[1]
    entries = MODULE['asset_datas'](root)
    names = {Path(source).name for source, target in entries}
    assert not names.intersection(MODULE['RETIRED_ASSETS'])
    assert {'gearmorph-official.png', 'gearmorph-world-art.png', 'icon.ico', 'screens.js'} <= names
    assert all('/previews/' not in Path(source).as_posix() for source, target in entries)
    assert all(Path(source).is_file() for source, target in entries)


def test_unreviewed_file_type_fails_closed(tmp_path):
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'private.pfx').write_bytes(b'synthetic')
    with pytest.raises(ValueError, match='Unreviewed'):
        MODULE['asset_datas'](tmp_path)


def test_selection_keeps_original_retired_resources(tmp_path):
    assets = tmp_path / 'assets'
    assets.mkdir()
    retired = assets / 'elderfall-fabric-pack.zip'
    retired.write_bytes(b'synthetic-original')
    assert MODULE['asset_datas'](tmp_path) == []
    assert retired.read_bytes() == b'synthetic-original'
