import io
import hashlib
import time
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from nexus_launcher.mod_batch import resolve_exact
from nexus_launcher.modrinth_provider import ModrinthProvider,ModInstaller,ProviderError
from nexus_launcher.user_instances import InstalledMod
from tests.test_next_shell import candidate  # noqa: F401
from tests.test_mod_media import png


@pytest.mark.parametrize('enabled',[True,False])
def test_exact_selection_not_latest_and_sha_verified_replacement(candidate,monkeypatch,enabled):
    app,window,_=candidate
    service=window.instance_service;instance=service.create('Version swap','1.21.1','fabric','0.16.10');root=service.path_for(instance.id)
    directory='mods' if enabled else 'disabled_mods'
    (root/directory/'old.jar').write_bytes(b'old')
    instance.installed_mods=[InstalledMod('mod','old','Old','old.jar','0'*128,enabled)];service.save(instance)
    data=b'new verified fixture';version={'id':'chosen','project_id':'mod','name':'Chosen','loaders':['fabric'],'game_versions':['1.21.1'],'dependencies':[],'files':[{'filename':'chosen.jar','url':'https://cdn.modrinth.com/data/mod/chosen.jar','hashes':{'sha512':hashlib.sha512(data).hexdigest()},'size':len(data)}]}
    provider=ModrinthProvider();monkeypatch.setattr(provider,'version',lambda key:version)
    plan=resolve_exact(provider,'mod','chosen','1.21.1','fabric')
    monkeypatch.setattr('nexus_launcher.modrinth_provider.open_https',lambda *a,**k:io.BytesIO(data))
    ModInstaller(service,provider).install(instance.id,'mod',resolved_versions=plan)
    assert service.load(instance.id).installed_mods[0].version_id=='chosen'
    assert (root/directory/'chosen.jar').read_bytes()==data and not (root/directory/'old.jar').exists()
    assert service.load(instance.id).installed_mods[0].enabled==enabled
    with pytest.raises(ProviderError):resolve_exact(provider,'different','chosen','1.21.1','fabric')
    with pytest.raises(ProviderError):resolve_exact(provider,'mod','chosen','1.20.1','fabric')


def test_completion_preserves_profile_and_installed_row_opens_it(candidate,monkeypatch):
    app,window,_=candidate
    service=window.instance_service;instance=service.create('Profile fixture','1.21.1','fabric','0.16.10');root=service.path_for(instance.id)
    (root/'mods'/'a.jar').write_bytes(b'fixture');instance.installed_mods=[InstalledMod('mod','v1','Version label','a.jar','a'*128)];service.save(instance)
    page=window.instances_page;page.refresh(instance.id);window._navigate('library','')
    catalog=page.mod_catalog;catalog.instance=instance
    calls=[];monkeypatch.setattr(catalog,'open_installed',lambda *a:calls.append(a))
    row=page.mods.itemWidget(page.mods.item(0));QTest.mouseClick(row,Qt.LeftButton,pos=QPoint(120,20))
    assert calls and calls[0][1]=='mod'
    menu=page.mods.itemWidget(page.mods.item(0)).findChild(QPushButton).menu()
    next(action for action in menu.actions() if action.text()=='Сменить версию…').trigger()
    assert catalog.project_tabs.currentIndex()==3
    assert page.library_stack.currentWidget() is catalog
    page._task_done('Complete')
    assert page.library_stack.currentWidget() is catalog
    page._installed_art_ready('mod',{'title':'Actual project name','icon':png(40,40)})
    row=page.mods.itemWidget(page.mods.item(0))
    assert row.name_label.text()=='Actual project name'
    assert not row.art_label.pixmap().isNull()


def test_runtime_change_preserves_mods_and_worlds_with_manifest_backup(candidate):
    app,window,_=candidate
    service=window.instance_service;instance=service.create('Runtime fixture','1.21.1','fabric','0.16.10');root=service.path_for(instance.id)
    world=root/'saves'/'world';world.mkdir();(world/'level.dat').write_bytes(b'owned fixture')
    changed=service.change_runtime(instance.id,'1.20.1','forge','47.3.0')
    assert changed.minecraft_version=='1.20.1' and changed.loader=='forge'
    assert (world/'level.dat').read_bytes()==b'owned fixture'
    assert list((root/'.nexus'/'backups').glob('*before-runtime-change*'))
    before=(root/'instance.json').read_bytes()
    with pytest.raises(ValueError):service.change_runtime(instance.id,'../bad','fabric','0.16.10')
    assert (root/'instance.json').read_bytes()==before


def test_version_cards_mark_current_and_emit_exact_id(candidate):
    from nexus_launcher.nexus_platform.mod_versions_view import ModVersionsView
    app,window,_=candidate
    widget=ModVersionsView();calls=[]
    versions=[{'id':key,'name':key,'version_type':'release','date_published':'2026-11-11','loaders':['fabric'],'game_versions':['1.21.1']} for key in ('old','new')]
    widget.set_versions(versions,['old'],calls.append);widget.show();app.processEvents()
    buttons=widget.findChildren(QPushButton)
    assert not buttons[0].isEnabled() and buttons[0].text()=='Установлена'
    buttons[1].click();assert calls==['new']
    widget.close()


def test_installed_art_loader_async_caches_and_decodes(candidate,monkeypatch):
    from nexus_launcher.nexus_platform.installed_mod_media import InstalledModMedia
    from PySide6.QtWidgets import QWidget
    app,window,_=candidate
    media=InstalledModMedia(window);calls=[]
    monkeypatch.setattr(media.provider,'project',lambda key:(calls.append(key) or {'title':'Actual title','icon_url':'https://cdn.modrinth.com/data/test/icon.png'}))
    monkeypatch.setattr('nexus_launcher.nexus_platform.installed_mod_media.fetch_media',lambda *a,**k:png(40,40))
    # The global UI fixture suppresses real requests. Exercise the worker through
    # its explicit queue here without opening any external connection.
    media.pending.add('mod');media.pool.submit(media._work,'mod')
    deadline=time.monotonic()+3
    while 'mod' not in media.cache and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert media.cache['mod']['title']=='Actual title' and media.cache['mod']['icon']
    assert calls==['mod']
    media.shutdown()
