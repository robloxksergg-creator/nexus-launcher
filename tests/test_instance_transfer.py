import json
import zipfile

import pytest
from nexus_launcher.instance_transfer import InstanceTransferService
from nexus_launcher.user_instances import InstanceService


def test_zip_export_and_import_roundtrip(tmp_path):
    service = InstanceService(tmp_path / "instances")
    transfer = InstanceTransferService(service)
    instance = service.create("Portable", "1.21.1", "fabric")
    (service.path_for(instance.id) / "config" / "demo.toml").write_text("ok", encoding="utf-8")
    archive = transfer.export_zip(instance.id, tmp_path / "pack.zip")
    imported = transfer.import_zip(archive, "Imported")
    assert imported.name == "Imported"
    assert (service.path_for(imported.id) / "config" / "demo.toml").read_text(encoding="utf-8") == "ok"


def test_zip_import_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "bad")
    transfer = InstanceTransferService(InstanceService(tmp_path / "instances"))
    with pytest.raises(ValueError):
        transfer.import_zip(archive)
    assert not (tmp_path / "escape.txt").exists()


def test_local_jar_import_is_a_copy(tmp_path):
    service = InstanceService(tmp_path / "instances")
    transfer = InstanceTransferService(service)
    instance = service.create("Pack", "1.21.1", "neoforge")
    jar = tmp_path / "local.jar"
    jar.write_bytes(b"demo")
    copied = transfer.import_jar(instance.id, jar)
    assert copied.read_bytes() == b"demo"
    assert jar.exists()
    assert service.load(instance.id).installed_mods[0].filename == "local.jar"


def test_operations_are_persisted(tmp_path):
    service = InstanceService(tmp_path)
    instance = service.create("Pack", "1.21.1", "fabric")
    entries = [
        json.loads(line)
        for line in (service.path_for(instance.id) / ".nexus" / "operations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert entries[-1]["action"] == "instance_created"


def test_import_never_enables_jvm_agents(tmp_path):
    service = InstanceService(tmp_path / "instances")
    transfer = InstanceTransferService(service)
    instance = service.create("Untrusted", "1.21.1", "fabric")
    instance.jvm_args = ["-javaagent:mods/payload.jar", "@args.txt"]
    service.save(instance)
    archive = transfer.export_zip(instance.id, tmp_path / "pack.zip")
    imported = transfer.import_zip(archive)
    assert imported.jvm_args == []
    assert service.load(instance.id).jvm_args == instance.jvm_args
