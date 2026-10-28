import json

import pytest
from nexus_launcher.offline_sign_release import external_key_path, generate, promote, sign_candidate
from nexus_launcher.signed_release import verify_envelope


def test_key_generation_never_overwrites(tmp_path):
    path = tmp_path / "fixture.private.pem"
    public = generate(path)
    assert len(bytes.fromhex(public)) == 32
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        generate(path)
    assert path.read_bytes() == original


def test_key_cannot_be_stored_in_project():
    with pytest.raises(ValueError, match="outside"):
        external_key_path(__file__ + ".private.pem")


@pytest.mark.parametrize("envelope", [{}, {"schema": 2, "key_id": []}, {"schema": 2, "key_id": None}])
def test_missing_or_malformed_signature_fails_closed(envelope):
    with pytest.raises(ValueError):
        verify_envelope(json.loads(json.dumps(envelope)))


def test_signer_binds_all_artifacts(tmp_path, monkeypatch):
    import hashlib

    from nexus_launcher.release_metadata import METADATA

    path = tmp_path / "fixture.private.pem"
    public = generate(path)
    monkeypatch.setitem(METADATA, "trusted_update_keys", {"fixture": public})
    payload = {"version": "0.9.24", "channel": "stable", "url": "https://example.test/launcher.exe"}
    for name, field in (("NexusLauncher.exe", None), ("release.zip", "zip"), ("setup.exe", "installer")):
        data = name.encode()
        (tmp_path / name).write_bytes(data)
        inventory = {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if field:
            payload[field] = inventory
            payload[field]["url"] = f"https://example.test/{name}"
        else:
            payload.update(inventory)
    (tmp_path / "manifest.draft.json").write_text(json.dumps(payload))
    output = sign_candidate(path, tmp_path, "fixture")
    envelope = json.loads(output.read_text())
    assert verify_envelope(envelope)["available"] is False
    manifest_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    report = {
        "version": "0.9.24",
        "remote": False,
        "manifest_sha256": manifest_hash,
        "artifacts": [
            {"file": "NexusLauncher.exe", "url": payload["url"], "size": payload["size"], "sha256": payload["sha256"]},
            *[
                {
                    "file": payload[k]["file"],
                    "url": payload[k]["url"],
                    "size": payload[k]["size"],
                    "sha256": payload[k]["sha256"],
                }
                for k in ("installer", "zip")
            ],
        ],
    }
    (tmp_path / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="does not authorize"):
        promote(path, tmp_path, "fixture", output.name, "report.json", "production.json")
    report["remote"] = True
    (tmp_path / "report.json").write_text(json.dumps(report))
    production = promote(path, tmp_path, "fixture", output.name, "report.json", "production.json")
    assert verify_envelope(json.loads(production.read_text()))["available"] is True
    envelope["release"]["zip"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        verify_envelope(envelope)
    (tmp_path / "release.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs"):
        sign_candidate(path, tmp_path, "fixture")
