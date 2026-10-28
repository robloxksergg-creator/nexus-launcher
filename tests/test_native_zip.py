"""Real DEFLATE/CRC/path integration; no archive authenticity claims."""
import io
import hashlib
from types import SimpleNamespace
import zipfile
import zlib

import pytest

from nexus_launcher import native_zip
from nexus_launcher.resource_limits import copy_limited


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(native_zip, "_native", None)
    elif getattr(native_zip._native, "ZIP_DEFLATE_API_VERSION", None) != 1:
        pytest.skip("Fresh native ZIP DEFLATE capability unavailable")


def make_zip(data, *, compression=zipfile.ZIP_DEFLATED, zip64=False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        if zip64:
            with archive.open("config/entry", "w", force_zip64=True) as stream:
                stream.write(data)
        else:
            archive.writestr("config/entry", data)
    return buffer


@pytest.mark.parametrize("size", [0, 1, 4096, 65536, 262144, 262145, 2 * 1024 * 1024])
def test_real_deflate_size_boundaries(backend, size):
    data = (bytes(range(256)) * (size // 256 + 1))[:size]
    with zipfile.ZipFile(make_zip(data)) as archive:
        with native_zip.open_zip_entry(archive, archive.infolist()[0]) as source:
            output = io.BytesIO()
            assert copy_limited(source, output, size) == size
            assert output.getvalue() == data
        assert not archive.fp.closed


@pytest.mark.parametrize("zip64", [False, True])
def test_high_ratio_and_zip64(backend, zip64):
    data = b"x" * (8 * 1024 * 1024)
    with zipfile.ZipFile(make_zip(data, zip64=zip64)) as archive:
        with native_zip.open_zip_entry(archive, archive.infolist()[0]) as source:
            output = io.BytesIO()
            assert copy_limited(source, output, len(data)) == len(data)
            assert output.getvalue() == data


def test_crc_failure_propagates(backend):
    with zipfile.ZipFile(make_zip(b"fixture")) as archive:
        item = archive.infolist()[0]
        item.CRC ^= 1
        with pytest.raises(zipfile.BadZipFile, match="CRC"):
            with native_zip.open_zip_entry(archive, item) as source:
                copy_limited(source, io.BytesIO(), item.file_size)


def test_copy_limit_still_refuses(backend):
    with zipfile.ZipFile(make_zip(b"12345")) as archive:
        output = io.BytesIO()
        with pytest.raises(ValueError, match="byte limit"):
            with native_zip.open_zip_entry(archive, archive.infolist()[0]) as source:
                copy_limited(source, output, 4)
        assert output.getvalue() == b""


def test_bad_local_header_still_refuses(backend):
    buffer = make_zip(b"fixture")
    data = bytearray(buffer.getvalue())
    data[30] ^= 1  # Local filename differs from the central directory.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with pytest.raises(zipfile.BadZipFile):
            with native_zip.open_zip_entry(archive, archive.infolist()[0]):
                pass


def raw_deflate(data):
    encoder = zlib.compressobj(wbits=-15)
    return encoder.compress(data) + encoder.flush()


@pytest.fixture
def decoder_type():
    if getattr(native_zip._native, "ZIP_DEFLATE_API_VERSION", None) != 1:
        pytest.skip("Fresh native ZIP decoder unavailable")
    return native_zip._native.ZipDeflateDecoder


def test_fragmented_raw_decoder(decoder_type):
    data = b"fragmented raw fixture" * 100
    compressed = raw_deflate(data)
    decoder = decoder_type(len(data), len(compressed))
    output = bytearray()
    pending = b""
    for byte in compressed:
        pending += bytes([byte])
        output.extend(decoder.decompress(pending, 1))
        pending = decoder.unconsumed_tail
    while pending:
        output.extend(decoder.decompress(pending, 1))
        pending = decoder.unconsumed_tail
    output.extend(decoder.flush())
    decoder.verify_complete()
    assert bytes(output) == data
    with pytest.raises(ValueError, match="closed"):
        decoder.decompress(b"", 1)


@pytest.mark.parametrize("case", ["truncated", "trailing", "oversize", "compressed_size"])
def test_invalid_completion_is_never_success(decoder_type, case):
    compressed = raw_deflate(b"fixture")
    size = 7
    if case == "truncated":
        compressed = compressed[:-1]
    elif case == "trailing":
        compressed += b"junk"
    elif case == "oversize":
        size = 1
    decoder = decoder_type(size, len(compressed) + (case == "compressed_size"))
    with pytest.raises(ValueError):
        decoder.decompress(compressed, 4096)
        decoder.flush()
        decoder.verify_complete()
    with pytest.raises(ValueError):
        decoder.verify_complete()


@pytest.mark.parametrize("size", [7, 20_000])
def test_partial_read_cannot_claim_completion(decoder_type, size):
    with zipfile.ZipFile(make_zip(b"x" * size)) as archive:
        with pytest.raises(ValueError, match="completion"):
            with native_zip.open_zip_entry(archive, archive.infolist()[0]) as source:
                assert source.read1(1) == b"x"


def test_stored_entry_keeps_existing_path(monkeypatch):
    def forbidden(*_):
        raise AssertionError("No DEFLATE decoder for stored data")

    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_DEFLATE_API_VERSION=1, ZipDeflateDecoder=forbidden))
    with zipfile.ZipFile(make_zip(b"stored", compression=zipfile.ZIP_STORED)) as archive:
        with native_zip.open_zip_entry(archive, archive.infolist()[0]) as source:
            assert source.read() == b"stored"


@pytest.mark.parametrize("version", [99, None])
def test_incompatible_version_refused_before_open(monkeypatch, version):
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(ZIP_DEFLATE_API_VERSION=version))
    def forbidden(*_):
        raise AssertionError("Must reject before opening")
    with pytest.raises(ImportError):
        with native_zip.open_zip_entry(SimpleNamespace(open=forbidden), None):
            pass


