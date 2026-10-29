import hashlib
import io
import json

import pytest

from nexus_launcher.github_updates import GitHubPackageTransport

BASE = "https://github.com/robloxksergg-creator/nexus-launcher/releases/download/"


@pytest.mark.parametrize("url", [
    "http://github.com/robloxksergg-creator/nexus-launcher/releases/download/v1/a.zip",
    "https://github.com/another/project/releases/download/v1/a.zip",
    BASE + "v1/a.zip?token=secret", BASE + "v1/../a.zip",
    BASE + "v1/%2e%2e.zip", BASE + "v1/a.zip#fragment",
    "https://release-assets.githubusercontent.com/a.zip",
])
def test_untrusted_initial_asset_rejected_before_network(url):
    with pytest.raises(ValueError):
        GitHubPackageTransport(url)


def test_signed_metadata_is_not_replaced_by_github_release_json():
    transport = GitHubPackageTransport(BASE + "updates-stable/envelope.json")
    transport._open = lambda _: io.BytesIO(b'{"schema":2,"signature":"fixture-only"}')
    assert transport.manifest() == {"schema": 2, "signature": "fixture-only"}


def test_download_preserves_existing_hash_size_and_partial_cleanup(tmp_path):
    transport = GitHubPackageTransport(BASE + "updates-stable/envelope.json")
    transport._open = lambda _: io.BytesIO(b"synthetic-zip")
    payload = {"url": BASE + "v2/package.zip", "size": 13,
               "sha256": hashlib.sha256(b"synthetic-zip").hexdigest()}
    target = transport.download(payload, tmp_path, lambda *_: None)
    assert target.read_bytes() == b"synthetic-zip"
    target.unlink()
    payload["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="integrity"):
        transport.download(payload, tmp_path, lambda *_: None)
    assert not list(tmp_path.iterdir())


def test_github_transport_composes_with_signed_v1_to_v2_and_preserves_user_data(tmp_path):
    from tests.test_startup_portable_backend import LaunchAdapter
    from tests.test_portable_package import fixture, resign
    from nexus_launcher.portable_package import stage_portable_archive
    from nexus_launcher.startup_portable_backend import PortableStartupBackend

    archive, envelope, keys, key = fixture()
    package = archive.getvalue()
    root = tmp_path / "installation"
    (root / "slots").mkdir(parents=True)
    source = tmp_path / "fixture.zip"
    source.write_bytes(package)
    envelope["release"].update(version="1.0.0", platform="windows", arch="x64",
                               available=True, url=BASE + "v1/package.zip",
                               size=len(package), sha256=hashlib.sha256(package).hexdigest())
    resign(envelope, key)
    old = stage_portable_archive(source, envelope, root / "slots", keys=keys)
    (root / "active.json").write_text(json.dumps({"slot": old.name}))
    (root / "user-data.json").write_text("unchanged synthetic data")
    envelope["release"].update(version="2.0.0", url=BASE + "v2/package.zip")
    resign(envelope, key)
    transport = GitHubPackageTransport(BASE + "updates-stable/envelope.json")
    transport._open = lambda url: io.BytesIO(
        json.dumps(envelope).encode() if url == transport.manifest_url else package)
    backend = PortableStartupBackend(root, transport=transport, adapter=LaunchAdapter(),
                                     platform="windows", arch="x64", keys=keys)
    release = backend.check()
    downloaded = backend.download(release, lambda *_: None)
    candidate = backend.stage(downloaded, release)
    assert backend.activate(candidate) == "COMPLETE"
    assert json.loads((root / "active.json").read_text())["slot"] != old.name
    assert (root / "user-data.json").read_text() == "unchanged synthetic data"
    assert backend.adapter.calls == ["wait", "launch", "health"]
