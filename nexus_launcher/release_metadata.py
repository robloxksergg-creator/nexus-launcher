"""Packaged release identity, with an explicit dedicated tester-build overlay."""

import json
import re
import sys
from pathlib import Path
import nexus_launcher.build_channel as build_channel

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
METADATA = json.loads((ROOT / "assets/release.json").read_text(encoding="utf-8"))
if build_channel.TESTER_BUILD:
    tester = json.loads((ROOT / "assets/tester-release.json").read_text(encoding="utf-8"))
    if tester.get("channel") != "beta" or not isinstance(tester.get("version"), str) or not tester["version"]:
        raise ValueError("Invalid tester release identity")
    METADATA = {**METADATA, **{key: tester[key] for key in ("version", "channel", "status")}}
    if 'trusted_update_keys' in tester:
        beta_keys = tester['trusted_update_keys']
        if (not isinstance(beta_keys, dict) or not beta_keys
                or any(not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key_id)
                       or not isinstance(public, str) or not re.fullmatch(r'[0-9a-f]{64}', public)
                       for key_id, public in beta_keys.items())):
            raise ValueError('Invalid dedicated beta update trust store')
        METADATA = {**METADATA, 'trusted_update_keys': dict(beta_keys)}
if build_channel.PUBLIC_PREVIEW_BUILD:
    if build_channel.TESTER_BUILD or build_channel.STAGING_BUILD:
        raise ValueError('Public preview cannot use tester or staging identity')
    from nexus_launcher import public_update_identity as public
    METADATA = {**METADATA, "version": public.VERSION, "channel": public.CHANNEL,
                "status": "public-managed-preview",
                "trusted_update_keys": {public.KEY_ID: public.PUBLIC_KEY}}
CURRENT_VERSION = METADATA["version"]
