"""Bounded digest parity and real destination readback, not authenticity proofs."""
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus_launcher import resource_limits as limits


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(limits, "_native", None)
    elif getattr(limits._native, "STREAM_HASH_API_VERSION", None) != 1:
        pytest.skip("Fresh native stream hash capability unavailable")


@pytest.mark.parametrize("algorithm", ["sha256", "sha512"])
@pytest.mark.parametrize("size", [0, 3, 256 * 1024 + 1])
def test_vectors_boundaries_and_open_stream(backend, algorithm, size):
    data = b"abc" if size == 3 else b"x" * size
    source = io.BytesIO(data)
    assert limits.digest_limited(source, algorithm, len(data)) == hashlib.new(algorithm, data).hexdigest()
    assert source.tell() == len(data)
    assert not source.closed


def test_fragmented_read1_and_bounded_requests(backend):
    calls = []
    data = io.BytesIO(b"abcdef")

    class Source:
        def read(self, _):
            raise AssertionError("Must use read1")

        def read1(self, size):
            calls.append(size)
            return data.read(min(size, 2))

    assert limits.digest_limited(Source(), limit=6) == hashlib.sha256(b"abcdef").hexdigest()
    assert calls == [7, 5, 3, 1]


@pytest.mark.parametrize("limit", [0, 4])
def test_overflow_never_returns_a_digest(backend, limit):
    with pytest.raises(ValueError, match="Hash input exceeds byte limit"):
        limits.digest_limited(io.BytesIO(b"12345"), limit=limit)


@pytest.mark.parametrize("eof", [False, True])
def test_late_data_and_eof_refused(backend, monkeypatch, eof):
    clock = [0]
    monkeypatch.setattr(limits.time, "monotonic", lambda: clock[0])

    def read(_):
        clock[0] += 2
        return b"" if eof else b"x"

    with pytest.raises(TimeoutError, match="Hashing exceeded its time budget"):
        limits.digest_limited(SimpleNamespace(read=read), timeout=1)
    assert clock[0] == 2


def test_original_read_error_is_not_retried(backend):
    failure = OSError("read fixture")
    calls = []

    def read(size):
        calls.append(size)
        raise failure

    with pytest.raises(OSError) as caught:
        limits.digest_limited(SimpleNamespace(read=read))
    assert caught.value is failure
    assert calls == [256 * 1024]


@pytest.mark.parametrize("algorithm", ["", "md5", "SHA256", None])
def test_unknown_algorithm_refused_before_io(backend, algorithm):
    def read(_):
        raise AssertionError("Unexpected read")

    with pytest.raises(ValueError, match="Unsupported stream digest"):
        limits.digest_limited(SimpleNamespace(read=read), algorithm)


@pytest.mark.parametrize("kwargs", [{"limit": -1}, {"limit": 1 << 64},
                                   {"timeout": float("nan")}, {"timeout": 10**1000}])
def test_bad_limits_refused_before_io(backend, kwargs):
    def read(_):
        raise AssertionError("Unexpected read")

    with pytest.raises(ValueError, match="Invalid stream"):
        limits.digest_limited(SimpleNamespace(read=read), **kwargs)


def test_jar_import_uses_written_file_without_read_bytes(backend, tmp_path, monkeypatch):
    from nexus_launcher import instance_transfer
    from nexus_launcher.user_instances import InstanceService

    service = InstanceService(tmp_path / "instances")
    instance = service.create("Hash fixture", "1.21.1", "fabric")
    source = tmp_path / "local.jar"
    data = b"jar fixture" * 100
    source.write_bytes(data)
    observed = []
    original = instance_transfer.digest_limited

    def observe(stream, algorithm):
        observed.append((Path(stream.name), algorithm))
        return original(stream, algorithm)

    def forbidden_read_bytes(_):
        raise AssertionError("Whole-file allocation must not return")

    monkeypatch.setattr(instance_transfer, "digest_limited", observe)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    destination = instance_transfer.InstanceTransferService(service).import_jar(instance.id, source)
    assert observed == [(destination, "sha512")]
    with destination.open("rb") as copied:
        assert copied.read() == data
    record = service.load(instance.id).installed_mods[0]
    assert record.sha512 == hashlib.sha512(data).hexdigest()
    assert record.version_id == "local:" + record.sha512[:16]


def test_updater_hash_format_and_empty_file(backend, tmp_path):
    from nexus_launcher.updater import sha256_file

    path = tmp_path / "content"
    for data in [b"", b"content"]:
        path.write_bytes(data)
        assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_old_extension_keeps_compatibility(monkeypatch):
    monkeypatch.setattr(limits, "_native", SimpleNamespace(STREAM_IO_API_VERSION=1))
    assert limits.digest_limited(io.BytesIO(b"abc")) == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize("version", [1, 99, None])
def test_native_refusal_never_downgrades(monkeypatch, version):
    calls = []

    def refuse(*args):
        calls.append(args)
        raise OSError("native hash refusal")

    monkeypatch.setattr(limits, "_native", SimpleNamespace(
        STREAM_HASH_API_VERSION=version, stream_digest_limited=refuse))
    source = io.BytesIO(b"abc")
    with pytest.raises(OSError if version == 1 else ImportError):
        limits.digest_limited(source)
    assert source.tell() == 0
    assert len(calls) == (1 if version == 1 else 0)
