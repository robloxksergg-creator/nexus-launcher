"""Release-channel feature gates packaged with the launcher."""

from __future__ import annotations

import json
import os
import nexus_launcher.build_channel as build_channel

from nexus_launcher.release_metadata import ROOT


def _flags() -> dict[str, bool]:
    payload = json.loads((ROOT / "assets/rc-feature-flags.json").read_text(encoding="utf-8"))
    channel = "staging" if os.environ.get("NEXUS_ENVIRONMENT") == "staging" else "playerRc"
    if build_channel.TESTER_BUILD:
        channel = "playerRc"
    selected = payload.get(channel, {})
    return {str(name): value is True for name, value in selected.items()}


def feature_enabled(name: str) -> bool:
    """Fail closed for unknown flags and malformed non-boolean values."""
    return _flags().get(name, False)
