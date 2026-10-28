"""Metadata size parity only; no claims about extraction or archive trust."""
import io
from types import SimpleNamespace
import zipfile

import pytest

from nexus_launcher import resource_limits as limits


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(limits, "_native", None)
    elif getattr(limits._native, "ARCHIVE_API_VERSION", None) != 1:
        pytest.skip("Fresh native archive capability unavailable")


def inventory(sizes):
    entries = [SimpleNamespace(file_size=size) for size in sizes]
    return SimpleNamespace(infolist=lambda: entries)


@pytest.mark.parametrize("sizes,expected", [([], 0), ([0], 0), ([1, 2, 3], 6),
                                          ([limits.MAX_FILE_BYTES] * 4, limits.MAX_EXTRACTED_BYTES)])
def test_valid_inventory(backend, sizes, expected):
    archive = inventory(sizes)
    before = [entry.file_size for entry in archive.infolist()]
    assert limits.validate_archive(archive) == expected
    assert [entry.file_size for entry in archive.infolist()] == before


@pytest.mark.parametrize("sizes,message", [
    ([-1], "Archive file exceeds size limit"),
    ([limits.MAX_FILE_BYTES + 1], "Archive file exceeds size limit"),
    ([10**100], "Archive file exceeds size limit"),
    ([-10**100], "Archive file exceeds size limit"),
    ([limits.MAX_FILE_BYTES] * 4 + [1], "Archive exceeds extracted byte limit"),
    ([limits.MAX_FILE_BYTES] * 4 + [1, 10**100], "Archive exceeds extracted byte limit"),
])
def test_refusal_preserves_inventory_and_error(backend, sizes, message):
    archive = inventory(sizes)
    for _ in range(2):
        with pytest.raises(ValueError, match=f"^{message}$"):
            limits.validate_archive(archive)
        assert [entry.file_size for entry in archive.infolist()] == sizes


@pytest.mark.parametrize("count", [50_000, 50_001])
def test_entry_count_boundary(backend, count):
    archive = inventory([0] * count)
    if count == 50_000:
        assert limits.validate_archive(archive) == 0
    else:
        with pytest.raises(ValueError, match="Too many archive entries"):
            limits.validate_archive(archive)


def test_configured_limits_are_forwarded(backend, monkeypatch):
    monkeypatch.setattr(limits, "MAX_ARCHIVE_ENTRIES", 2)
    monkeypatch.setattr(limits, "MAX_FILE_BYTES", 3)
    monkeypatch.setattr(limits, "MAX_EXTRACTED_BYTES", 5)
    assert limits.validate_archive(inventory([2, 3])) == 5
    for sizes, message in [([3, 3], "extracted byte"), ([4], "file exceeds"),
                           ([-1, 0, 0], "Too many")]:
        with pytest.raises(ValueError, match=message):
            limits.validate_archive(inventory(sizes))


def test_real_zip_metadata(backend):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("config/", b"")
        archive.writestr("config/settings.txt", b"settings")
        archive.writestr("mods/example.jar", b"fixture")
    with zipfile.ZipFile(data) as archive:
        assert limits.validate_archive(archive) == 15
        assert archive.read("config/settings.txt") == b"settings"


def test_old_extension_keeps_compatibility_path(monkeypatch):
    monkeypatch.setattr(limits, "_native", SimpleNamespace(CORE_API_VERSION=1))
    assert limits.validate_archive(inventory([1, 2])) == 3


@pytest.mark.parametrize("version", [1, 99, None])
def test_native_refusal_never_downgrades(monkeypatch, version):
    calls = []

    def refuse(*args):
        calls.append(args)
        raise OSError("native archive refusal")

    monkeypatch.setattr(limits, "_native", SimpleNamespace(
        ARCHIVE_API_VERSION=version, archive_inventory=refuse))
    with pytest.raises(OSError if version == 1 else ImportError):
        limits.validate_archive(inventory([1]))
    assert len(calls) == (1 if version == 1 else 0)


def test_entry_count_checked_before_native_dispatch(monkeypatch):
    monkeypatch.setattr(limits, "MAX_ARCHIVE_ENTRIES", 0)
    monkeypatch.setattr(limits, "_native", SimpleNamespace(ARCHIVE_API_VERSION=99))
    with pytest.raises(ValueError, match="Too many archive entries"):
        limits.validate_archive(inventory([-1]))
