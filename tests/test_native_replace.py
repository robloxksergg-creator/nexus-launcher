"""Replacement parity and refusal cleanup on owned temporary files."""
import hashlib
import os
import types
import uuid
from contextlib import contextmanager

import pytest

from nexus_launcher import safe_paths as paths


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows handle replacement")
    if request.param == "python":
        monkeypatch.setattr(paths, "_native", None)
    elif getattr(paths._native, "HANDLE_REPLACE_API_VERSION", None) != 1:
        pytest.skip("Native replacement unavailable")


@pytest.mark.parametrize("expected", [None, hashlib.sha256(b"new").hexdigest()])
def test_replace_success(tmp_path, backend, expected):
    source, target = tmp_path / "source", tmp_path / "цель"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    paths.replace_file(source, target, expected_sha256=expected)
    assert target.read_bytes() == b"new"
    assert not source.exists()
    tmp_path.rename(tmp_path.with_name(uuid.uuid4().hex + "-released"))


@pytest.mark.parametrize("failure", ["hash", "limit"])
def test_refusal_preserves_files_and_releases_handles(tmp_path, backend, monkeypatch, failure):
    from nexus_launcher import resource_limits

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    expected = "0" * 64
    if failure == "limit":
        monkeypatch.setattr(resource_limits, "MAX_FILE_BYTES", 2)
        expected = hashlib.sha256(b"new").hexdigest()
    with pytest.raises(ValueError, match="hash mismatch|byte limit"):
        paths.replace_file(source, target, expected_sha256=expected)
    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"old"
    tmp_path.rename(tmp_path.with_name(uuid.uuid4().hex + "-released"))


def test_target_hardlink_does_not_modify_other_name(tmp_path, backend):
    source, target, sentinel = (tmp_path / name for name in ("source", "target", "sentinel"))
    source.write_bytes(b"new")
    sentinel.write_bytes(b"old")
    os.link(sentinel, target)
    paths.replace_file(source, target)
    assert sentinel.read_bytes() == b"old"
    assert target.read_bytes() == b"new"


def test_incompatible_native_api_does_not_fallback(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows replacement")
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    monkeypatch.setattr(paths, "_native", types.SimpleNamespace(HANDLE_REPLACE_API_VERSION=99))
    with pytest.raises(ImportError, match="replacement API"):
        paths.replace_file(source, target)
    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"old"


@contextmanager
def deny_target_deletion(target):
    """Hold an actual Windows share-mode restriction, not a simulated error."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def test_locked_target_failure_retains_both_files(tmp_path, backend):
    import time

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    with deny_target_deletion(target):
        start = time.monotonic()
        with pytest.raises(OSError) as failure:
            paths.replace_file(source, target, expected_sha256=hashlib.sha256(b"new").hexdigest())
        assert failure.value.winerror in (5, 32, 33)
        assert time.monotonic() - start >= 1.5
        assert source.read_bytes() == b"new"
        assert target.read_bytes() == b"old"
    # A failure must release the verified source and both parent pins.
    source.rename(tmp_path / "released-source")
    tmp_path.rename(tmp_path.with_name(uuid.uuid4().hex + "-released"))


def test_transient_target_lock_is_retried(tmp_path, backend):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    locked, release = threading.Event(), threading.Event()

    def hold_target():
        with deny_target_deletion(target):
            locked.set()
            assert release.wait(10), "Test failed to release its target handle"

    def replace():
        paths.replace_file(source, target, expected_sha256=hashlib.sha256(b"new").hexdigest())

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(hold_target)
        try:
            assert locked.wait(5)
            replacement = pool.submit(replace)
            # Keep the lock long enough to exercise a failed rename and retry.
            with pytest.raises(TimeoutError):
                replacement.result(timeout=0.2)
        finally:
            release.set()
        holder.result(timeout=5)
        replacement.result(timeout=5)
    assert not source.exists()
    assert target.read_bytes() == b"new"


def test_native_error_is_not_retried_through_python(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows replacement")
    from nexus_launcher import resource_limits

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    calls = []

    def refuse(*args):
        calls.append(args)
        raise OSError("native replacement refused")

    monkeypatch.setattr(paths, "_native", types.SimpleNamespace(
        HANDLE_REPLACE_API_VERSION=1, windows_replace_file=refuse))
    monkeypatch.setattr(resource_limits, "MAX_FILE_BYTES", 2)
    with pytest.raises(OSError, match="native replacement refused"):
        paths.replace_file(source, target, expected_sha256="0" * 64)
    assert calls == [(str(source), str(target), "0" * 64, 2)]
    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"old"
