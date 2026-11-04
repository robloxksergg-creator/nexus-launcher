import hashlib
import threading
import urllib.error

import pytest
from nexus_launcher.curseforge_importer import CurseForgeImporter
from nexus_launcher.updater import ModpackUpdater, PackFile, PackRelease


def test_curseforge_jobs_use_private_paths_and_merge_after_all_downloads(tmp_path, monkeypatch):
    importer = CurseForgeImporter(tmp_path/'instance', 'fixture')
    barrier = threading.Barrier(2)
    def download(root, reference):
        root.mkdir(parents=True)
        path = root/f"{reference['fileID']}.jar"
        path.write_bytes(b'synthetic verified bytes')
        barrier.wait(timeout=3)
        assert not (tmp_path/'stage/mods').exists()
        return {'path':'mods/'+path.name,'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    monkeypatch.setattr(importer, '_download_mod', download)
    records=importer._stage_downloads(tmp_path/'stage',[{'fileID':1},{'fileID':2}],3)
    assert [r['path'] for r in records] == ['mods/1.jar','mods/2.jar']
    assert all((tmp_path/'stage'/r['path']).is_file() for r in records)
    assert not (tmp_path/'instance').exists()


def test_curseforge_collision_does_not_overwrite_or_merge(tmp_path, monkeypatch):
    importer = CurseForgeImporter(tmp_path/'instance', 'fixture')
    def download(root, reference):
        root.mkdir(parents=True)
        (root/'same.jar').write_bytes(b'verified')
        return {'path':'mods/same.jar'}
    monkeypatch.setattr(importer, '_download_mod', download)
    with pytest.raises(ValueError, match='одинаковый путь'):
        importer._stage_downloads(tmp_path/'stage',[{},{}],3)
    assert not (tmp_path/'stage/mods').exists()


def test_updater_never_applies_when_one_parallel_file_fails(tmp_path, monkeypatch):
    updater=ModpackUpdater(tmp_path/'instance')
    entries=tuple(PackFile(str(i),f'{i}.jar','1',f'mods/{i}.jar','https://github.com/file',4,hashlib.sha256(b'good').hexdigest(),True,'mod') for i in range(2))
    release=PackRelease('1','','',files=entries)
    def transfer(entry, path, transferred, total, *, emit=None):
        if entry.id == '1': raise ValueError('synthetic hash mismatch')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'good')
        emit('verifying',entry.path,4,4)
        return 4
    monkeypatch.setattr(updater,'_download_file',transfer)
    monkeypatch.setattr(updater,'_write_transaction',lambda *_:pytest.fail('applied before verification'))
    with pytest.raises(ValueError,match='hash mismatch'): updater._sync_files(release)
    assert not (tmp_path/'instance/mods').exists()


def test_rate_limit_does_not_cause_automatic_retry_storm(tmp_path, monkeypatch):
    from nexus_launcher import updater as module
    calls=[]
    def opened(*_, **__):
        calls.append(True)
        raise urllib.error.HTTPError('https://github.com/file',429,'rate limited',{},None)
    monkeypatch.setattr(module,'open_https',opened)
    entry=PackFile('a','a.jar','1','mods/a.jar','https://github.com/file',4,hashlib.sha256(b'good').hexdigest(),True,'mod')
    updater=ModpackUpdater(tmp_path/'instance')
    with pytest.raises(ConnectionError,match='HTTP_429'):
        updater._download_file(entry,tmp_path/'stage/a.part',[0],4)
    assert calls == [True]
