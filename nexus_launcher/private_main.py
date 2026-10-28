"""Local-only NEXUS Global Update entry point."""

import os
import nexus_launcher.build_channel as build_channel

build_channel.STAGING_BUILD = True
os.environ["NEXUS_PRIVATE_UI"] = "1"
os.environ["NEXUS_DISABLE_SELF_UPDATE"] = "1"
os.environ["NEXUS_ENVIRONMENT"] = "staging"

from nexus_launcher.private_platform import main

raise SystemExit(main())
