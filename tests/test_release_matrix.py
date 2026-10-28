import hashlib
import http.client
import io
import json
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from nexus_launcher.secure_http import OriginRedirects
from nexus_launcher.updater import ModpackUpdater


def test_redirect_closes_body_without_draining():
    class Socket:
        def makefile(self, *args):
            return io.BytesIO(
                b"HTTP/1.1 302 Found\r\nLocation: https://example.test/next\r\nContent-Length: 999999999\r\n\r\n"
            )

    response = http.client.HTTPResponse(Socket())
    response.begin()
    policy = OriginRedirects({("https", "example.test", 443)})

    def follow(*args, **kwargs):
        assert response.isclosed()
        return "followed"

    policy.add_parent(SimpleNamespace(open=follow))
    request = urllib.request.Request("https://example.test/start")
    request.timeout = 1
    assert policy.http_error_302(request, response, 302, "Found", response.headers) == "followed"


@pytest.mark.parametrize("error", [TimeoutError("deadline"), urllib.error.URLError("unavailable")])
def test_update_endpoint_failure_keeps_verified_offline_pack(tmp_path, monkeypatch, error):
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods/a.jar").write_bytes(b"installed")
    state_dir = tmp_path / ".nexus-launcher"
    state_dir.mkdir()
    state = {"last_successful_update": 1, "managed_files": {"mods/a.jar": hashlib.sha256(b"installed").hexdigest()}}
    (state_dir / "pack.json").write_text(json.dumps(state))
    updater = ModpackUpdater(tmp_path)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("nexus_launcher.updater.fetch_manifest", fail)
    with pytest.raises((TimeoutError, urllib.error.URLError)):
        updater.update_if_needed("https://example.test/manifest")
    assert updater.can_launch_offline()
    operation = state_dir / "file-transaction"
    operation.mkdir()
    assert not updater.can_launch_offline()
    operation.rmdir()
    assert (tmp_path / "mods/a.jar").read_bytes() == b"installed"
    monkeypatch.setattr("nexus_launcher.updater.fetch_manifest", lambda _: None)
    assert updater.update_if_needed("https://example.test/manifest") is None
    (tmp_path / "mods/a.jar").write_bytes(b"corrupt")
    assert not updater.can_launch_offline()


def test_unverifiable_old_journal_blocks_launch_without_destroying_data(tmp_path):
    folder = tmp_path / ".nexus-launcher"
    folder.mkdir()
    journal = folder / "update-transaction.json"
    journal.write_text(json.dumps({"changed": ["mods/a.jar"], "removed": []}))
    (tmp_path / "mods").mkdir()
    target = tmp_path / "mods/a.jar"
    target.write_bytes(b"only surviving copy")
    with pytest.raises(ValueError, match="Legacy journal"):
        ModpackUpdater(tmp_path)
    assert journal.exists()
    assert target.read_bytes() == b"only surviving copy"


def test_concurrent_checks_share_lock_and_retry(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from nexus_launcher.self_update import SelfUpdater

    entered, release = threading.Event(), threading.Event()
    one, two = SelfUpdater(), SelfUpdater()
    one.update_dir = two.update_dir = tmp_path

    def response(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return io.BytesIO(b'{"available":false}')

    monkeypatch.setattr("nexus_launcher.self_update.open_release_url", response)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(one.check)
        assert entered.wait(5)
        try:
            with pytest.raises(RuntimeError):
                two.check()
        finally:
            release.set()
        assert future.result() is None
    assert two.check() is None
