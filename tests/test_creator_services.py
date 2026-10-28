import json
import zipfile

import pytest

from nexus_launcher.creator_services import Capabilities, StudioService
from nexus_launcher.user_instances import InstanceService


def test_forget_preserves_files_and_persists(tmp_path):
    instances = InstanceService(tmp_path)
    instance = instances.create("Private", "1.21.1", "vanilla")
    instances.forget(instance.id)
    assert InstanceService(tmp_path).list() == []
    assert instances.load(instance.id).name == "Private"
    assert instances.path_for(instance.id).is_dir()


def test_capabilities_do_not_elevate_local_role(tmp_path):
    for role in ("player", "team", "nexus_launcher.admin"):
        service = StudioService(InstanceService(tmp_path), Capabilities(role))
        with pytest.raises(PermissionError):
            service.load("anything")
        assert not service.capabilities.can_publish


def test_classified_export_and_changes(tmp_path):
    instances = InstanceService(tmp_path / "instances")
    instance = instances.create("Private", "1.21.1", "vanilla")
    root = instances.path_for(instance.id)
    (root / "mods/client.jar").write_bytes(b"client")
    (root / "mods/shared.jar").write_bytes(b"shared")
    service = StudioService(instances, Capabilities("creator"))
    project = service.load(instance.id)
    service.save(instance.id, project)
    with pytest.raises(ValueError, match="сторону"):
        service.export(instance.id, tmp_path / "blocked.zip", server=True)
    project["mod_sides"] = {"client.jar": "client", "shared.jar": "both"}
    project["baseline"] = service.inventory(instance.id)
    service.save(instance.id, project)
    (root / "config/test.json").write_text("{}")
    assert service.changes(instance.id)["added"] == ["config/test.json"]
    destination = service.export(instance.id, tmp_path / "server.zip", server=True)
    with zipfile.ZipFile(destination) as archive:
        assert "mods/client.jar" not in archive.namelist()
        assert "mods/shared.jar" in archive.namelist()
        manifest = json.loads(archive.read("nexus-local-manifest.json"))
        assert manifest["official"] is False
        assert manifest["signed"] is False
        assert "java_path" not in manifest
    with pytest.raises(FileExistsError):
        service.export(instance.id, destination, server=True)


def test_export_rejects_symlink(tmp_path):
    instances = InstanceService(tmp_path / "instances")
    instance = instances.create("Private", "1.21.1", "vanilla")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("private")
    try:
        (instances.path_for(instance.id) / "config/link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink privilege unavailable")
    service = StudioService(instances, Capabilities("creator"))
    with pytest.raises((ValueError, OSError)):
        service.inventory(instance.id)
