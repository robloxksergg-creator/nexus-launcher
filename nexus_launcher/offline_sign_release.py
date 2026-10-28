"""Operator-only offline signing tool. Never imported by the launcher/build."""

import argparse
import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nexus_launcher.signed_release import canonical, verify_envelope


def external_key_path(value):
    path = Path(value).resolve()
    workspace = Path(__file__).resolve().parents[2]
    if path.is_relative_to(workspace):
        raise ValueError("Private key must be outside the workspace")
    if not path.name.endswith(".private.pem"):
        raise ValueError("Use the ignored .private.pem suffix")
    return path


def generate(path):
    # The operator must first create a private directory with restrictive ACLs.
    if not path.parent.is_dir():
        raise ValueError("Create a protected offline directory first")
    key = Ed25519PrivateKey.generate()
    data = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return key.public_key().public_bytes_raw().hex()


def sign_candidate(
    key_path, folder, key_id, draft_name="manifest.draft.json", output_name="manifest.signed.candidate.json"
):
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Only dedicated Ed25519 keys are supported")
    if Path(draft_name).name != draft_name or Path(output_name).name != output_name:
        raise ValueError("Manifest names must be local filenames")
    payload = json.loads((folder / draft_name).read_text(encoding="utf-8"))
    public = key.public_key().public_bytes_raw().hex()
    from nexus_launcher.release_metadata import METADATA

    if METADATA["trusted_update_keys"].get(key_id) != public:
        raise ValueError("Key is not pinned in launcher release metadata")
    artifacts = [("NexusLauncher.exe", payload)]
    artifacts += [(payload[name]["file"], payload[name]) for name in ("zip", "installer")]
    for name, expected in artifacts:
        if Path(name).name != name:
            raise ValueError("Invalid artifact filename")
        path = folder / name
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected["sha256"] or path.stat().st_size != expected["size"]:
            raise ValueError("Artifact differs from candidate inventory")
    payload.pop("trusted_update_keys", None)
    now = datetime.now(UTC)
    payload.update(
        platform="windows", arch="x64", published_at=now.isoformat(), expires_at=(now + timedelta(days=14)).isoformat()
    )
    # Remains unavailable; signing does not authorize publishing.
    payload["available"] = False
    envelope = {
        "schema": 2,
        "key_id": key_id,
        "release": payload,
        "signature": base64.b64encode(key.sign(canonical(payload))).decode("ascii"),
    }
    verify_envelope(envelope)
    output = folder / output_name
    with output.open("w", encoding="utf-8") as stream:
        json.dump(envelope, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    return output


def promote(key_path, folder, key_id, manifest_name, report_name, output_name):
    for name in (manifest_name, report_name, output_name):
        if Path(name).name != name:
            raise ValueError("Promotion files must be local filenames")
    manifest_path = folder / manifest_name
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = verify_envelope(envelope)
    report = json.loads((folder / report_name).read_text(encoding="utf-8"))
    with manifest_path.open("rb") as stream:
        manifest_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    expected = {
        ("NexusLauncher.exe", payload["url"], payload["size"], payload["sha256"]),
        (
            payload["installer"]["file"],
            payload["installer"]["url"],
            payload["installer"]["size"],
            payload["installer"]["sha256"],
        ),
        (payload["zip"]["file"], payload["zip"]["url"], payload["zip"]["size"], payload["zip"]["sha256"]),
    }
    observed = {(item["file"], item["url"], item["size"], item["sha256"]) for item in report.get("artifacts", [])}
    if (
        payload.get("available") is not False
        or report.get("remote") is not True
        or report.get("version") != payload["version"]
        or report.get("manifest_sha256") != manifest_hash
        or observed != expected
    ):
        raise ValueError("Production download verification report does not authorize promotion")
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Only dedicated Ed25519 keys are supported")
    public = key.public_key().public_bytes_raw().hex()
    from nexus_launcher.release_metadata import METADATA

    if envelope["key_id"] != key_id or METADATA["trusted_update_keys"].get(key_id) != public:
        raise ValueError("Promotion key is not pinned")
    now = datetime.now(UTC)
    production = {
        **payload,
        "available": True,
        "status": "release",
        "published_at": now.isoformat(),
        "expires_at": (now + timedelta(days=14)).isoformat(),
    }
    result = {
        "schema": 2,
        "key_id": key_id,
        "release": production,
        "signature": base64.b64encode(key.sign(canonical(production))).decode("ascii"),
    }
    verify_envelope(result)
    output = folder / output_name
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "sign", "promote"))
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--key-id", default="nexus-launcher-updates-2026-01")
    parser.add_argument("--draft", default="manifest.draft.json")
    parser.add_argument("--output", default="manifest.signed.candidate.json")
    parser.add_argument("--report")
    args = parser.parse_args()
    path = external_key_path(args.private_key)
    if args.action == "generate":
        print(json.dumps({"key_id": args.key_id, "public_key": generate(path)}))
    elif args.action == "sign":
        if args.candidate is None:
            parser.error("--candidate is required for signing")
        print(str(sign_candidate(path, args.candidate.resolve(), args.key_id, args.draft, args.output)))
    else:
        if args.candidate is None or not args.report:
            parser.error("--candidate and --report are required")
        print(str(promote(path, args.candidate.resolve(), args.key_id, args.draft, args.report, args.output)))


if __name__ == "__main__":
    main()
