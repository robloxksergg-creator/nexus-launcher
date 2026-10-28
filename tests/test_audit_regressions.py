import hashlib
import io
import json
import os
import threading
import urllib.request
from unittest.mock import patch

import pytest
from nexus_launcher.modrinth_provider import ModInstaller, ModrinthProvider, ProviderError
from nexus_launcher.nexus_account import AccountError, NexusAccountClient, ProtocolError, SessionRejected, TransportError
from nexus_launcher.resource_limits import copy_limited, ensure_space, read_limited, validate_archive
from nexus_launcher.safe_paths import checked_path
from nexus_launcher.secure_http import OriginRedirects, origin
from nexus_launcher.updater import ModpackUpdater, PackRelease
from nexus_launcher.user_instances import InstanceService


@pytest.mark.parametrize(
    "path",
    ["../outside", "mods/NUL.jar", "mods/a. ", "mods/a.", "mods/COM1", "mods/a:stream", "C:/x", "/x", "mods/../x"],
)
def test_invalid_inventory_rejected_before_writes(tmp_path, path):
    game = tmp_path / "game"
    state = game / ".nexus-launcher"
    state.mkdir(parents=True)
    original = json.dumps({"managed_files": {"mods/good.jar": "x", path: "x"}})
    (state / "pack.json").write_text(original)
    updater = ModpackUpdater(game)
    with pytest.raises(ValueError):
        updater._sync_files(PackRelease("test", "", ""))
    assert list(state.iterdir()) == [state / "pack.json"]
    assert (state / "pack.json").read_text() == original


def test_path_sibling_prefix_is_not_containment(tmp_path):
    with pytest.raises(ValueError):
        checked_path(tmp_path / "game", "../game-other/file")


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("existed", [False, True])
def test_crash_recovery_phases(tmp_path, prepared, existed):
    updater = ModpackUpdater(tmp_path)
    target = tmp_path / "mods/x.jar"
    target.parent.mkdir()
    if existed:
        target.write_bytes(b"original")
    updater._write_transaction(["mods/x.jar"], [])
    if prepared:
        updater._prepare_transaction_file("mods/x.jar")
        target.write_bytes(b"changed")
    ModpackUpdater(tmp_path)
    assert target.exists() == existed
    if existed:
        assert target.read_bytes() == b"original"


def test_corrupt_backup_preserves_files_and_journal(tmp_path):
    updater = ModpackUpdater(tmp_path)
    target = tmp_path / "mods/x.jar"
    target.parent.mkdir()
    target.write_bytes(b"original")
    updater._write_transaction(["mods/x.jar"], [])
    updater._prepare_transaction_file("mods/x.jar")
    (updater.state_dir / "backup-files/mods/x.jar").write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        ModpackUpdater(tmp_path)
    assert target.read_bytes() == b"original"
    assert updater.transaction_path.exists()


@pytest.mark.parametrize('headers', [{'Authorization': 'Bearer fixture'}, {'Cookie': 'session=fixture'}])
def test_same_origin_credential_redirect_is_denied(headers):
    request = urllib.request.Request("https://test.invalid/a", headers=headers)
    with pytest.raises(ValueError, match='Credentialed redirects'):
        OriginRedirects({origin(request.full_url)}).redirect_request(
            request, None, 302, "Found", {}, "https://test.invalid/b"
        )


@pytest.mark.parametrize("url", ["https://other.invalid/b", "http://test.invalid/b", "https://test.invalid:444/b"])
def test_credential_redirect_rejected(url):
    request = urllib.request.Request("https://test.invalid/a", headers={"Authorization": "Bearer fake"})
    with pytest.raises(ValueError):
        OriginRedirects({origin(request.full_url)}).redirect_request(request, None, 302, "Found", {}, url)


@pytest.mark.parametrize(
    "digest,success",
    [(None, False), ("wrong", False), ("a" * 128, False), (hashlib.sha512(b"fixture").hexdigest(), True)],
)
def test_modrinth_mandatory_integrity(tmp_path, monkeypatch, digest, success):
    service = InstanceService(tmp_path)
    instance = service.create("Audit", "1.21.1", "vanilla")
    provider = ModrinthProvider()
    version = {
        "id": "v1",
        "project_id": "p1",
        "files": [{"filename": "test.jar", "url": "https://cdn.modrinth.com/test.jar", "hashes": {"sha512": digest}}],
    }
    monkeypatch.setattr(provider, "resolve", lambda *args: [version])
    monkeypatch.setattr("nexus_launcher.modrinth_provider.open_https", lambda *args, **kwargs: io.BytesIO(b"fixture"))
    if success:
        ModInstaller(service, provider).install(instance.id, "p1")
        assert (service.path_for(instance.id) / "mods/test.jar").read_bytes() == b"fixture"
    else:
        with pytest.raises(ProviderError):
            ModInstaller(service, provider).install(instance.id, "p1")
        assert not (service.path_for(instance.id) / "mods/test.jar").exists()


