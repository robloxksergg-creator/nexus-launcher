"""Verify local release inventory or downloaded production artifacts. Read-only."""

import argparse
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path

from nexus_launcher.resource_limits import MAX_FILE_BYTES, copy_limited
from nexus_launcher.secure_http import open_https
from nexus_launcher.signed_release import verify_envelope

HOST = "nexusmc.flux-productions.com"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(folder, manifest_name, remote=False):
    envelope = json.loads((folder / manifest_name).read_text(encoding="utf-8"))
    release = verify_envelope(envelope)
    if release["version"] != "0.9.24" or release["available"] is not False:
        raise ValueError("Only the disabled 0.9.24 production manifest may be preflighted")
    artifacts = [
        ("NexusLauncher.exe", release, release["url"]),
        (release["installer"]["file"], release["installer"], release["installer"]["url"]),
        (release["zip"]["file"], release["zip"], release["zip"]["url"]),
    ]
    results = []
    for filename, expected, url in artifacts:
        if remote:
            request = urllib.request.Request(url, headers={"User-Agent": "NEXUS-Release-Preflight/0.9.24"})
            with tempfile.NamedTemporaryFile(delete=False) as output:
                temporary = Path(output.name)
                with open_https(request, timeout=60, allowed_hosts={HOST}) as response:
                    copy_limited(response, output, min(MAX_FILE_BYTES, expected["size"] + 1), timeout=300)
            path = temporary
        else:
            path = folder / filename
        try:
            actual = {"size": path.stat().st_size, "sha256": digest(path)}
            if actual != {"size": expected["size"], "sha256": expected["sha256"]}:
                raise ValueError(f"Artifact mismatch: {filename}")
            results.append({"file": filename, "url": url, **actual})
        finally:
            if remote:
                temporary.unlink(missing_ok=True)
    return {
        "version": release["version"],
        "available": False,
        "remote": remote,
        "manifest_sha256": digest(folder / manifest_name),
        "artifacts": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--manifest", default="manifest.production.disabled.json")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.candidate.resolve(), args.manifest, args.remote)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
