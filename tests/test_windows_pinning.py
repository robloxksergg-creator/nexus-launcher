import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from nexus_launcher.safe_paths import atomic_copy, checked_path, pinned_directory, remove_owned_tree, replace_file


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel sharing semantics")
def test_directory_substitution_is_blocked_during_io(tmp_path):
    folder = tmp_path / "original"
    folder.mkdir()
    renamed = tmp_path / "moved"

    def substitute():
        with pytest.raises(OSError):
            folder.rename(renamed)

    with pinned_directory(folder), ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(substitute).result()
        (folder / "kept.txt").write_text("safe")
    folder.rename(renamed)  # The guard releases all handles.
    assert (renamed / "kept.txt").read_text() == "safe"


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace policy")
@pytest.mark.parametrize(
    "root", [r"\\server\share", r"\\?\C:\data", r"\\.\C:\data", "C:/data./nested", "C:/data /nested", "C:/NUL/nested"]
)
def test_unsafe_absolute_roots_rejected_without_network(root):
    with pytest.raises(ValueError):
        checked_path(root, "data.txt")


def test_handle_replace_and_hash_rejection(tmp_path):
    import hashlib

    source, target = tmp_path / "stage", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    with pytest.raises(ValueError, match="hash"):
        replace_file(source, target, expected_sha256="0" * 64)
    assert target.read_bytes() == b"old"
    replace_file(source, target, expected_sha256=hashlib.sha256(b"new").hexdigest())
    assert target.read_bytes() == b"new"
    assert not source.exists()


@pytest.mark.parametrize("filename", ["обновление-🎮.exe", "x" * 180 + ".exe"])
def test_handle_replace_unicode_and_long_path(tmp_path, filename):
    import hashlib

    folder = tmp_path / ("nested" * 15)
    folder.mkdir()
    source, target = folder / "stage", folder / filename
    source.write_bytes(b"verified")
    replace_file(source, target, expected_sha256=hashlib.sha256(b"verified").hexdigest())
    # Match the extended spelling used by handle rename. Ordinary Python path
    # readback can fail at MAX_PATH even when the destination was created correctly.
    readback = Path("\\\\?\\" + str(target)) if os.name == "nt" else target
    assert readback.read_bytes() == b"verified"


def test_handle_verification_size_limit_preserves_original(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows handle verification")
    import nexus_launcher.resource_limits as resource_limits

    monkeypatch.setattr(resource_limits, "MAX_FILE_BYTES", 2)
    source, target = tmp_path / "stage", tmp_path / "target"
    source.write_bytes(b"large")
    target.write_bytes(b"old")
    with pytest.raises(ValueError, match="byte limit"):
        replace_file(source, target, expected_sha256="0" * 64)
    assert target.read_bytes() == b"old"
    assert source.read_bytes() == b"large"


def test_atomic_copy_does_not_write_through_hardlink(tmp_path):
    source, target, outside = tmp_path / "source", tmp_path / "target", tmp_path / "sentinel"
    source.write_bytes(b"restored")
    outside.write_bytes(b"untouched")
    os.link(outside, target)
    atomic_copy(source, target)
    assert target.read_bytes() == b"restored"
    assert outside.read_bytes() == b"untouched"


def test_atomic_copy_corrupt_backup_retains_target(tmp_path):
    source, target = tmp_path / "backup", tmp_path / "target"
    source.write_bytes(b"corrupt")
    target.write_bytes(b"working")
    with pytest.raises(ValueError, match="hash"):
        atomic_copy(source, target, expected_sha256="0" * 64)
    assert target.read_bytes() == b"working"
    assert list(tmp_path.glob("copy-*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_cleanup_and_restore_refuse_junction(tmp_path):
    import subprocess

    outside, owned = tmp_path / "outside", tmp_path / "owned"
    outside.mkdir()
    owned.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"keep")
    link = owned / "junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    try:
        with pytest.raises(ValueError, match="reparse"):
            remove_owned_tree(tmp_path, "owned")
        with pytest.raises(ValueError, match="reparse"):
            atomic_copy(sentinel, link / "sentinel")
        assert sentinel.read_bytes() == b"keep"
    finally:
        link.rmdir()  # Remove only the fixture junction itself.
