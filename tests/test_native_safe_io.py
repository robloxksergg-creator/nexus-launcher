"""Windows handle lifetime and Python/Rust pinning parity on owned temp paths."""

import gc
import os
import types
from pathlib import Path

import pytest

from nexus_launcher import safe_paths as paths


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows directory handle semantics")
    if request.param == "python":
        monkeypatch.setattr(paths, "_native", None)
    elif paths._native is None or getattr(paths._native, "SAFE_IO_API_VERSION", None) != 1:
        pytest.skip("Native safe-IO extension is unavailable")
    return request.param


def test_pin_blocks_parent_and_leaf_rename_then_releases(tmp_path, backend):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    with paths.pinned_directory(child):
        for folder in (child, parent):
            with pytest.raises(OSError):
                folder.rename(folder.with_name(folder.name + "-moved"))
    child.rename(parent / "renamed")
    parent.rename(tmp_path / "moved")


def test_missing_leaf_releases_partially_acquired_handles(tmp_path, backend):
    parent = tmp_path / "parent"
    parent.mkdir()
    with pytest.raises(OSError) as failure:
        with paths.pinned_directory(parent / "missing"):
            pytest.fail("Missing directory must not yield")
    assert failure.value.winerror in (2, 3)
    parent.rename(tmp_path / "moved")


def test_non_directory_failure_releases_parents(tmp_path, backend):
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "file").write_bytes(b"unchanged")
    with pytest.raises((OSError, ValueError)):
        with paths.pinned_directory(parent / "file" / "child", create=True):
            pytest.fail("File ancestor must not yield")
    parent.rename(tmp_path / "moved")
    assert (tmp_path / "moved/file").read_bytes() == b"unchanged"


def test_body_exception_releases_pin(tmp_path, backend):
    folder = tmp_path / "parent"
    folder.mkdir()
    with pytest.raises(RuntimeError, match="consumer"):
        with paths.pinned_directory(folder):
            raise RuntimeError("consumer")
    folder.rename(tmp_path / "moved")


def test_create_unicode_directory_and_nested_pins(tmp_path, backend):
    folder = tmp_path / "nested" / "обновление-🎮" / "leaf"
    with paths.pinned_directory(folder, create=True):
        assert folder.is_dir()
        with paths.pinned_directory(folder):
            (folder / "kept").write_bytes(b"safe")
        with pytest.raises(OSError):
            folder.rename(folder.with_name("moved"))
    folder.rename(folder.with_name("moved"))
    assert (folder.with_name("moved") / "kept").read_bytes() == b"safe"


def native_api():
    if os.name != "nt" or paths._native is None or getattr(paths._native, "SAFE_IO_API_VERSION", None) != 1:
        pytest.skip("Native Windows pin API is unavailable")
    return paths._native


def test_native_handles_have_independent_owners_and_idempotent_close(tmp_path):
    core = native_api()
    folder = tmp_path / "folder"
    folder.mkdir()
    first = core.WindowsDirectoryPin(str(folder))
    second = core.WindowsDirectoryPin(str(folder))
    try:
        first.close()
        first.close()
        with pytest.raises(OSError):
            folder.rename(tmp_path / "moved")
    finally:
        first.close()
        second.close()
    folder.rename(tmp_path / "moved")


def test_native_drop_releases_handles(tmp_path):
    core = native_api()
    folder = tmp_path / "folder"
    folder.mkdir()
    guard = core.WindowsDirectoryPin(str(folder))
    with pytest.raises(OSError):
        folder.rename(tmp_path / "moved")
    del guard
    gc.collect()
    folder.rename(tmp_path / "moved")


def test_native_create_long_directory_with_extended_readback(tmp_path):
    core = native_api()
    folder = tmp_path / ("nested" * 18) / "обновление-🎮" / ("leaf" * 20)
    extended = Path("\\\\?\\" + str(folder))
    moved = extended.with_name("moved")
    guard = core.WindowsDirectoryPin(str(folder), True)
    try:
        assert extended.is_dir()
        with pytest.raises(OSError):
            extended.rename(moved)
    finally:
        guard.close()
    extended.rename(moved)
    assert moved.is_dir()


@pytest.mark.parametrize("create", [False, True])
def test_direct_native_pin_rejects_junction_and_releases_parents(tmp_path, create):
    import subprocess
    core = native_api()
    owned, outside = tmp_path / "owned", tmp_path / "outside"
    owned.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"keep")
    link = owned / "junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                   check=True, capture_output=True)
    try:
        with pytest.raises(ValueError, match="reparse"):
            core.WindowsDirectoryPin(str(link), create)
        assert sentinel.read_bytes() == b"keep"
    finally:
        link.rmdir()  # Only the fixture junction, never its destination.
    owned.rename(tmp_path / "moved")


@pytest.mark.parametrize("path", [
    "relative", "C:relative", r"\\server\share", r"\\?\C:\data", r"\\.\C:\data",
    "C:/data/../other", "C:/data./nested", "C:/data /nested", "C:/NUL/nested",
    "C:/COM¹/nested", "C:/LPT³.txt/nested", "C:/file:stream", "C:/a\0b",
])
def test_direct_native_calls_reject_ambiguous_names_without_network(path):
    with pytest.raises(ValueError):
        native_api().WindowsDirectoryPin(path)


def test_incompatible_native_api_does_not_create_directory(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows native selection")
    folder = tmp_path / "not-created"
    monkeypatch.setattr(paths, "_native", types.SimpleNamespace(SAFE_IO_API_VERSION=999))
    with pytest.raises(ImportError):
        with paths.pinned_directory(folder, create=True):
            pytest.fail("Incompatible extension must not yield")
    assert not folder.exists()


def test_native_failure_is_not_retried_through_python(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows native selection")
    folder = tmp_path / "not-created"

    def refusing(*args):
        raise OSError("synthetic pin failure")

    monkeypatch.setattr(paths, "_native", types.SimpleNamespace(SAFE_IO_API_VERSION=1,
                                                              WindowsDirectoryPin=refusing))
    with pytest.raises(OSError, match="synthetic pin failure"):
        with paths.pinned_directory(folder, create=True):
            pytest.fail("Failed pin must not yield")
    assert not folder.exists()
