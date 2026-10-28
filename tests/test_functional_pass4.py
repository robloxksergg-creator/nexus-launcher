import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from nexus_launcher.creator_services import StudioService, Capabilities
from nexus_launcher.instance_transfer import InstanceTransferService
from nexus_launcher.instance_ui import CreateInstanceDialog
from nexus_launcher.studio_ui import StudioPage
from nexus_launcher.user_instances import InstanceService


def test_import_folder_copies_without_modifying_original(tmp_path):
    folder = tmp_path / "source"
    (folder / "mods").mkdir(parents=True)
    (folder / "mods/test.jar").write_bytes(b"mod")
    (folder / "config").mkdir()
    (folder / "config/test.txt").write_text("setting")
    instances = InstanceService(tmp_path / "instances")
    transfer = InstanceTransferService(instances)
    summary = transfer.analyze_folder(folder)
    assert summary["mods"] == 1
    assert summary["minecraft"] is None
    imported = transfer.import_folder(folder, "Copy", "1.21.1", "vanilla")
    assert (folder / "mods/test.jar").read_bytes() == b"mod"
    assert (instances.path_for(imported.id) / "config/test.txt").read_text() == "setting"


@pytest.mark.parametrize("metadata", [[], {"name": 123}, {"mod_sides": []}, {"presentation": {"video": []}}])
def test_malformed_project_metadata_is_rejected(tmp_path, metadata):
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "vanilla")
    (instances.path_for(instance.id) / ".nexus/project.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        StudioService(instances, Capabilities("creator")).load(instance.id)


def test_studio_draft_persists_and_player_cannot_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "vanilla")
    page = StudioPage(instances)
    page.set_mode(True)
    page.refresh()
    page.name.setText("Draft")
    assert page.dirty
    assert page.save()
    assert not page.dirty
    assert StudioService(instances, Capabilities("creator")).load(instance.id)["name"] == "Draft"
    page.set_mode(False)
    page.name.setText("Denied")
    assert not page.save()
    page.close()


def test_creation_templates_have_real_loader_values():
    app = QApplication.instance() or QApplication([])
    dialog = CreateInstanceDialog()
    dialog.template.setCurrentText("NeoForge Tech")
    assert dialog.values()[2] == "neoforge"
    assert dialog.memory.value() == 6144
    dialog.close()


def test_explicit_mod_metadata_detects_missing_dependencies_and_loader(tmp_path):
    import zipfile
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "neoforge")
    with zipfile.ZipFile(instances.path_for(instance.id) / "mods/example.jar", "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({"id": "example", "depends": {"missing_api": "*"}}))
    service = StudioService(instances, Capabilities("creator"))
    errors = service.validate(instance.id)
    assert any("Fabric-мод" in error for error in errors)
    assert any("missing_api" in error for error in errors)


def test_presentation_export_bundles_image_with_matching_hash(tmp_path):
    import hashlib
    import zipfile
    from PySide6.QtGui import QImage
    image = QImage(16, 16, QImage.Format_RGB32)
    image.fill(0xff336699)
    asset = tmp_path / "banner.png"
    assert image.save(str(asset))
    instances = InstanceService(tmp_path / "instances")
    instance = instances.create("Test", "1.21.1", "vanilla")
    service = StudioService(instances, Capabilities("creator"))
    project = service.load(instance.id)
    project["presentation"] = {"banner": str(asset)}
    service.save(instance.id, project)
    with zipfile.ZipFile(service.export(instance.id, tmp_path / "client.zip")) as archive:
        manifest = json.loads(archive.read("nexus-local-manifest.json"))
        name = manifest["presentation"]["banner"]
        assert hashlib.sha256(archive.read(name)).hexdigest() == manifest["sha256"][name]
        assert str(asset) not in json.dumps(manifest)


def test_automatic_side_classification_uses_explicit_fabric_environment(tmp_path):
    import zipfile
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "fabric")
    for name, environment in (("client.jar", "client"), ("both.jar", "*")):
        with zipfile.ZipFile(instances.path_for(instance.id) / "mods" / name, "w") as archive:
            archive.writestr("fabric.mod.json", json.dumps({"id": name[:-4], "environment": environment}))
    service = StudioService(instances, Capabilities("creator"))
    sides = service.auto_classify(instance.id)
    assert sides["client.jar"] == "client"
    assert sides["both.jar"] == "both"


