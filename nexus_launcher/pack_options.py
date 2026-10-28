from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_RESOURCE_PACKS = ("FreshAnimations_v1.10.4.zip",)
LEGACY_ADDONS = (
    "FA+All_Extensions-v1.8.1.zip",
    "FA+Details-v2.2.1.zip",
    "FA+Objects-v2.1.2.zip",
    "FA+Spiders-v2.2.zip",
    "FA+Emissive-v1.6.zip",
    "FA+Classic_Horses-v1.5.zip",
)
DEFAULT_SHADER = "ComplementaryReimagined_r5.8.1.zip"


def ensure_visual_defaults(instance: Path) -> None:
    """Remove forced add-ons once, then preserve the player's selections."""
    marker = instance / ".nexus-launcher" / "visual-options-user-owned-v1"
    if marker.exists():
        return
    options_path = instance / "options.txt"
    original = options_path.read_text(encoding="utf-8") if options_path.is_file() else ""
    lines = original.splitlines()
    index = next((i for i, line in enumerate(lines) if line.startswith("resourcePacks:")), None)
    if index is None:
        packs = [
            "vanilla",
            "mod_resources",
            *(f"file/{name}" for name in DEFAULT_RESOURCE_PACKS if (instance / "resourcepacks" / name).is_file()),
        ]
        lines.append("resourcePacks:" + json.dumps(packs, ensure_ascii=False, separators=(",", ":")))
    else:
        try:
            packs = json.loads(lines[index].partition(":")[2])
        except (ValueError, TypeError):
            return
        if not isinstance(packs, list) or not all(isinstance(pack, str) for pack in packs):
            return
        retained = [pack for pack in packs if pack not in {f"file/{name}" for name in LEGACY_ADDONS}]
        if retained != packs:
            lines[index] = "resourcePacks:" + json.dumps(retained, ensure_ascii=False, separators=(",", ":"))
    if lines != original.splitlines():
        marker.parent.mkdir(parents=True, exist_ok=True)
        backup = marker.parent / "options-before-visual-migration.txt"
        if options_path.is_file() and not backup.exists():
            backup.write_text(original, encoding="utf-8")
        temporary = options_path.with_suffix(".txt.part")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, options_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
