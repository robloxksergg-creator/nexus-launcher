"""Publishing digest dispatch, real ZIP inventory and fail-closed errors."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from nexus_launcher import publishing
from nexus_launcher import resource_limits as limits


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(limits, "_native", None)
    elif getattr(limits._native, "STREAM_HASH_API_VERSION", None) != 1:
        pytest.skip("Native stream hash capability unavailable")


def submission():
    return publishing.Submission(
        "11111111-1111-1111-1111-111111111111", "project", "creator", 1,
        "1.0.0", "1.21.1", "fabric", publishing.validate_metadata({
            "title": "Test world", "shortName": "TW", "summary": "Summary",
            "description": "Local test fixture", "category": "RPG"}), {}, "client.zip")


def artifact(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mods/example.jar", b"local fixture")


@pytest.mark.parametrize("size", [0, 3, 256 * 1024 + 1])
def test_file_digest_matches_standard_hash(backend, tmp_path, monkeypatch, size):
    data = b"x" * size
    source = tmp_path / "artifact.bin"
    source.write_bytes(data)
    def forbidden(_):
        raise AssertionError("Do not materialize publication artifacts")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    assert publishing.sha256(source) == hashlib.sha256(data).hexdigest()


def test_file_hash_enforces_live_byte_limit(backend, tmp_path, monkeypatch):
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"12345")
    monkeypatch.setattr(publishing, "MAX_PACKAGE_BYTES", 4)
    with pytest.raises(ValueError, match="Hash input exceeds byte limit"):
        publishing.sha256(source)


def test_package_roundtrip_hashes_artifacts_and_presentation(backend, tmp_path):
    client, server, icon = (tmp_path / n for n in ("client.zip", "server.zip", "icon.png"))
    artifact(client); artifact(server); icon.write_bytes(b"image fixture")
    package = tmp_path / "submission.zip"
    publishing.SubmissionPackage.create(package, submission(), client, server, {"icon": icon})
    with zipfile.ZipFile(package) as z:
        raw = json.loads(z.read("submission.json"))
        for name, digest in {**raw["artifactHashes"], **raw["presentationHashes"]}.items():
            assert digest == hashlib.sha256(z.read(name)).hexdigest()
        assert raw["signed"] is False and raw["official"] is False
    loaded, warnings = publishing.SubmissionPackage.inspect(package)
    assert loaded.client_artifact == "artifacts/client.zip"
    assert loaded.server_artifact == "artifacts/server.zip"
    assert loaded.presentation == {"icon": "presentation/icon.png"}
    assert warnings == []


def test_native_dispatch_receives_full_package_limit(tmp_path, monkeypatch):
    native = limits._native
    assert getattr(native, "STREAM_HASH_API_VERSION", None) == 1
    calls = []
    def digest(read, algorithm, limit, timeout, clock):
        calls.append((algorithm, limit, timeout))
        return native.stream_digest_limited(read, algorithm, limit, timeout, clock)
    monkeypatch.setattr(limits, "_native", SimpleNamespace(
        STREAM_HASH_API_VERSION=1, stream_digest_limited=digest))
    client = tmp_path / "client.zip"; artifact(client)
    package = tmp_path / "submission.zip"
    publishing.SubmissionPackage.create(package, submission(), client)
    publishing.SubmissionPackage.inspect(package)
    assert calls == [("sha256", 16 * 1024**3, 300)] * 2


@pytest.mark.parametrize("failure_type", [OSError, TimeoutError, ValueError])
def test_native_hash_failure_retains_destination(tmp_path, monkeypatch, failure_type):
    client = tmp_path / "client.zip"; artifact(client)
    destination = tmp_path / "previous.zip"; destination.write_bytes(b"existing destination")
    failure = failure_type("native hash fixture failure")
    def fail(*_): raise failure
    monkeypatch.setattr(limits, "_native", SimpleNamespace(
        STREAM_HASH_API_VERSION=1, stream_digest_limited=fail))
    with pytest.raises(failure_type) as caught:
        publishing.SubmissionPackage.create(destination, submission(), client)
    assert caught.value is failure
    assert destination.read_bytes() == b"existing destination"
    assert not list(tmp_path.glob("*.part"))


def test_native_readback_failure_is_not_retried(tmp_path, monkeypatch):
    client = tmp_path / "client.zip"; artifact(client)
    package = tmp_path / "submission.zip"
    publishing.SubmissionPackage.create(package, submission(), client)
    before = package.read_bytes()
    failure = OSError("readback fixture failure")
    calls = []
    def fail(*_):
        calls.append(1)
        raise failure
    monkeypatch.setattr(limits, "_native", SimpleNamespace(
        STREAM_HASH_API_VERSION=1, stream_digest_limited=fail))
    with pytest.raises(OSError) as caught:
        publishing.SubmissionPackage.inspect(package)
    assert caught.value is failure and calls == [1]
    assert package.read_bytes() == before


@pytest.mark.parametrize("version", [99, None])
def test_incompatible_hash_version_refused(tmp_path, monkeypatch, version):
    source = tmp_path / "artifact"; source.write_bytes(b"abc")
    monkeypatch.setattr(limits, "_native", SimpleNamespace(STREAM_HASH_API_VERSION=version))
    with pytest.raises(ImportError):
        publishing.sha256(source)
