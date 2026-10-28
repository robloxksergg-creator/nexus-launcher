"""Stream parity and failure propagation; not native ZIP decompression evidence."""
import hashlib
import io
from types import SimpleNamespace
import zipfile

import pytest

from nexus_launcher import resource_limits as limits


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(limits, "_native", None)
    elif getattr(limits._native, "STREAM_IO_API_VERSION", None) != 1:
        pytest.skip("Fresh native stream IO capability unavailable")


@pytest.mark.parametrize("copy", [False, True])
@pytest.mark.parametrize("size", [0, 3, 64 * 1024, 256 * 1024 + 1])
def test_exact_limits_digest_and_stream_lifetime(backend, copy, size):
    data = b"x" * size
    source, target = io.BytesIO(data), io.BytesIO()
    digest = hashlib.sha256()
    if copy:
        assert limits.copy_limited(source, target, size, digest) == size
        assert target.getvalue() == data
        assert digest.digest() == hashlib.sha256(data).digest()
    else:
        assert limits.read_limited(source, size) == data
    assert not source.closed and not target.closed


@pytest.mark.parametrize("copy", [False, True])
def test_overflow_is_not_written_or_hashed(backend, copy):
    target = io.BytesIO()
    digest = hashlib.sha256()
    with pytest.raises(ValueError, match="byte limit"):
        if copy:
            limits.copy_limited(io.BytesIO(b"12345"), target, 4, digest)
        else:
            limits.read_limited(io.BytesIO(b"12345"), 4)
    assert target.getvalue() == b""
    assert digest.digest() == hashlib.sha256().digest()


@pytest.mark.parametrize("copy", [False, True])
def test_read1_preferred_and_requests_bounded(backend, copy):
    calls = []
    data = io.BytesIO(b"abcdef")

    class Fragmented:
        def read(self, _):
            raise AssertionError("Buffered read must not be used")

        def read1(self, size):
            calls.append(size)
            return data.read(min(size, 2))

    target = io.BytesIO()
    if copy:
        assert limits.copy_limited(Fragmented(), target, 6) == 6
        assert target.getvalue() == b"abcdef"
    else:
        assert limits.read_limited(Fragmented(), 6) == b"abcdef"
    assert calls == [7, 5, 3, 1]


@pytest.mark.parametrize("copy", [False, True])
def test_slow_drip_and_late_eof_policy(backend, copy, monkeypatch):
    clock = [0]
    monkeypatch.setattr(limits.time, "monotonic", lambda: clock[0])

    class Drip:
        def read(self, _):
            clock[0] += 2
            return b"x"

    with pytest.raises(TimeoutError, match="time budget"):
        if copy:
            limits.copy_limited(Drip(), io.BytesIO(), timeout=3)
        else:
            limits.read_limited(Drip(), timeout=3)
    assert clock[0] == 4

    class LateEOF:
        def read(self, _):
            clock[0] += 2
            return b""

    # Preserve existing semantics: copy checks time only after a nonempty read;
    # bounded response reads also reject a late EOF. Neither interrupts a call.
    if copy:
        assert limits.copy_limited(LateEOF(), io.BytesIO(), timeout=1) == 0
    else:
        with pytest.raises(TimeoutError):
            limits.read_limited(LateEOF(), timeout=1)


@pytest.mark.parametrize("written", [0, 1, None, -1])
def test_short_write_never_reports_success_or_updates_digest(backend, written):
    calls = []
    digest = hashlib.sha256()

    class ShortWriter:
        def write(self, block):
            calls.append(block)
            return written

    with pytest.raises(OSError, match="Incomplete stream write"):
        limits.copy_limited(io.BytesIO(b"abc"), ShortWriter(), digest=digest)
    assert calls == [b"abc"]
    assert digest.digest() == hashlib.sha256().digest()


@pytest.mark.parametrize("stage", ["read", "write", "digest"])
def test_original_errors_propagate_without_retry(backend, stage):
    calls = []
    failure = OSError("fixture failure")

    def refuse(*args):
        calls.append(args)
        raise failure

    source = SimpleNamespace(read=refuse) if stage == "read" else io.BytesIO(b"abc")
    target = SimpleNamespace(write=refuse) if stage == "write" else io.BytesIO()
    digest = SimpleNamespace(update=refuse) if stage == "digest" else None
    with pytest.raises(OSError) as caught:
        limits.copy_limited(source, target, digest=digest)
    assert caught.value is failure
    assert len(calls) == 1
    if stage == "digest":
        assert target.getvalue() == b"abc"  # The helper does not roll back writes.


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_real_zip_stream_and_crc_refusal(backend, compression):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=compression) as archive:
        archive.writestr("config/test.txt", b"archive fixture" * 100)
    with zipfile.ZipFile(data) as archive, archive.open("config/test.txt") as source:
        target = io.BytesIO()
        assert limits.copy_limited(source, target, 1500) == 1500
        assert target.getvalue() == b"archive fixture" * 100
    # Corrupt the expected CRC in a ZipInfo fixture, leaving payload bytes alone.
    with zipfile.ZipFile(data) as archive:
        item = archive.getinfo("config/test.txt")
        item.CRC ^= 1
        with archive.open(item) as source, pytest.raises(zipfile.BadZipFile, match="CRC"):
            limits.copy_limited(source, io.BytesIO(), 1500)


@pytest.mark.parametrize("copy", [False, True])
@pytest.mark.parametrize("kwargs", [{"limit": -1}, {"limit": 1.5},
                                   {"limit": 1 << 64}, {"timeout": -1},
                                   {"timeout": float("nan")}, {"timeout": float("inf")},
                                   {"timeout": 10**1000}])
def test_invalid_limits_refused_before_read(backend, copy, kwargs):
    def forbidden(_):
        raise AssertionError("Must reject before IO")

    source = SimpleNamespace(read=forbidden)
    with pytest.raises(ValueError, match="Invalid stream"):
        if copy:
            limits.copy_limited(source, io.BytesIO(), **kwargs)
        else:
            limits.read_limited(source, **kwargs)


def test_old_extension_uses_compatibility_path(monkeypatch):
    monkeypatch.setattr(limits, "_native", SimpleNamespace(CORE_API_VERSION=1))
    assert limits.read_limited(io.BytesIO(b"abc")) == b"abc"
    target = io.BytesIO()
    assert limits.copy_limited(io.BytesIO(b"abc"), target) == 3


@pytest.mark.parametrize("copy", [False, True])
@pytest.mark.parametrize("version", [1, 99, None])
def test_native_failure_or_bad_version_never_downgrades(monkeypatch, copy, version):
    calls = []

    def refuse(*args):
        calls.append(args)
        raise OSError("native fixture refusal")

    monkeypatch.setattr(limits, "_native", SimpleNamespace(
        STREAM_IO_API_VERSION=version, stream_read_limited=refuse, stream_copy_limited=refuse))
    source = io.BytesIO(b"abc")
    with pytest.raises(OSError if version == 1 else ImportError):
        if copy:
            limits.copy_limited(source, io.BytesIO())
        else:
            limits.read_limited(source)
    assert source.tell() == 0
    assert len(calls) == (1 if version == 1 else 0)
