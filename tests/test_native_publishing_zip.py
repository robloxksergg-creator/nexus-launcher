"""Explicit ZIP limits and real local submission package codec integration."""
from types import SimpleNamespace
import zipfile

import pytest

from nexus_launcher import native_zip, publishing
from tests.test_native_publishing_hash import artifact, submission


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(native_zip, "_native", None)
    elif getattr(native_zip._native, "ZIP_LIMITS_API_VERSION", None) != 1:
        pytest.skip("Fresh native explicit ZIP limits unavailable")


@pytest.fixture
def native():
    if getattr(native_zip._native, "ZIP_LIMITS_API_VERSION", None) != 1:
        pytest.skip("Fresh native explicit ZIP limits unavailable")
    return native_zip._native


def test_submission_standard_reader_and_inventory(backend, tmp_path):
    client, server, icon = (tmp_path / n for n in ("client.zip", "server.zip", "icon.png"))
    artifact(client); artifact(server); icon.write_bytes(b"presentation")
    package = tmp_path / "submission.zip"
    publishing.SubmissionPackage.create(package, submission(), client, server, {"icon": icon})
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None
        assert z.read("artifacts/client.zip") == client.read_bytes()
        assert z.read("artifacts/server.zip") == server.read_bytes()
        assert z.read("presentation/icon.png") == b"presentation"
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in z.infolist())
    result, warnings = publishing.SubmissionPackage.inspect(package)
    assert warnings == [] and result.client_artifact == "artifacts/client.zip"


def test_dispatch_preserves_per_operation_limits(native, tmp_path, monkeypatch):
    calls = []
    def encoder(level, **kwargs):
        calls.append(("encode", kwargs.get("limit", 1024**3)))
        return native.ZipDeflateEncoder(level, **kwargs)
    def decoder(size, compressed, **kwargs):
        calls.append(("decode", kwargs.get("limit", 1024**3)))
        return native.ZipDeflateDecoder(size, compressed, **kwargs)
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_LIMITS_API_VERSION=1, ZIP_ENCODE_API_VERSION=1, ZIP_DEFLATE_API_VERSION=1,
        ZipDeflateEncoder=encoder, ZipDeflateDecoder=decoder))
    client = tmp_path / "client.zip"; artifact(client)
    package = tmp_path / "submission.zip"
    publishing.SubmissionPackage.create(package, submission(), client)
    publishing.SubmissionPackage.inspect(package)
    assert calls == [("encode", 1024**3), ("encode", 16 * 1024**3),
                     ("decode", 2 * 1024**2), ("decode", 16 * 1024**3),
                     ("decode", 16 * 1024**3)]


@pytest.mark.parametrize("limit", [0, 3, 16 * 1024**3])
def test_raw_explicit_limit_roundtrip(native, limit):
    data = b"abc" if limit else b""
    e = native.ZipDeflateEncoder(6, limit=limit)
    raw = e.compress(data) + e.flush(); e.verify_complete(len(data))
    d = native.ZipDeflateDecoder(len(data), len(raw), limit=limit)
    assert d.decompress(raw, 1024) + d.flush() == data
    d.verify_complete()


def test_live_encoder_limit_is_terminal(native):
    e = native.ZipDeflateEncoder(6, limit=3)
    e.compress(b"ab")
    with pytest.raises(ValueError, match="size exceeded"):
        e.compress(b"cd")
    with pytest.raises(ValueError): e.flush()


def test_declared_limits_do_not_allocate_declared_size(native):
    with pytest.raises(ValueError): native.ZipDeflateDecoder(1024**3 + 1, 1)
    native.ZipDeflateDecoder(1024**3 + 1, 1, limit=16 * 1024**3)
    with pytest.raises(ValueError): native.ZipDeflateDecoder(4, 1, limit=3)
    with pytest.raises(ValueError): native.ZipDeflateDecoder(1, 16 * 1024**3 + 1, limit=16 * 1024**3)


@pytest.mark.parametrize("limit", [-1, 16 * 1024**3 + 1])
def test_invalid_native_limit(native, limit):
    with pytest.raises((ValueError, OverflowError)): native.ZipDeflateEncoder(6, limit=limit)
    with pytest.raises((ValueError, OverflowError)): native.ZipDeflateDecoder(0, 2, limit=limit)


def test_old_extension_retains_python_explicit_path(tmp_path, monkeypatch):
    def forbidden(*_, **__): raise AssertionError("Old codec must not receive new keyword")
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_ENCODE_API_VERSION=1, ZIP_DEFLATE_API_VERSION=1,
        ZipDeflateEncoder=forbidden, ZipDeflateDecoder=forbidden))
    package = tmp_path / "test.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
        with native_zip.write_zip_entry(z, "data", limit=16 * 1024**3) as stream:
            stream.write(b"abc")
    with zipfile.ZipFile(package) as z:
        with native_zip.open_zip_entry(z, z.getinfo("data"), limit=16 * 1024**3) as stream:
            assert stream.read() == b"abc"


@pytest.mark.parametrize("limit", [-1, 16 * 1024**3 + 1, "16"])
def test_invalid_policy_refused_before_open(limit):
    def forbidden(*_, **__): raise AssertionError("Must refuse before opening")
    with pytest.raises(ValueError):
        with native_zip.write_zip_entry(SimpleNamespace(open=forbidden), "entry", limit=limit): pass


@pytest.mark.parametrize("version", [99, None])
def test_incompatible_explicit_api_refused(monkeypatch, version):
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(ZIP_LIMITS_API_VERSION=version))
    def forbidden(*_, **__): raise AssertionError("Must refuse before opening")
    with pytest.raises(ImportError):
        with native_zip.write_zip_entry(SimpleNamespace(open=forbidden), "entry", limit=16 * 1024**3): pass


def test_selected_native_failure_does_not_create_package(native, tmp_path, monkeypatch):
    client = tmp_path / "client.zip"; artifact(client)
    package = tmp_path / "submission.zip"
    failure = OSError("explicit codec fixture failure")
    def encoder(level, **kwargs):
        if kwargs: raise failure
        return native.ZipDeflateEncoder(level)
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_ENCODE_API_VERSION=1, ZIP_LIMITS_API_VERSION=1, ZipDeflateEncoder=encoder))
    with pytest.raises(OSError) as caught:
        publishing.SubmissionPackage.create(package, submission(), client)
    assert caught.value is failure
    assert not package.exists() and not list(tmp_path.glob("*.part"))
