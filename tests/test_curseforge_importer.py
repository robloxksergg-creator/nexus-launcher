import hashlib
import io
import json
import zipfile

from nexus_launcher.curseforge_importer import CurseForgeImporter


def test_curseforge_resource_pack_goes_to_resourcepacks(tmp_path, monkeypatch):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("pack.mcmeta", "{}")

    class Response(io.BytesIO):
        def geturl(self):
            return "https://mediafilez.forgecdn.net/files/7937/133/Immersive%20Interfaces.zip"

    monkeypatch.setattr("nexus_launcher.curseforge_importer.open_https", lambda *args, **kwargs: Response(content.getvalue()))
    importer = CurseForgeImporter(tmp_path / "instance", "nexus-pinewood")
    record = importer._download_mod(
        tmp_path / "stage" / "mods",
        {"projectID": 1087342, "fileID": 7937133, "sha256": hashlib.sha256(content.getvalue()).hexdigest()},
    )
    assert record["path"] == "resourcepacks/Immersive Interfaces.zip"
    assert (tmp_path / "stage" / record["path"]).is_file()


def test_nested_shader_archive_is_normalized(tmp_path, monkeypatch):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("Hysteria-main/shaders/test.fsh", "shader")

    class Response(io.BytesIO):
        def geturl(self):
            return "https://mediafilez.forgecdn.net/files/test.zip"

    monkeypatch.setattr("nexus_launcher.curseforge_importer.open_https", lambda *args, **kwargs: Response(content.getvalue()))
    importer = CurseForgeImporter(tmp_path / "instance", "nexus-pinewood")
    record = importer._download_mod(
        tmp_path / "stage/mods", {"projectID": 1, "fileID": 2, "sha256": hashlib.sha256(content.getvalue()).hexdigest()}
    )
    assert record["path"] == "shaderpacks/test.zip"
    with zipfile.ZipFile(tmp_path / "stage" / record["path"]) as archive:
        assert archive.namelist() == ["shaders/test.fsh"]


def test_modified_game_config_does_not_trigger_reinstall(tmp_path):
    importer = CurseForgeImporter(tmp_path / "instance", "nexus-elderfall")
    config = importer.instance / "config/test.json"
    config.parent.mkdir(parents=True)
    config.write_text("changed by game")
    source = tmp_path / "source.zip"
    source.write_bytes(b"source")
    make_state(importer, source, [{"path": "config/test.json", "size": 2, "sha256": "old"}])
    assert importer.verify()
    config.unlink()
    assert not importer.verify()


def test_reinstall_preserves_player_options(tmp_path):
    importer = CurseForgeImporter(tmp_path / "instance", "test")
    importer.instance.mkdir()
    options = importer.instance / "options.txt"
    options.write_text('resourcePacks:["file/custom.zip"]\n')
    staging = tmp_path / "stage"
    staging.mkdir()
    (staging / "options.txt").write_text("resourcePacks:[]\n")
    records = [{"path": "options.txt", "size": 1, "sha256": "old"}]
    importer._apply(staging, records)
    assert options.read_text() == 'resourcePacks:["file/custom.zip"]\n'
    archive = tmp_path / "source.zip"
    archive.write_bytes(b"source")
    make_state(importer, archive, records)
    assert importer.verify()
    importer._apply(staging, [])
    assert options.is_file()


def test_elderfall_repair_is_idempotent_and_preserves_backup(tmp_path):
    importer = CurseForgeImporter(tmp_path / "instance", "nexus-elderfall")
    jar = importer.instance / "mods" / "sodium-extra.jar"
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"backup")
    archive = tmp_path / "source.zip"
    archive.write_bytes(b"source")
    make_state(
        importer, archive, [{"path": "mods/sodium-extra.jar", "source": {"projectId": 447673, "fileId": 8403458}}]
    )
    importer.repair_installed()
    importer.repair_installed()
    assert not jar.exists()
    assert len(list((importer.instance / ".nexus-launcher/quarantine").rglob("sodium-extra.jar"))) == 1
    assert json.loads(importer.state_path.read_text())["files"] == []
    assert importer._fixed_references([{"projectID": 447673, "fileID": 8403458}]) == []


def make_state(importer, archive, files):
    importer.state_path.parent.mkdir(parents=True, exist_ok=True)
    importer.state_path.write_text(
        json.dumps(
            {
                "id": importer.pack_id,
                "sourceArchiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "files": files,
            }
        ),
        encoding="utf-8",
    )


def test_fast_installed_check_ignores_files_replaced_by_remote_update(tmp_path):
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", "{}")
    importer = CurseForgeImporter(tmp_path / "instance", "nexus_launcher.main")
    make_state(importer, archive, [{"path": "mods/old.jar", "size": 3, "sha256": "bad"}])
    assert importer.is_installed(archive)
    assert not importer.verify()


def test_extra_mod_is_quarantined_for_pack_without_remote_manifest(tmp_path):
    archive = tmp_path / "pack.zip"
    archive.write_bytes(b"pack")
    instance = tmp_path / "instance"
    (instance / "mods").mkdir(parents=True)
    (instance / "mods" / "required.jar").write_bytes(b"ok")
    (instance / "mods" / "extra.jar").write_bytes(b"extra")
    importer = CurseForgeImporter(instance, "builder")
    make_state(importer, archive, [{"path": "mods/required.jar", "size": 2, "sha256": "unused"}])
    assert importer.quarantine_extra_mods() == ["extra.jar"]
    assert not (instance / "mods" / "extra.jar").exists()
    assert list((instance / ".nexus-launcher" / "quarantine").rglob("extra.jar"))