def test_response_and_stream_byte_limits():
    with pytest.raises(ValueError):
        read_limited(io.BytesIO(b"12345"), 4)
    destination = io.BytesIO()
    with pytest.raises(ValueError):
        copy_limited(io.BytesIO(b"12345"), destination, 4)
    assert len(destination.getvalue()) <= 4


def test_archive_entry_and_aggregate_limits(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("nexus_launcher.resource_limits.MAX_ARCHIVE_ENTRIES", 2)
    monkeypatch.setattr("nexus_launcher.resource_limits.MAX_FILE_BYTES", 10)
    monkeypatch.setattr("nexus_launcher.resource_limits.MAX_EXTRACTED_BYTES", 15)
    for sizes in ([1, 1, 1], [11], [8, 8]):
        archive = SimpleNamespace(infolist=lambda sizes=sizes: [SimpleNamespace(file_size=n) for n in sizes])
        with pytest.raises(ValueError):
            validate_archive(archive)


def test_disk_space_preflight(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("nexus_launcher.resource_limits.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(OSError):
        ensure_space(tmp_path, 1)


def test_final_response_url_is_checked(monkeypatch):
    from types import SimpleNamespace

    from nexus_launcher.secure_http import open_https

    closed = []
    response = SimpleNamespace(geturl=lambda: "http://untrusted.invalid/file", close=lambda: closed.append(True))
    monkeypatch.setattr(
        "nexus_launcher.secure_http.urllib.request.build_opener", lambda _: SimpleNamespace(open=lambda *a, **k: response)
    )
    with pytest.raises(ValueError):
        open_https(urllib.request.Request("https://trusted.invalid/file"), 1)
    assert closed == [True]


def test_symlink_destination_rejected(tmp_path):
    game, outside = tmp_path / "game", tmp_path / "outside"
    game.mkdir()
    outside.mkdir()
    sentinel = outside / "x.jar"
    sentinel.write_bytes(b"untouched")
    try:
        os.symlink(outside, game / "mods", target_is_directory=True)
    except OSError:
        pytest.skip("Symlink privilege unavailable on this Windows host")
    with pytest.raises(ValueError):
        checked_path(game, "mods/x.jar")
    assert sentinel.read_bytes() == b"untouched"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_windows_junction_above_nominal_root_is_rejected(tmp_path):
    import subprocess

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "nested").mkdir()
    sentinel = outside / "nested" / "keep.txt"
    sentinel.write_bytes(b"untouched")
    link = tmp_path / "ancestor-link"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, timeout=10)
    if result.returncode:
        pytest.skip("Junction creation unavailable")
    try:
        with pytest.raises(ValueError, match="reparse"):
            checked_path(link / "nested", "keep.txt")
        assert sentinel.read_bytes() == b"untouched"
    finally:
        os.rmdir(link)  # Remove only this fixture junction; never its target.


def test_windows_reparse_attribute_rejected(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    original = Path.lstat
    target = tmp_path / "mods"
    target.mkdir()

    def fake_stat(path):
        if path == target:
            return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
        return original(path)

    monkeypatch.setattr(Path, "lstat", fake_stat)
    with pytest.raises(ValueError):
        checked_path(tmp_path, "mods/x.jar")


@pytest.mark.parametrize(
    "error,deleted",
    [
        (SessionRejected("revoked"), True),
        (TransportError("offline"), False),
        (AccountError("permission denied"), False),
    ],
)
def test_restore_only_deletes_rejected_session(error, deleted):
    client = NexusAccountClient()
    with (
        patch.object(client, "_token", return_value="fake"),
        patch.object(client, "_request", side_effect=error),
        patch("nexus_launcher.nexus_account.keyring.delete_password") as remove,
    ):
        assert client.restore() is None
        assert remove.called == deleted


@pytest.mark.parametrize("data", [b"not-json", b"null", b"[]", b'"text"', b"\xff"])
def test_account_bad_json_becomes_protocol_error(data):
    from email.message import Message

    class Reply(io.BytesIO):
        headers = Message()

    with patch("nexus_launcher.nexus_account.open_https", return_value=Reply(data)):
        with pytest.raises(ProtocolError):
            NexusAccountClient()._request("/api/launcher/profile")


@pytest.mark.parametrize("user", [[], None, {"minecraftNick": 12}, {"minecraftNick": "../path"}])
def test_bad_profile_schema(user):
    with pytest.raises(ProtocolError):
        NexusAccountClient()._profile_from_result({"user": user}, "fake")


def test_atomic_launch_guard_and_finally_release(monkeypatch):
    from types import SimpleNamespace

    from nexus_launcher.modern_main import Launcher

    owner = SimpleNamespace(_launch_lock=threading.Lock())
    queued = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            queued.append(self.target)

    monkeypatch.setattr("nexus_launcher.modern_main.threading.Thread", FakeThread)

    def failed_worker():
        raise ValueError("fixture")

    assert Launcher._start_launch_worker(owner, failed_worker)
    assert not Launcher._start_launch_worker(owner, failed_worker)
    assert len(queued) == 1
    with pytest.raises(ValueError):
        queued.pop()()
    assert not owner._launch_lock.locked()
    assert Launcher._start_launch_worker(owner, lambda: None)
    queued.pop()()
    assert not owner._launch_lock.locked()


def test_launch_guard_released_when_thread_start_fails(monkeypatch):
    from types import SimpleNamespace

    from nexus_launcher.modern_main import Launcher

    owner = SimpleNamespace(_launch_lock=threading.Lock())

    def fail(**kwargs):
        raise RuntimeError("cannot create thread")

    monkeypatch.setattr("nexus_launcher.modern_main.threading.Thread", fail)
    with pytest.raises(RuntimeError):
        Launcher._start_launch_worker(owner, lambda: None)
    assert not owner._launch_lock.locked()


def test_curseforge_cleanup_preserves_unowned_part(tmp_path, monkeypatch):
    from nexus_launcher.curseforge_importer import CurseForgeImporter

    class Reply(io.BytesIO):
        def geturl(self):
            return "https://mediafilez.forgecdn.net/files/example.jar"

    mods = tmp_path / "stage/mods"
    mods.mkdir(parents=True)
    sentinel = mods / "example.jar.part"
    sentinel.write_bytes(b"not owned by downloader")
    monkeypatch.setattr("nexus_launcher.curseforge_importer.open_https", lambda *a, **k: Reply(b"invalid jar"))
    monkeypatch.setattr("nexus_launcher.curseforge_importer.time.sleep", lambda _: None)
    with pytest.raises(RuntimeError):
        CurseForgeImporter(tmp_path / "instance", "test")._download_mod(
            mods, {"projectID": 1, "fileID": 2, "sha256": "0" * 64}
        )
    assert sentinel.read_bytes() == b"not owned by downloader"
    assert list(mods.iterdir()) == [sentinel]


@pytest.mark.parametrize(
    "status,expected", [(401, SessionRejected), (403, AccountError), (429, TransportError), (503, TransportError)]
)
def test_account_http_error_classification(status, expected):
    from urllib.error import HTTPError

    error = HTTPError("https://test.invalid/api", status, "fixture", {}, io.BytesIO(b"not json"))
    with patch("nexus_launcher.nexus_account.open_https", side_effect=error):
        with pytest.raises(expected) as caught:
            NexusAccountClient()._request("/api/launcher/profile", token="synthetic")
    assert type(caught.value) is expected


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_real_windows_junction_is_rejected(tmp_path):
    import subprocess

    game, outside = tmp_path / "game", tmp_path / "outside"
    game.mkdir()
    outside.mkdir()
    sentinel = outside / "original.txt"
    sentinel.write_bytes(b"untouched")
    link = game / "mods"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, timeout=10)
    if result.returncode:
        pytest.skip("Junction creation unavailable")
    try:
        with pytest.raises(ValueError):
            checked_path(game, "mods/original.txt")
        assert sentinel.read_bytes() == b"untouched"
    finally:
        # Remove only the test junction itself; never traverse/delete its target.
        os.rmdir(link)
    assert sentinel.read_bytes() == b"untouched"
