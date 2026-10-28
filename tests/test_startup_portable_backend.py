import hashlib
import io
import json
from pathlib import Path

import pytest

from nexus_launcher.startup_portable_backend import PackageTransport, PortableStartupBackend
from nexus_launcher.resource_limits import MAX_RESPONSE_BYTES
from nexus_launcher.startup_update_flow import Phase, StartupFlow
from tests.test_portable_bootstrap import Adapter
from tests.test_portable_transition import environment
from tests.test_portable_package import resign


class Transport:
    def __init__(self, source, envelope):
        self.source, self.envelope = source, envelope

    def manifest(self):
        return self.envelope

    def download(self, payload, cache, progress):
        cache.mkdir(exist_ok=True)
        target = cache / "package-fixture.zip"
        target.write_bytes(self.source.read_bytes())
        progress(1, 1)
        return target


class LaunchAdapter(Adapter):
    def launch_current(self, executable, files):
        self.calls.append("current")
        assert executable.parent == files
        assert executable.read_bytes() == b"fixture-not-executable"
        return True


def setup(tmp_path, mode="healthy"):
    root, old, new, keys, envelope, key, source = environment(tmp_path)
    transport = Transport(source, envelope)
    adapter = LaunchAdapter(mode)
    backend = PortableStartupBackend(root, transport=transport, adapter=adapter,
                                     platform="windows", arch="x64", keys=keys)
    return backend, root, old, new, key


def test_flow_composes_real_signature_staging_transition_with_synthetic_process(tmp_path):
    backend, root, old, _, _ = setup(tmp_path)
    flow = StartupFlow(backend, lambda _: None)
    assert flow.run()
    assert flow.view.phase == Phase.READY
    assert json.loads((root / "active.json").read_text())["slot"] != old.name
    assert (root / "user-data.json").read_text() == "unchanged synthetic data"
    assert backend.adapter.calls == ["wait", "launch", "health"]


def test_bad_health_ack_rolls_back_and_offers_installed_without_launching_it(tmp_path):
    backend, root, old, _, _ = setup(tmp_path, "bad-ack")
    flow = StartupFlow(backend, lambda _: None)
    assert not flow.run() and flow.view.offline
    assert json.loads((root / "active.json").read_text())["slot"] == old.name
    assert "current" not in backend.adapter.calls
    assert flow.run(offline=True)


def test_unknown_process_blocks_current_and_future_attempts(tmp_path):
    backend, _, _, _, _ = setup(tmp_path, "unstoppable")
    flow = StartupFlow(backend, lambda _: None)
    assert not flow.run()
    assert flow.view.phase == Phase.BLOCKED
    assert not backend.can_launch_current()
    assert not flow.run(offline=True)


def test_tampered_manifest_cannot_reach_download(tmp_path):
    backend, _, _, _, _ = setup(tmp_path)
    backend.transport.envelope["release"]["version"] = "88.0.0"
    with pytest.raises(ValueError):
        backend.check()


def test_wrong_platform_even_with_valid_signature_is_rejected(tmp_path):
    backend, _, _, _, key = setup(tmp_path)
    backend.transport.envelope["release"]["arch"] = "arm64"
    resign(backend.transport.envelope, key)
    with pytest.raises(ValueError, match="platform"):
        backend.check()


def test_no_native_adapter_is_not_silently_replaced_by_mock(tmp_path):
    with pytest.raises(ValueError, match="adapter"):
        PortableStartupBackend(tmp_path, transport=object(), adapter=None, platform="windows", arch="x64")


@pytest.mark.parametrize("url", ["http://example.test/a", "https://evil.test/a", " https://example.test/a",
                               "https://example.test/a\n", "https://user@example.test/a"])
def test_transport_rejects_untrusted_url_before_io(url):
    with pytest.raises(ValueError):
        PackageTransport(url, allowed_hosts={"example.test"})


class Response(io.BytesIO):
    pass


def test_full_inventory_manifest_can_exceed_legacy_limit_but_remains_bounded():
    transport = PackageTransport("https://example.test/feed", allowed_hosts={"example.test"})
    content = {"fixture": "x" * (160 * 1024)}
    transport._open = lambda _: Response(json.dumps(content).encode())
    assert transport.manifest() == content
    transport._open = lambda _: Response(b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ValueError, match="limit"):
        transport.manifest()


@pytest.mark.parametrize("body,declared,good_hash,success", [
    (b"zip", 3, True, True), (b"zip-extra", 3, True, False),
    (b"z", 3, True, False), (b"zip", 3, False, False),
])
def test_transport_bounds_hashes_and_cleans_only_owned_partial(tmp_path, body, declared, good_hash, success):
    transport = PackageTransport("https://example.test/feed", allowed_hosts={"example.test"})
    transport._open = lambda _: Response(body)
    sentinel = tmp_path / "user-file"
    sentinel.write_bytes(b"preserve")
    payload = {"url": "https://example.test/package.zip", "size": declared,
               "sha256": hashlib.sha256(b"zip" if good_hash else b"other").hexdigest()}
    if success:
        target = transport.download(payload, tmp_path, lambda *_: None)
        assert target.read_bytes() == b"zip"
    else:
        with pytest.raises(ValueError):
            transport.download(payload, tmp_path, lambda *_: None)
        assert not list(tmp_path.glob("package-*.zip"))
    assert sentinel.read_bytes() == b"preserve"