def test_export_summary_blocks_unknown_server_mod(tmp_path):
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "vanilla")
    (instances.path_for(instance.id) / "mods/unknown.jar").write_bytes(b"unknown")
    service = StudioService(instances, Capabilities("creator"))
    assert service.export_summary(instance.id, True).unknown_mods == 1
    with pytest.raises(ValueError, match="сторону"):
        service.export(instance.id, tmp_path / "server.zip", True)


def test_embedded_dependency_is_warning_not_missing_error(tmp_path):
    import zipfile
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "fabric")
    path = instances.path_for(instance.id) / "mods/nested.jar"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({"id": "nested", "jars": [{"file": "META-INF/jars/api.jar"}], "depends": {"inside_api": "*"}}))
    service = StudioService(instances, Capabilities("creator"))
    assert not any("отсутствуют зависимости" in error for error in service.validate(instance.id))
    report = service.validation_report(instance.id)
    assert any(item.level == "WARNING" and "вложенные" in item.message for item in report)


def test_physical_delete_removes_only_selected_instance(tmp_path):
    instances = InstanceService(tmp_path)
    first = instances.create("One", "1.21.1", "vanilla")
    second = instances.create("Two", "1.21.1", "vanilla")
    first_path, second_path = instances.path_for(first.id), instances.path_for(second.id)
    instances.delete(first.id)
    assert not first_path.exists()
    assert second_path.exists()


def test_test_launch_metadata_is_separate_from_normal_launch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import nexus_launcher.modern_main as modern_main
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "vanilla")
    class Process:
        pid = 42
        def wait(self): return 7
    class Core:
        def __init__(self, *_): pass
        def launch(self, *_args, **_kwargs): return Process()
    class Signal:
        def emit(self, *_): pass
    monkeypatch.setattr(modern_main, "MinecraftLauncher", Core)
    owner = SimpleNamespace(account_profile=SimpleNamespace(minecraft_nick="Player"),
        account_client=SimpleNamespace(game_ticket=lambda: "ticket"), instance_service=instances,
        config={}, bridge=SimpleNamespace(status=Signal(), progress=Signal(), finished=Signal(), game_exited=Signal(), failed=Signal()),
        game_process=None)
    modern_main.Launcher._launch_user_instance_worker(owner, instance.id, "test")
    saved = instances.load(instance.id)
    assert saved.last_test_launch
    assert saved.last_test_exit_code == 7
    assert saved.last_launch == ""
    assert saved.last_exit_code is None


def test_capabilities_are_explicit_and_never_allow_local_publish():
    player, creator = Capabilities("player"), Capabilities("creator")
    assert player.can_create_instance and not player.can_use_studio
    assert creator.can_use_studio and creator.can_edit_project and creator.can_export_client
    assert creator.can_export_server and creator.can_validate_project and creator.can_build_release
    assert not creator.can_publish


def test_bulk_classification_persists_after_restart(tmp_path):
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "vanilla")
    for name in ("one.jar", "two.jar"):
        (instances.path_for(instance.id) / "mods" / name).write_bytes(name.encode())
    service = StudioService(instances, Capabilities("creator"))
    service.classify(instance.id, ["one.jar", "two.jar"], "both")
    reopened = StudioService(InstanceService(tmp_path), Capabilities("creator"))
    assert reopened.load(instance.id)["mod_sides"] == {"one.jar": "both", "two.jar": "both"}


def test_studio_rail_visibility_follows_creator_capability(tmp_path, monkeypatch):
    import nexus_launcher.modern_main as modern_main
    import nexus_launcher.nexus_platform.window as window_module
    config = tmp_path / "launcher.json"
    config.write_text(json.dumps({"creatorMode": False, "welcomeCompleted": True}), encoding="utf-8")
    monkeypatch.setattr(modern_main, "CONFIG_FILE", config)
    monkeypatch.setattr(window_module, "CONFIG_FILE", config)
    monkeypatch.setattr(window_module.PlatformLauncher, "_check_servers", lambda self: None)
    monkeypatch.setattr(window_module.PlatformLauncher, "_restore_account_worker", lambda self: None)
    monkeypatch.setattr(window_module.PlatformLauncher, "_refresh_build_access_worker", lambda self: None)
    window = window_module.PlatformLauncher()
    assert window.rail.section_buttons["studio"].isHidden()
    window._platform_settings_changed({"creatorMode": True})
    assert not window.rail.section_buttons["studio"].isHidden()
    window.close()
