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

Starting with 1.0.8, a dedicated signed Linux update channel is supported.
Users of 1.0.7 and older must install the complete 1.0.8 package once. After
the first responsive launch, NEXUS prepares a private managed copy only if the
installed files match their signed release inventory. Initial preparation needs
network access; failure leaves the original launcher usable and is retried on
the next launch. Preparation does not execute a second launcher concurrently.

Subsequent launches check the Linux feed, verify the complete inactive bundle,
and switch only after the new process acknowledges real UI readiness through
private inherited pipes. The previous signed slot is retained. An uncertain
process or transition blocks further activation rather than forcing a retry.
Update files live under `.launcher-updates` in the data directory; they are
separate from worlds and instances. Do not delete update state while running.
The Windows feed is never used. Root access and security-policy changes are
neither required nor requested.

GPL-3.0-only. Copyright 2026 Икрам Ikram / ForceCore. See LICENSE, COPYRIGHT.md
and the packaged third-party-notices. This is a development review package,
not a statement of cross-platform release readiness.
