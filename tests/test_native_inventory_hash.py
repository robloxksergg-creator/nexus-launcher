"""Real inventory consumers reuse bounded native digests without trust changes."""
import hashlib
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from nexus_launcher import build_management, creator_services, curseforge_importer
from nexus_launcher import resource_limits as limits


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(limits, "_native", None)
    else:
        assert getattr(limits._native, "STREAM_HASH_API_VERSION", None) == 1


@pytest.mark.parametrize("consumer", [build_management.sha256, creator_services.digest,
                                     curseforge_importer.sha256_file])
@pytest.mark.parametrize("size", [0, 3, 256 * 1024 + 1])
def test_consumer_digest_parity(backend, tmp_path, consumer, size):
    data = b"x" * size
    source = tmp_path / "source"; source.write_bytes(data)
    assert consumer(source) == hashlib.sha256(data).hexdigest()


def test_limit_comes_from_open_handle(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.write_bytes(b"abc")
    native = limits._native
    calls = []
    def digest(read, algorithm, limit, timeout, clock):
        calls.append((algorithm, limit, timeout))
        return native.stream_digest_limited(read, algorithm, limit, timeout, clock)
    def forbidden(*_): raise AssertionError("Do not stat an independently reopened pathname")
    monkeypatch.setattr(Path, "stat", forbidden)
    monkeypatch.setattr(limits, "_native", SimpleNamespace(
        STREAM_HASH_API_VERSION=1, stream_digest_limited=digest))
    assert limits.digest_file(source) == hashlib.sha256(b"abc").hexdigest()
    assert calls == [("sha256", 3, 300)]


def test_detects_growth_past_opened_size(backend, tmp_path, monkeypatch):
    source = tmp_path / "source"; source.write_bytes(b"abc")
    real_stat = limits.os.fstat
    def shortened(fd):
        values = list(real_stat(fd)); values[6] = 2
        return os.stat_result(values)
    with monkeypatch.context() as patch:
        patch.setattr(limits.os, "fstat", shortened)
        with pytest.raises(ValueError, match="Hash input exceeds byte limit"):
            limits.digest_file(source)


def test_nonregular_handle_refused_before_digest(tmp_path, monkeypatch):
    source = tmp_path / "source"; source.write_bytes(b"abc")
    real_stat = limits.os.fstat
    def nonregular(fd):
        values = list(real_stat(fd)); values[0] = stat.S_IFIFO
        return os.stat_result(values)
    def forbidden(*_, **__): raise AssertionError("No digest of nonregular source")
    with monkeypatch.context() as patch:
        patch.setattr(limits.os, "fstat", nonregular)
        patch.setattr(limits, "digest_limited", forbidden)
        with pytest.raises(ValueError, match="regular file"):
            limits.digest_file(source)


@pytest.mark.parametrize("failure_type", [OSError, TimeoutError, ValueError])
def test_native_error_is_propagated_and_handle_closed(tmp_path, monkeypatch, failure_type):
    source = tmp_path / "source"; source.write_bytes(b"abc")
    failure = failure_type("inventory hash fixture failure")
    streams = []; calls = []
    real_open = Path.open
    def tracked(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs); streams.append(stream); return stream
    def fail(*_): calls.append(1); raise failure
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", tracked)
        patch.setattr(limits, "_native", SimpleNamespace(
            STREAM_HASH_API_VERSION=1, stream_digest_limited=fail))
        with pytest.raises(failure_type) as caught:
            limits.digest_file(source)
    assert caught.value is failure and calls == [1]
    assert len(streams) == 1 and streams[0].closed
    assert source.read_bytes() == b"abc"
