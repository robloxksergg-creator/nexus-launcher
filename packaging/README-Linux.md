# NEXUS Linux review build

Initial target: Ubuntu 24.04 desktop, x86-64. Other distributions, older glibc
versions, ARM, Steam Deck and macOS are not qualified by this build.

Extract the entire `NEXUS-Linux-x64` folder into a directory owned by your user.
Keep `_internal` beside `nexus-launcher`. From that folder run:

```sh
./nexus-launcher
```

The tar archive preserves the executable permission. Do not run with sudo or
as root, and do not disable the Chromium sandbox. A normal graphical desktop
session with working Qt/X11 or Wayland system libraries is required. The
package contains Python, Qt and the Rust extension; Java is not included.
Minecraft requires an appropriate installed Java runtime (Java 21 for
Gearmorph), compatible graphics drivers and the necessary game entitlement.
Successful UI smoke tests do not establish a working game launch.

Settings and local instances use `$XDG_DATA_HOME/nexus-launcher`, defaulting to
`~/.local/share/nexus-launcher`. Existing Windows installations are not imported
or removed. Account sessions require an unlocked Secret Service/KWallet backend
in your desktop session. If it is unavailable, sign-in must fail rather than
store the session token in a plaintext fallback.

This first Linux build has no automatic binary replacement. The Windows
bootstrap and Windows update feed are not used. Updates will require a complete
Linux package until a Linux-specific verified updater is implemented.

GPL-3.0-only. Copyright 2026 Икрам Ikram / ForceCore. See LICENSE, COPYRIGHT.md
and the packaged third-party-notices. This is a development review package,
not a statement of cross-platform release readiness.
