"""Bounded copy parity, native handle lifetime and refusal cleanup."""
import hashlib
import os
import types

import pytest

from nexus_launcher import safe_paths as paths


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(paths, "_native", None)
    elif os.name != "nt" or getattr(paths._native, "COPY_STREAM_API_VERSION", None) != 1:
        pytest.skip("Native copy extension unavailable")


@pytest.mark.parametrize("size", [0, 3, 256 * 1024, 256 * 1024 + 1])
def test_copy_boundaries(tmp_path, backend, size):
    source, target = tmp_path / "source", tmp_path / "nested" / "target"
    content = b"x" * size
    source.write_bytes(content)
    paths.atomic_copy(source, target, expected_sha256=hashlib.sha256(content).hexdigest())
    assert source.read_bytes() == content
    assert target.read_bytes() == content
    assert not list(target.parent.glob("copy-*.tmp"))


@pytest.mark.parametrize("failure", ["hash", "limit"])
def test_copy_refusal_retains_target_and_cleans_temporary(tmp_path, backend, monkeypatch, failure):
    from nexus_launcher import resource_limits

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    expected = "0" * 64
    if failure == "limit":
        monkeypatch.setattr(resource_limits, "MAX_FILE_BYTES", 2)
        expected = None
    with pytest.raises(ValueError, match="hash mismatch|byte limit"):
        paths.atomic_copy(source, target, expected_sha256=expected)
    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"old"
    assert not list(tmp_path.glob("copy-*.tmp"))
    source.rename(tmp_path / "source-released")


@pytest.mark.parametrize("version", [1, 99])
def test_native_failure_is_not_downgraded(tmp_path, monkeypatch, version):
    if os.name != "nt":
        pytest.skip("Windows copy capability")
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    calls = []

    def refuse(*args):
        calls.append(args)
        raise OSError("native copy refused")

    monkeypatch.setattr(paths, "_native", types.SimpleNamespace(
        COPY_STREAM_API_VERSION=version, windows_copy_streams=refuse))
    with pytest.raises(OSError if version == 1 else ImportError):
        paths.atomic_copy(source, target)
    assert len(calls) == (1 if version == 1 else 0)
    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"old"
    assert not list(tmp_path.glob("copy-*.tmp"))


def test_native_duplicates_leave_original_streams_open(tmp_path):
    if os.name != "nt" or getattr(paths._native, "COPY_STREAM_API_VERSION", None) != 1:
        pytest.skip("Native copy extension unavailable")
    import msvcrt

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"content")
    with source.open("rb", buffering=0) as input_stream, target.open("wb", buffering=0) as output:
        count, digest = paths._native.windows_copy_streams(
            msvcrt.get_osfhandle(input_stream.fileno()), msvcrt.get_osfhandle(output.fileno()), 7)
        assert count == 7
        assert digest == hashlib.sha256(b"content").hexdigest()
        assert input_stream.tell() == output.tell() == 7
        # These operations fail if native code accidentally consumed originals.
        input_stream.seek(0)
        assert input_stream.read() == b"content"
        output.write(b"!")
    assert target.read_bytes() == b"content!"


def test_native_limit_never_writes_overflow_byte(tmp_path):
    if os.name != "nt" or getattr(paths._native, "COPY_STREAM_API_VERSION", None) != 1:
        pytest.skip("Native copy extension unavailable")
    import msvcrt

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"123")
    with source.open("rb", buffering=0) as input_stream, target.open("wb", buffering=0) as output:
        with pytest.raises(ValueError, match="byte limit"):
            paths._native.windows_copy_streams(msvcrt.get_osfhandle(input_stream.fileno()),
                                              msvcrt.get_osfhandle(output.fileno()), 2)
        assert output.tell() <= 2
        input_stream.seek(0)
        assert input_stream.read() == b"123"
    assert target.stat().st_size <= 2
