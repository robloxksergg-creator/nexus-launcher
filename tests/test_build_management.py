import json
import zipfile
from pathlib import Path

import pytest
from nexus_launcher.build_management import BuildManager, sha256


def test_draft_publish_history_and_atomic_rollback(tmp_path: Path):
    manager = BuildManager(tmp_path / "builds", "https://cdn.example.test")
    mod = tmp_path / "Example-1.0.jar"
    with zipfile.ZipFile(mod, "w") as archive:
        archive.writestr("META-INF/neoforge.mods.toml", '[[mods]]\nmodId="example"\nversion="1.0"\n')
    entry = manager.add_file(mod, "mods/Example-1.0.jar", "BOTH", "REQUIRED", "Owner")
    assert entry.sha256 == sha256(mod)
    metadata = manager.metadata()
    metadata.pack_version = "2.2.0"
    metadata.display_name = "Age of Machinery"
    manager.save_metadata(metadata, "Owner")
    manifest_path = manager.publish("Release", "Owner")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "PUBLISHED"
    assert manifest["displayName"] == "Age of Machinery"
    assert manifest["files"][0]["path"] == "mods/Example-1.0.jar"
    assert manager.history()[0]["metadata"]["pack_version"] == "2.2.0"
    manager.rollback("2.2.0", "Owner")
    assert json.loads((manager.current_dir / "manifest.json").read_text())["version"] == "2.2.0"


def test_validation_rejects_missing_or_tampered_file(tmp_path: Path):
    manager = BuildManager(tmp_path / "builds")
    source = tmp_path / "config.json"
    source.write_text("{}")
    entry = manager.add_file(source, "config/example.json", "CLIENT", "REQUIRED")
    (manager.draft_dir / "files" / entry.stored_name).write_text("tampered")
    assert any("Invalid hash" in error for error in manager.validate())


def test_rejects_unsafe_destination(tmp_path: Path):
    manager = BuildManager(tmp_path / "builds")
    source = tmp_path / "x.jar"
    source.write_bytes(b"x")
    with pytest.raises(ValueError):
        manager.add_file(source, "../outside.jar", "BOTH", "REQUIRED")
