import zipfile

import pytest

from nexus_launcher.instance_backups import BackupService
from nexus_launcher.user_instances import InstanceService


def test_backup_restores_files_as_separate_instance_and_retains(tmp_path):
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "vanilla")
    root = instances.path_for(instance.id)
    (root / "config/test.txt").write_text("before")
    (root / "mods/test.jar").write_bytes(b"original")
    (root / "saves/world").mkdir()
    (root / "saves/world/level.dat").write_bytes(b"world")
    backups = BackupService(instances)
    snapshot = backups.create(instance.id)
    (root / "config/test.txt").write_text("after")
    restored = backups.restore_copy(instance.id, snapshot.name)
    target = instances.path_for(restored.id)
    assert restored.id != instance.id
    assert (target / "config/test.txt").read_text() == "before"
    assert (root / "config/test.txt").read_text() == "after"
    assert (target / "mods/test.jar").read_bytes() == b"original"
    assert (target / "saves/world/level.dat").read_bytes() == b"world"
    backups.create(instance.id, retain=1)
    assert len(backups.list(instance.id)) == 1


def test_backup_restore_rejects_traversal_before_creating_instance(tmp_path):
    instances = InstanceService(tmp_path)
    instance = instances.create("Test", "1.21.1", "vanilla")
    backups = BackupService(instances)
    source = backups.folder(instance.id) / "snapshot-evil.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../evil", "no")
    with pytest.raises(ValueError):
        backups.restore_copy(instance.id, source.name)
    assert len(instances.list()) == 1
