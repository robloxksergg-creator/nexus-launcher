import base64
import io
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from nexus_launcher.publishing import BundledCatalogueRepository, CachedCatalogueRepository
from nexus_launcher.remote_publishing import (FallbackWorldCatalogueRepository, RemoteWorldCatalogueRepository,
                               _canonical)


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_args): self.close()


def envelope(private, sequence, worlds):
    payload = {"environment": "staging", "publishedAt": "2026-09-14T00:00:00Z",
               "sequence": sequence, "worlds": worlds}
    return {"schema": 1, "keyId": "staging-test",
            "signature": base64.b64encode(private.sign(_canonical(payload))).decode(), "catalogue": payload}


def test_signed_remote_catalogue_cache_and_anti_rollback(tmp_path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    current = envelope(private, 2, [{"id": "remote"}])
    remote = RemoteWorldCatalogueRepository("https://staging.example.test/api/v1/catalogue/staging",
        {"staging-test": public}, tmp_path / "highest.json", tmp_path / "catalogue.json",
        opener=lambda *_a, **_k: Response(json.dumps(current).encode()))
    assert remote.list_worlds() == [{"id": "remote"}]
    assert json.loads((tmp_path / "highest.json").read_text())["sequence"] == 2
    current.clear(); current.update(envelope(private, 1, [{"id": "old"}]))
    with pytest.raises(ValueError, match="rollback"):
        remote.list_worlds()


def test_invalid_remote_falls_back_to_verified_cache_then_bundled(tmp_path):
    cached_file = tmp_path / "simple-cache.json"
    cached_file.write_text(json.dumps({"worlds": [{"id": "cached"}]}))
    cached = CachedCatalogueRepository(cached_file, lambda x: {w["id"]: w for w in x["worlds"]})
    class Broken:
        def list_worlds(self): raise ValueError("offline")
    fallback = FallbackWorldCatalogueRepository(Broken(), cached, BundledCatalogueRepository([{"id":"bundled"}]))
    assert fallback.list_worlds() == [{"id": "cached"}]
    cached_file.unlink()
    assert fallback.list_worlds() == [{"id": "bundled"}]


def test_production_and_staging_keys_are_not_interchangeable(tmp_path):
    staging, production = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    staging_public = staging.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    signed = envelope(production, 1, [])
    repo = RemoteWorldCatalogueRepository("https://staging.example.test/catalogue", {"staging-test":staging_public},
        tmp_path/"state", tmp_path/"cache", opener=lambda *_a,**_k:Response(json.dumps(signed).encode()))
    with pytest.raises(ValueError, match="signature"):
        repo.list_worlds()


def test_windows_hidden_process_policy(monkeypatch):
    import nexus_launcher.process_utils as process_utils
    monkeypatch.setattr(process_utils.sys, "platform", "win32")
    value = process_utils.hidden_process_kwargs(0x200)
    assert value["creationflags"] & process_utils.subprocess.CREATE_NO_WINDOW
    assert value["creationflags"] & 0x200
    assert value["startupinfo"].dwFlags & process_utils.subprocess.STARTF_USESHOWWINDOW
