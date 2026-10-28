"""Streaming ZIP creation parity, finalization and destination preservation."""
import io
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile
import zlib

import pytest

from nexus_launcher import native_zip


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(native_zip, "_native", None)
    elif getattr(native_zip._native, "ZIP_ENCODE_API_VERSION", None) != 1:
        pytest.skip("Fresh native ZIP encoder unavailable")


@pytest.mark.parametrize("size", [0, 1, 65536, 262145, 2 * 1024 * 1024])
@pytest.mark.parametrize("level", [0, 6, 9])
def test_roundtrip_standard_reader(backend, size, level):
    data = (bytes(range(256)) * (size // 256 + 1))[:size]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as archive:
        native_zip.write_zip_data(archive, "config/entry", data)
    with zipfile.ZipFile(buffer) as archive:
        assert archive.read("config/entry") == data
        assert archive.testzip() is None
        assert archive.getinfo("config/entry").compress_type == zipfile.ZIP_DEFLATED


def test_file_metadata_and_streaming(backend, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"file fixture" * 1000)
    os.utime(source, (1_600_000_000, 1_600_000_000))
    expected = zipfile.ZipInfo.from_file(source, "mods/test.jar")
    def forbidden(_):
        raise AssertionError("Do not load export files with read_bytes")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        native_zip.write_zip_file(archive, source, "mods/test.jar")
    with zipfile.ZipFile(buffer) as archive:
        item = archive.getinfo("mods/test.jar")
        assert item.date_time == expected.date_time
        assert item.external_attr == expected.external_attr
        assert archive.read(item) == b"file fixture" * 1000


def test_unicode_metadata_and_zip64(backend):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        native_zip.write_zip_data(archive, "данные.json", '{"имя":"Нексус"}')
        with native_zip.write_zip_entry(archive, "empty", force_zip64=True):
            pass
    with zipfile.ZipFile(buffer) as archive:
        assert archive.read("данные.json").decode() == '{"имя":"Нексус"}'
        assert archive.read("empty") == b""


def test_source_failure_keeps_original_exception(backend):
    failure = OSError("source fixture failure")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        with pytest.raises(OSError) as caught:
            with native_zip.write_zip_entry(archive, "entry") as output:
                output.write(b"partial")
                raise failure
    assert caught.value is failure


@pytest.fixture
def encoder_type():
    if getattr(native_zip._native, "ZIP_ENCODE_API_VERSION", None) != 1:
        pytest.skip("Fresh native ZIP encoder unavailable")
    return native_zip._native.ZipDeflateEncoder


@pytest.mark.parametrize("level", [0, 1, 6, 9])
def test_raw_incompressible_and_finalization(encoder_type, level):
    data = os.urandom(1024 * 1024)
    encoder = encoder_type(level)
    compressed = encoder.compress(data) + encoder.flush()
    encoder.verify_complete(len(data))
    assert zlib.decompress(compressed, -15) == data
    with pytest.raises(ValueError, match="closed"):
        encoder.compress(b"more")
    with pytest.raises(ValueError):
        encoder.flush()


def test_early_verification_and_bad_size_refused(encoder_type):
    encoder = encoder_type(6)
    with pytest.raises(ValueError, match="completion"):
        encoder.verify_complete(0)
    encoder.compress(b"abc")
    encoder.flush()
    with pytest.raises(ValueError, match="completion"):
        encoder.verify_complete(4)
    encoder.verify_complete(3)


def test_oversized_call_is_terminal(encoder_type):
    encoder = encoder_type(6)
    with pytest.raises(ValueError):
        encoder.compress(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError):
        encoder.flush()


def test_invalid_level(encoder_type):
    with pytest.raises(ValueError, match="level"):
        encoder_type(10)


@pytest.mark.parametrize("version", [99, None])
def test_bad_version_refused_before_write(monkeypatch, version):
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(ZIP_ENCODE_API_VERSION=version))
    def forbidden(*_, **__):
        raise AssertionError("No opening after incompatible version")
    with pytest.raises(ImportError):
        with native_zip.write_zip_entry(SimpleNamespace(open=forbidden), "entry"):
            pass


def test_encoder_failure_does_not_replace_export(tmp_path, monkeypatch):
    from nexus_launcher.instance_transfer import InstanceTransferService
    from nexus_launcher.user_instances import InstanceService
    service = InstanceService(tmp_path / "instances")
    instance = service.create("Export fixture", "1.21.1", "fabric")
    destination = tmp_path / "export.zip"
    destination.write_bytes(b"previous export")
    failure = OSError("encoder fixture failure")
    class Encoder:
        def __init__(self, *_): pass
        def compress(self, *_): raise failure
        def flush(self): raise ValueError("failed encoder cannot finish")
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_ENCODE_API_VERSION=1, ZipDeflateEncoder=Encoder))
    with pytest.raises(OSError) as caught:
        InstanceTransferService(service).export_zip(instance.id, destination)
    assert caught.value is failure
    assert destination.read_bytes() == b"previous export"
    assert not list(tmp_path.glob("*.zip.part"))


def test_stored_entry_does_not_use_encoder(monkeypatch):
    def forbidden(*_):
        raise AssertionError("No compressor for stored entries")
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_ENCODE_API_VERSION=1, ZipDeflateEncoder=forbidden))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        native_zip.write_zip_data(archive, "entry", b"stored")
    with zipfile.ZipFile(buffer) as archive:
        assert archive.read("entry") == b"stored"
