import zipfile
import pytest
from nexus_launcher.skin_readiness import skin_component


@pytest.mark.parametrize('loader,marker', [('fabric','fabric.mod.json'), ('forge','META-INF/mods.toml'), ('neoforge','META-INF/neoforge.mods.toml')])
def test_component_requires_enabled_jar_and_loader_metadata(tmp_path, loader, marker):
    mods = tmp_path / 'mods'
    mods.mkdir()
    jar = mods / 'renamed.jar'
    with zipfile.ZipFile(jar, 'w') as out:
        out.writestr('customskinloader/CustomSkinLoader.class', b'synthetic')
        out.writestr(marker, '{}')
    assert skin_component(tmp_path, loader) == 'present'
    jar.rename(mods / 'renamed.jar.disabled')
    assert skin_component(tmp_path, loader) == 'missing'


def test_filename_and_prepared_png_are_not_component_evidence(tmp_path):
    (tmp_path / 'mods').mkdir()
    (tmp_path / 'mods/customskinloader.jar').write_bytes(b'broken')
    (tmp_path / 'CustomSkinLoader').mkdir()
    assert skin_component(tmp_path, 'fabric') == 'missing'
    assert skin_component(tmp_path, 'vanilla') == 'vanilla'


def test_wrong_loader_not_present(tmp_path):
    (tmp_path / 'mods').mkdir()
    with zipfile.ZipFile(tmp_path / 'mods/skin.jar', 'w') as out:
        out.writestr('customskinloader/CustomSkinLoader.class', b'x')
        out.writestr('fabric.mod.json', '{}')
    assert skin_component(tmp_path, 'forge') == 'missing'


def test_universal_nested_component(tmp_path):
    import io
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as inner:inner.writestr('customskinloader/CustomSkinLoader.class',b'x')
    (tmp_path/'mods').mkdir()
    with zipfile.ZipFile(tmp_path/'mods/universal.jar','w') as outer:
        outer.writestr('META-INF/jar-jar/CustomSkinLoader-Common.jar',data.getvalue())
        outer.writestr('customskinloader/bootstrap/neoforge/v2/TransformerBootstrap.class',b'x')
    assert skin_component(tmp_path,'neoforge')=='present'
    assert skin_component(tmp_path,'fabric')=='missing'


def test_sync_preserves_other_sources_and_is_idempotent(tmp_path):
    from types import SimpleNamespace
    import json
    from nexus_launcher.modern_main import Launcher
    folder = tmp_path / 'CustomSkinLoader'
    folder.mkdir()
    config = folder / 'CustomSkinLoader.json'
    config.write_text(json.dumps({'customSetting':True, 'loadlist':[{'name':'Other','type':'MojangAPI'}]}))
    owner=SimpleNamespace(account_profile=SimpleNamespace(minecraft_nick='Builder',skin_png=b'synthetic',skin_model='slim'))
    Launcher._sync_skin_for_instance(owner,tmp_path)
    Launcher._sync_skin_for_instance(owner,tmp_path)
    data=json.loads(config.read_text())
    assert data['customSetting'] is True
    assert [r['name'] for r in data['loadlist']] == ['NEXUS LocalSkin','NEXUS Network Skins','Other']
    assert data['loadlist'][0]['model']=='slim'
    assert data['loadlist'][1]['model']=='auto'


def test_corrupt_skin_config_is_not_replaced(tmp_path):
    from types import SimpleNamespace
    from nexus_launcher.modern_main import Launcher
    folder=tmp_path/'CustomSkinLoader'
    folder.mkdir()
    config=folder/'CustomSkinLoader.json'
    config.write_text('{broken')
    owner=SimpleNamespace(account_profile=SimpleNamespace(minecraft_nick='Builder',skin_png=b'synthetic',skin_model='default'))
    with pytest.raises(ValueError):Launcher._sync_skin_for_instance(owner,tmp_path)
    assert config.read_text()=='{broken'


def test_unsafe_nick_rejected(tmp_path):
    from types import SimpleNamespace
    from nexus_launcher.modern_main import Launcher
    owner=SimpleNamespace(account_profile=SimpleNamespace(minecraft_nick='../escape',skin_png=b'synthetic'))
    with pytest.raises(ValueError):Launcher._sync_skin_for_instance(owner,tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('choice,expected', [('Отмена','cancel'), ('Подготовить установку','install'), ('Запустить без скина','launch')])
def test_launch_choice_does_not_silently_install(tmp_path,monkeypatch,choice,expected):
    from types import SimpleNamespace
    import nexus_launcher.modern_main as main
    calls=[]
    class Dialog:
        ActionRole=0;AcceptRole=1;RejectRole=2
        def __init__(self,*args):pass
        def setWindowTitle(self,*args):pass
        def setText(self,*args):pass
        def setInformativeText(self,*args):pass
        def addButton(self,label,*args):return label
        def exec(self):pass
        def clickedButton(self):return choice
    monkeypatch.setattr(main,'QMessageBox',Dialog)
    instance=SimpleNamespace(loader='fabric')
    owner=SimpleNamespace(game_process=None,_launch_lock=SimpleNamespace(locked=lambda:False),
        account_profile=SimpleNamespace(skin_png=b'skin'),
        instance_service=SimpleNamespace(load=lambda _:instance,path_for=lambda _:tmp_path),
        instances_page=SimpleNamespace(_catalog_install=lambda *args:calls.append(('install',args))),
        show_instances=lambda:None,_launch_user_instance_worker=lambda:None,
        _start_launch_worker=lambda *args:calls.append(('launch',args)))
    main.Launcher._launch_user_instance(owner,'instance')
    assert ([c[0] for c in calls] or ['cancel'])==[expected]
