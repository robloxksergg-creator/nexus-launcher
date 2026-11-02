from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit


def validate_profile(pack_id, server, minecraft, loader, loader_version, repository, visibility):
    """Validate publisher-supplied metadata, not publisher identity or safety."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", pack_id):
        raise ValueError("Invalid pack ID")
    endpoint = urlsplit('//' + server)
    if (not endpoint.hostname or endpoint.username or endpoint.password or endpoint.path
            or endpoint.query or endpoint.fragment or any(c.isspace() for c in server)
            or not 1 <= (endpoint.port if endpoint.port is not None else 25565) <= 65535):
        raise ValueError("Invalid game server address")
    if not re.fullmatch(r"1\.\d+(?:\.\d+)?", minecraft):
        raise ValueError("Invalid Minecraft release")
    if loader not in {'vanilla', 'forge', 'neoforge', 'fabric'}:
        raise ValueError("Invalid loader")
    if loader == 'vanilla':
        if loader_version:
            raise ValueError("Vanilla has no loader version")
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}", loader_version):
        raise ValueError("Loader version required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or any(x in {'.','..'} for x in repository.split('/')):
        raise ValueError("Expected GitHub owner/repository")
    if visibility not in {'internal', 'public'}:
        raise ValueError("Invalid visibility")


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
    parser.add_argument("--pack-id", default="gearmorph")
    parser.add_argument("--server-address", default="playgearmorph.bisquitmc.net")
    parser.add_argument("--minecraft", default="1.21.1")
    parser.add_argument("--loader", default="neoforge")
    parser.add_argument("--loader-version", default=None)
    parser.add_argument("--repository", default="NexusMC202/website_NexusMC")
    parser.add_argument("--visibility", default="internal")
    args = parser.parse_args()
    if args.loader_version is None:
        args.loader_version = '21.1.248' if args.loader == 'neoforge' and args.minecraft == '1.21.1' else ''
    validate_profile(args.pack_id, args.server_address, args.minecraft, args.loader,
                     args.loader_version, args.repository, args.visibility)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", args.tag):
        raise ValueError("Invalid release tag")
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
                    else (f"https://github.com/{args.repository}/releases/download/{args.tag}/{remote_asset}")
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
        "pack": args.pack_id,
        "version": args.version,
        "packVersion": args.version,
        "requiredPackVersion": args.version,
        "channel": "stable",
        "minecraft": args.minecraft,
        "loader": args.loader,
        "loaderVersion": args.loader_version,
        "visibility": args.visibility,
        "maintenance": False,
        "minecraft_server": args.server_address,
        "files": files,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {len(files)} files, {sum(item['size'] for item in files)} bytes")


if __name__ == "__main__":
    main()
