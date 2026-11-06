import hashlib
import json
import pytest
from nexus_launcher.updater import ModpackUpdater


def installed(tmp_path):
    (tmp_path/'mods').mkdir()
    (tmp_path/'mods/a.jar').write_bytes(b'approved')
    state=tmp_path/'.nexus-launcher'
    state.mkdir()
    (state/'pack.json').write_text(json.dumps({'last_successful_update':1,'managed_files':{'mods/a.jar':hashlib.sha256(b'approved').hexdigest()}}))
    return ModpackUpdater(tmp_path)


def test_verified_repeat_launch_preserves_unmanaged_data(tmp_path):
    updater=installed(tmp_path)
    (tmp_path/'options.txt').write_text('changed settings')
    (tmp_path/'saves').mkdir()
    (tmp_path/'saves/world').write_bytes(b'world')
    assert updater.offline_launch_report()=={'ready':True,'reason':'VERIFIED','missing':[],'changed':[]}
    assert updater.can_launch_offline()
    assert (tmp_path/'saves/world').read_bytes()==b'world'


@pytest.mark.parametrize('damage',['missing','changed'])
def test_damaged_managed_file_is_identified_without_repair(tmp_path,damage):
    updater=installed(tmp_path)
    path=tmp_path/'mods/a.jar'
    if damage=='missing':path.unlink()
    else:path.write_bytes(b'changed')
    report=updater.offline_launch_report()
    assert not report['ready'] and report['reason']=='FILES_CHANGED'
    assert report[damage]==['mods/a.jar']
    assert not updater.can_launch_offline()
    assert path.exists()==(damage=='changed')


def test_unfinished_transaction_never_allows_cached_launch(tmp_path):
    updater=installed(tmp_path)
    (tmp_path/'.nexus-launcher/file-transaction').mkdir()
    assert updater.offline_launch_report()['reason']=='INCOMPLETE_INSTALL'
    assert not updater.can_launch_offline()


def test_corrupt_inventory_has_specific_fail_closed_reason(tmp_path):
    updater=installed(tmp_path)
    (tmp_path/'.nexus-launcher/pack.json').write_text('{')
    assert updater.offline_launch_report()['reason']=='INVENTORY_OR_READ_ERROR'
    assert not updater.can_launch_offline()
