import json

import pytest
from nexus_launcher.user_instances import InstanceService, safe_filename


def test_create_and_reload_isolated_instance(tmp_path):
    service = InstanceService(tmp_path / "user-instances")
    created = service.create("Моя сборка", "1.21.1", "fabric", "0.16.10")
    loaded = service.load(created.id)
    assert loaded.name == "Моя сборка"
    assert loaded.loader == "fabric"
    assert (service.path_for(created.id) / "mods").is_dir()
    assert (
        json.loads((service.path_for(created.id) / "instance.json").read_text(encoding="utf-8"))["schema_version"] == 2
    )


def test_instance_path_rejects_traversal(tmp_path):
    service = InstanceService(tmp_path)
    with pytest.raises(ValueError):
        service.path_for("../../official")


@pytest.mark.parametrize("name", ["../evil.jar", "folder/evil.jar", "", "evil?.jar"])
def test_safe_filename_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        safe_filename(name)


def test_rename_and_delete(tmp_path):
    service = InstanceService(tmp_path)
    instance = service.create("Old", "1.20.1", "vanilla")
    assert service.rename(instance.id, "New").name == "New"
    service.delete(instance.id)
    assert not service.path_for(instance.id).exists()


def test_remove_mod_deletes_only_tracked_file(tmp_path):
    service = InstanceService(tmp_path)
    instance = service.create("Pack", "1.21.1", "fabric")
    jar = service.path_for(instance.id) / "mods" / "demo.jar"
    jar.write_bytes(b"jar")
    from nexus_launcher.user_instances import InstalledMod

    instance.installed_mods.append(InstalledMod("p", "v", "Demo", "demo.jar", "hash"))
    service.save(instance)
    updated = service.remove_mod(instance.id, "demo.jar")
    assert not jar.exists()
    assert updated.installed_mods == []


def test_custom_install_path_is_registered_and_reloads(tmp_path):
    service = InstanceService(tmp_path / "registry")
    custom = tmp_path / "games" / "Personal World"
    created = service.create("Personal", "1.21.1", "vanilla", install_path=str(custom))
    assert service.path_for(created.id) == custom.absolute()
    assert service.load(created.id).install_path == str(custom.absolute())
    assert [item.id for item in InstanceService(service.root).list()] == [created.id]


def test_relocate_preserves_files_and_updates_registry(tmp_path):
    service = InstanceService(tmp_path / "instances")
    created = service.create("Move me", "1.21.1", "vanilla")
    old = service.path_for(created.id)
    (old / "saves" / "world.dat").write_bytes(b"world")
    destination = tmp_path / "other" / "Move me"
    moved = service.relocate(created.id, destination, True)
    assert not old.exists()
    assert service.path_for(created.id) == destination.absolute()
    assert (destination / "saves" / "world.dat").read_bytes() == b"world"
    assert moved.install_path == str(destination.absolute())


def test_new_install_path_keeps_old_user_files(tmp_path):
    service = InstanceService(tmp_path / "instances")
    created = service.create("Fresh", "1.21.1", "vanilla")
    old = service.path_for(created.id)
    (old / "saves" / "world.dat").write_bytes(b"world")
    destination = tmp_path / "new" / "Fresh"
    service.relocate(created.id, destination, False)
    assert (old / "saves" / "world.dat").read_bytes() == b"world"
    assert service.path_for(created.id) == destination.absolute()
    assert not (destination / "saves" / "world.dat").exists()


def test_duplicate_copies_user_content_and_changes_identity(tmp_path):
    service = InstanceService(tmp_path / "instances")
    original = service.create("Original", "1.21.1", "vanilla")
    (service.path_for(original.id) / "config" / "client.toml").write_text("enabled=true", encoding="utf-8")
    duplicate = service.duplicate(original.id)
    assert duplicate.id != original.id
    assert duplicate.name.endswith("копия")
    assert (service.path_for(duplicate.id) / "config" / "client.toml").read_text(encoding="utf-8") == "enabled=true"
