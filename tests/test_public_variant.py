from pathlib import Path
import runpy

import pytest

prepare = runpy.run_path(str(Path(__file__).parents[1] / 'packaging/prepare_public_variant.py'))['prepare']


def test_variant_changes_only_copied_build_identity_and_excludes_unlisted_secrets(tmp_path):
    source = tmp_path / 'source'
    (source / 'nexus_launcher').mkdir(parents=True)
    (source / 'packaging/metadata').mkdir(parents=True)
    (source / 'assets').mkdir()
    before = 'VERSION = "1.0.1"\nPUBLIC_KEY = "public-fixture"\n'
    (source / 'nexus_launcher/public_update_identity.py').write_text(before)
    for name in ('public_version_info.txt', 'public_bootstrap_version_info.txt'):
        (source / 'packaging/metadata' / name).write_text("filevers=(1, 0, 1, 0)\nStringStruct(u'ProductVersion', u'1.0.1')")
    for name in ('LICENSE', 'COPYRIGHT.md'):
        (source / name).write_text('synthetic fixture')
    (source / '.env').write_text('SYNTHETIC_PRIVATE_FIXTURE')
    result = prepare(source, tmp_path / 'v2', '1.0.2')
    text = (result / 'nexus_launcher/public_update_identity.py').read_text()
    assert 'VERSION = "1.0.2"' in text and 'public-fixture' in text
    assert (source / 'nexus_launcher/public_update_identity.py').read_text() == before
    assert not (result / '.env').exists()
    assert 'filevers=(1, 0, 2, 0)' in (result / 'packaging/metadata/public_version_info.txt').read_text()
    assert "u'1.0.2'" in (result / 'packaging/metadata/public_version_info.txt').read_text()
    with pytest.raises(ValueError):
        prepare(source, result, '1.0.3')


@pytest.mark.parametrize('version', ['1.0', '1.0.2-beta', '../secret', '1.0.2\n'])
def test_invalid_build_version_creates_no_variant(tmp_path, version):
    source = tmp_path / 'source'
    source.mkdir()
    destination = tmp_path / 'variant'
    with pytest.raises(ValueError):
        prepare(source, destination, version)
    assert not destination.exists()
