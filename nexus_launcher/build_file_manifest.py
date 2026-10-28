from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def file_type(path: str) -> str:
    root = Path(path).parts[0].lower()
    return {
        "mods": "mod",
        "config": "config",
        "defaultconfigs": "config",
        "resourcepacks": "resourcepack",
        "shaderpacks": "shader",
        "kubejs": "kubejs",
        "libraries": "library",
    }.get(root, "other")


def github_asset_name(name: str) -> str:
    """Match the filename normalization performed by GitHub Releases."""
    normalized = re.sub(r"[^A-Za-z0-9._+-]+", ".", name)
    return re.sub(r"\.+", ".", normalized)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    args.assets.mkdir(parents=True, exist_ok=True)
    files = []
    for relative, expected in sorted(state["managed_files"].items()):
        source = args.instance / Path(relative)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"Changed managed file: {relative}")
        asset = f"{digest[:16]}--{source.name}"
        remote_asset = github_asset_name(asset)
        target = args.assets / asset
        if not target.exists():
            shutil.copy2(source, target)
        files.append(
            {
                "id": digest[:16],
                "name": source.name,
                "version": "",
                "path": relative,
                "url": (
                    "https://nexusmc.flux-productions.com/api/launcher/empty"
                    if source.stat().st_size == 0
                    else (f"https://github.com/NexusMC202/website_NexusMC/releases/download/{args.tag}/{remote_asset}")
                ),
                "size": source.stat().st_size,
                "sha256": digest,
                "required": True,
                "mode": "required",
                "type": file_type(relative),
            }
        )
    payload = {
        "schemaVersion": 2,
        "pack": "gearmorph",
        "version": args.version,
        "packVersion": args.version,
        "requiredPackVersion": args.version,
        "channel": "stable",
        "minecraft": "1.21.1",
        "loader": "neoforge",
        "loaderVersion": "21.1.248",
        "visibility": "internal",
        "maintenance": False,
        "minecraft_server": "playgearmorph.bisquitmc.net",
        "files": files,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {len(files)} files, {sum(item['size'] for item in files)} bytes")


if __name__ == "__main__":
    main()
