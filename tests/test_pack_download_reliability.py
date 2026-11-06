"""Offline pack transfers: range integrity, real stream interruptions and local failures."""
import hashlib
import http.client
import io
import ssl

import pytest
from nexus_launcher import updater as module
from nexus_launcher.updater import ModpackUpdater, PackFile


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def setup_transfer(tmp_path, monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    entry = PackFile("x", "x.jar", "1", "mods/x.jar",
                     "https://github.com/fixture", 6, hashlib.sha256(b"abcdef").hexdigest())
    updater = ModpackUpdater(tmp_path / "instance", log=lambda _: None)
    return updater, entry, tmp_path / "cache.part"


def test_broken_body_resumes_missing_bytes(tmp_path, monkeypatch):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    class Broken(Response):
        def read1(self, size):
            if self.tell():
                raise http.client.IncompleteRead(b"", 3)
            return super().read1(3)
    offsets = []
    def opened(request, **kwargs):
        offsets.append(request.get_header("Range"))
        assert kwargs["timeout"] == 30
        return (Broken(b"abc", headers={"Content-Length": "6"}) if len(offsets) == 1 else
                Response(b"def", 206, {"Content-Range": "bytes 3-5/6", "Content-Length": "3"}))
    monkeypatch.setattr(module, "open_https", opened)
    transferred = [0]
    assert updater._download_file(entry, path, transferred, 6) == 6
    assert path.read_bytes() == b"abcdef"
    assert offsets == [None, "bytes=3-"]
    assert transferred == [6]


@pytest.mark.parametrize("headers", [
    {"Content-Range": "bytes 3-5/7"},
    {"Content-Range": "bytes 3-6/6"},
    {"Content-Range": "bytes 2-5/6"},
    {"Content-Range": "bytes 3-5/6", "Content-Length": "2"},
    {"Content-Range": "bytes 3-5/6", "Content-Encoding": "gzip"},
])
def test_invalid_range_is_terminal_without_appending(tmp_path, monkeypatch, headers):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    path.write_bytes(b"abc")
    calls = []
    def opened(*args, **kwargs):
        calls.append(True)
        return Response(b"def", 206, headers)
    monkeypatch.setattr(module, "open_https", opened)
    with pytest.raises(ValueError):
        updater._download_file(entry, path, [0], 6)
    assert calls == [True]
    assert path.read_bytes() == b"abc"


def test_disk_sync_failure_is_not_a_network_retry(tmp_path, monkeypatch):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    calls = []
    def opened(*args, **kwargs):
        calls.append(True)
        return Response(b"abcdef")
    monkeypatch.setattr(module, "open_https", opened)
    monkeypatch.setattr(module.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        updater._download_file(entry, path, [0], 6)
    assert calls == [True]


def test_certificate_failure_is_terminal(tmp_path, monkeypatch):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    calls = []
    def opened(*args, **kwargs):
        calls.append(True)
        raise ssl.SSLCertVerificationError("fixture")
    monkeypatch.setattr(module, "open_https", opened)
    with pytest.raises(ssl.SSLCertVerificationError):
        updater._download_file(entry, path, [0], 6)
    assert calls == [True]


def test_valid_partial_segments_finish_with_full_hash(tmp_path, monkeypatch):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    path.write_bytes(b"abc")
    replies = iter([Response(b"de", 206, {"Content-Range": "bytes 3-4/6"}),
                    Response(b"f", 206, {"Content-Range": "bytes 5-5/6"})])
    monkeypatch.setattr(module, "open_https", lambda *a, **k: next(replies))
    assert updater._download_file(entry, path, [0], 6) == 6
    assert path.read_bytes() == b"abcdef"


def test_callback_failure_does_not_repeat_download(tmp_path, monkeypatch):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    calls = []
    def opened(*args, **kwargs):
        calls.append(True)
        return Response(b"abcdef")
    monkeypatch.setattr(module, "open_https", opened)
    def report(*args):
        raise ValueError("UI fixture")
    with pytest.raises(ValueError, match="UI fixture"):
        updater._download_file(entry, path, [0], 6, emit=report)
    assert calls == [True]


def test_slow_progress_can_continue_beyond_five_minutes(tmp_path, monkeypatch):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    class Slow(Response):
        def read1(self, size):
            clock[0] += 310
            return super().read1(size)
    monkeypatch.setattr(module, "open_https", lambda *a, **k: Slow(b"abcdef"))
    assert updater._download_file(entry, path, [0], 6) == 6


def test_fast_chunks_do_not_flood_persistent_progress(tmp_path, monkeypatch):
    updater, entry, path = setup_transfer(tmp_path, monkeypatch)
    monkeypatch.setattr(module.time, "monotonic", lambda: 1)
    class TinyChunks(Response):
        def read1(self, size):
            return super().read1(1)
    monkeypatch.setattr(module, "open_https", lambda *a, **k: TinyChunks(b"abcdef"))
    events = []
    assert updater._download_file(entry, path, [0], 6, emit=lambda *a: events.append(a)) == 6
    assert [e[2] for e in events if e[0] == "downloading"] == [0, 6]
    assert events[-1][0] == "verifying"