def test_native_failure_never_falls_back(monkeypatch):
    failure = ValueError("native fixture failure")
    class Decoder:
        eof = False
        unconsumed_tail = b""
        def __init__(self, *_): pass
        def decompress(self, *_): raise failure
        def verify_complete(self): raise AssertionError("No verification after failure")
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_DEFLATE_API_VERSION=1, ZipDeflateDecoder=Decoder))
    with zipfile.ZipFile(make_zip(b"fixture")) as archive:
        with pytest.raises(ValueError) as caught:
            with native_zip.open_zip_entry(archive, archive.infolist()[0]) as source:
                source.read1(1)
    assert caught.value is failure


def test_unknown_private_protocol_refuses_and_closes(monkeypatch):
    def forbidden(*_):
        raise AssertionError("No decoder before protocol validation")
    monkeypatch.setattr(native_zip, "_native", SimpleNamespace(
        ZIP_DEFLATE_API_VERSION=1, ZipDeflateDecoder=forbidden))
    with zipfile.ZipFile(make_zip(b"fixture")) as archive:
        stream = archive.open(archive.infolist()[0])
        del stream._readbuffer
        monkeypatch.setattr(archive, "open", lambda *_: stream)
        with pytest.raises(ImportError, match="protocol"):
            with native_zip.open_zip_entry(archive, archive.infolist()[0]):
                pass
        assert stream.closed


def test_deflated_update_installs_expected_bytes(backend, tmp_path):
    from nexus_launcher.updater import ModpackUpdater, PackRelease
    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("mods/fixture.jar", b"fixture" * 1000)
    release = PackRelease("zip-native", "https://example.invalid/fixture.zip",
                          hashlib.sha256(archive.read_bytes()).hexdigest())
    updater = ModpackUpdater(tmp_path / "game")
    updater.apply(archive, release)
    assert (tmp_path / "game/mods/fixture.jar").read_bytes() == b"fixture" * 1000
    assert updater.installed_version == "zip-native"


def test_crc_failure_does_not_replace_installed_file(backend, tmp_path):
    from nexus_launcher.updater import ModpackUpdater, PackRelease
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("mods/fixture.jar", b"changed")
    raw = bytearray(archive.read_bytes())
    central = raw.index(b"PK\x01\x02")
    raw[central + 16] ^= 1  # Central CRC, not the payload or metadata size.
    archive.write_bytes(raw)
    game = tmp_path / "game"
    (game / "mods").mkdir(parents=True)
    original = game / "mods/fixture.jar"
    original.write_bytes(b"original")
    updater = ModpackUpdater(game)
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        updater.apply(archive, PackRelease("bad", "", ""))
    assert original.read_bytes() == b"original"
