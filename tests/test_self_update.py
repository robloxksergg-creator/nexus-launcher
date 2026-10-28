import hashlib
import io
import json
from email.message import Message
from unittest.mock import patch

import pytest
from nexus_launcher.self_update import SelfUpdater, version_tuple


class Reply:
    def __init__(self, payload, content_type="application/json"):
        self.payload = payload
        self.stream = io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(payload) if isinstance(payload, bytes) else 0)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return self.stream.read(_size)


def test_version_comparison():
    assert version_tuple("v0.7.1") > version_tuple("0.7.0")


def test_unsigned_manifest_may_notify_but_cannot_download(tmp_path):
    binary = b"new launcher"
    manifest = {
        "version": "9.0.0",
        "url": "https://nexusmc.flux-productions.com/launcher.exe",
        "sha256": hashlib.sha256(binary).hexdigest(),
    }
    updater = SelfUpdater("https://nexusmc.flux-productions.com/manifest")
    updater.update_dir = tmp_path
    with patch(
        "nexus_launcher.self_update.open_release_url", side_effect=[Reply(manifest), Reply(binary, "application/octet-stream")]
    ):
        release = updater.check()
        assert release is not None
        with pytest.raises(ValueError, match="подписано"):
            updater.download(release)


def test_update_installation_never_executes_a_program(tmp_path):
    import pytest

    with pytest.raises(RuntimeError, match="отключена"):
        SelfUpdater().install_after_exit(tmp_path / "anything.exe")


def test_check_does_not_redownload_identical_running_binary(tmp_path, monkeypatch):
    binary = b"already installed release"
    executable = tmp_path / "NexusLauncher.exe"
    executable.write_bytes(binary)
    manifest = {
        "version": "99.0.0",
        "url": "https://nexusmc.flux-productions.com/launcher.exe",
        "sha256": hashlib.sha256(binary).hexdigest(),
    }
    monkeypatch.setattr("nexus_launcher.self_update.sys.frozen", True, raising=False)
    monkeypatch.setattr("nexus_launcher.self_update.sys.executable", str(executable))
    with patch("nexus_launcher.self_update.open_release_url", return_value=Reply(manifest)):
        assert SelfUpdater("https://nexusmc.flux-productions.com/manifest").check() is None


@pytest.mark.parametrize(
    "version", ["99.0-x/../../escape", "1.2.3/evil", "1.2.3-beta", "1.2", "1.2.3\\evil", "1.2.3:evil"]
)
def test_rejects_unsafe_versions(version):
    with pytest.raises(ValueError):
        version_tuple(version)


@pytest.mark.parametrize(
    "url",
    [
        "http://nexusmc.flux-productions.com/x",
        "https://evil.test/x",
        "https://user@nexusmc.flux-productions.com/x",
        "https://nexusmc.flux-productions.com:444/x",
    ],
)
def test_rejects_untrusted_urls(url):
    from nexus_launcher.self_update import validate_url

    with pytest.raises(ValueError):
        validate_url(url)


def test_rejects_untrusted_redirect():
    from nexus_launcher.self_update import TrustedRedirects

    with pytest.raises(ValueError):
        TrustedRedirects().redirect_request(None, None, 302, "Found", {}, "https://evil.test/evil.exe")


@pytest.mark.parametrize("url", [
    None, 123, "", " https://nexusmc.flux-productions.com/x",
    "https://nexusmc.flux-productions.com/x ",
    "https://nexusmc.flux-productions.com/\nx",
    "https://nexusmc.flux-productions.com/\tx",
    "https://nexusmc.flux-productions.com/\rx",
    "https://nexusmc.flux-productions.com/\x00x",
    "https://nexusmc.flux-productions.com/\x7fx",
])
def test_rejects_ambiguous_url_before_transport(url):
    from nexus_launcher.self_update import open_release_url, validate_url
    from types import SimpleNamespace

    with pytest.raises(ValueError):
        validate_url(url)
    with patch("nexus_launcher.self_update.open_https") as transport:
        with pytest.raises(ValueError):
            open_release_url(SimpleNamespace(full_url=url), timeout=1)
        transport.assert_not_called()


def test_manifest_limit_without_content_length():
    from nexus_launcher.self_update import MAX_MANIFEST_BYTES

    reply = Reply(b"x" * (MAX_MANIFEST_BYTES + 1))
    del reply.headers["Content-Length"]
    with patch("nexus_launcher.self_update.open_release_url", return_value=reply):
        with pytest.raises(ValueError, match="большой"):
            SelfUpdater().check()


def test_startup_only_notifies(monkeypatch):
    import nexus_launcher.self_update as self_update

    release = self_update.LauncherRelease("99.0.0", "https://nexusmc.flux-productions.com/x.exe", "a" * 64)
    monkeypatch.setattr(self_update.sys, "frozen", True, raising=False)
    with patch.object(SelfUpdater, "check", return_value=release), patch.object(SelfUpdater, "download") as download:
        assert self_update.try_startup_update() is False
        assert self_update.startup_release == release
        download.assert_not_called()
    self_update.startup_release = None


@pytest.mark.parametrize("payload", [None, [], "unexpected", 123])
def test_invalid_manifest_type_is_rejected(payload):
    with patch("nexus_launcher.self_update.open_release_url", return_value=Reply(payload)):
        with pytest.raises(ValueError):
            SelfUpdater().check()
