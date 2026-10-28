import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from nexus_launcher.curseforge_importer import CurseForgeImporter
from nexus_launcher.curseforge_metadata import expected_file


class Response(io.BytesIO):
    def geturl(self):
        return "https://mediafilez.forgecdn.net/files/1/2/test.jar"


@pytest.fixture
def payload(monkeypatch):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "test")
    monkeypatch.setattr("nexus_launcher.curseforge_importer.time.sleep", lambda _: None)
    monkeypatch.setattr("nexus_launcher.curseforge_importer.open_https", lambda *a, **k: Response(data.getvalue()))
    return data.getvalue()


def test_expected_hash_and_concurrent_cleanup(tmp_path, payload):
    directory = tmp_path / "stage/mods"
    directory.mkdir(parents=True)
    foreign = directory / "another-operation.part"
    foreign.write_bytes(b"keep")
    importer = CurseForgeImporter(tmp_path / "instance", "test")
    ref = {"projectID": 1, "fileID": 2, "sha256": hashlib.sha256(payload).hexdigest()}
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: importer._download_mod(directory, ref), range(8)))
    assert all(record["sha256"] == ref["sha256"] for record in records)
    assert foreign.read_bytes() == b"keep"
    assert list(directory.glob("curseforge-*.part")) == []


@pytest.mark.parametrize("kind", ["hash", "corrupt", "timeout", "missing"])
def test_failure_never_installs_or_deletes_foreign_temp(tmp_path, payload, monkeypatch, kind):
    directory = tmp_path / "stage/mods"
    directory.mkdir(parents=True)
    foreign = directory / "foreign.part"
    foreign.write_bytes(b"keep")
    ref = {"projectID": 1, "fileID": 2, "sha256": "0" * 64}
    if kind == "corrupt":
        ref["sha256"] = hashlib.sha256(b"broken").hexdigest()
        monkeypatch.setattr("nexus_launcher.curseforge_importer.open_https", lambda *a, **k: Response(b"broken"))
    elif kind == "timeout":

        def timeout(*args, **kwargs):
            raise TimeoutError("fixture timeout")

        monkeypatch.setattr("nexus_launcher.curseforge_importer.open_https", timeout)
    elif kind == "missing":
        ref.pop("sha256")
        monkeypatch.delenv("NEXUS_CURSEFORGE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        CurseForgeImporter(tmp_path / "instance", "test")._download_mod(directory, ref)
    assert foreign.read_bytes() == b"keep"
    assert not (directory / "test.jar").exists()
    assert list(directory.glob("curseforge-*.part")) == []


def test_missing_pack_hash_uses_official_metadata(tmp_path, payload, monkeypatch):
    monkeypatch.setenv("NEXUS_CURSEFORGE_API_KEY", "test-only-key")
    data = {
        "data": {
            "id": 2,
            "modId": 1,
            "isAvailable": True,
            "fileName": "test.jar",
            "fileLength": len(payload),
            "hashes": [{"algo": 1, "value": hashlib.sha1(payload).hexdigest()}],
        }
    }

    def metadata(request, **kwargs):
        assert request.full_url == "https://api.curseforge.com/v1/mods/1/files/2"
        assert kwargs["allowed_hosts"] == {"api.curseforge.com"}
        assert request.get_header("X-api-key") == "test-only-key"
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr("nexus_launcher.curseforge_metadata.open_https", metadata)
    result = CurseForgeImporter(tmp_path / "instance", "test")._download_mod(
        tmp_path / "stage/mods", {"projectID": 1, "fileID": 2}
    )
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    data["data"]["hashes"] = [{"algo": 2, "value": "0" * 32}]
    with pytest.raises(ValueError, match="SHA-1"):
        expected_file(1, 2, "test-only-key")


def test_parallel_imports_same_instance_are_rejected_and_recover(tmp_path, monkeypatch):
    import threading

    entered, release = threading.Event(), threading.Event()
    importer = CurseForgeImporter(tmp_path / "instance", "test")
    monkeypatch.setattr("nexus_launcher.curseforge_importer.inspect_pack", lambda _: (None, {}))

    def stage(*_):
        entered.set()
        assert release.wait(5)
        raise ValueError("fixture import failed")

    monkeypatch.setattr(importer, "_install_staged", stage)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(importer.install, tmp_path / "fixture.zip")
        assert entered.wait(5)
        try:
            # A separate importer instance must share the same OS lock.
            other = CurseForgeImporter(importer.instance, "test")
            with pytest.raises(RuntimeError, match="операция"):
                other.install(tmp_path / "fixture.zip")
        finally:
            release.set()
        with pytest.raises(ValueError, match="fixture"):
            first.result()
    monkeypatch.setattr(importer, "_install_staged", lambda *_: {"ok": True})
    assert importer.install(tmp_path / "fixture.zip") == {"ok": True}
    assert list((tmp_path / ".staging").iterdir()) == []
