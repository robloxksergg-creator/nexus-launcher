# NEXUS Launcher 1.0.5 — Pre-installation Check Preview

Coordinated Windows x64, Linux x64 and Apple Silicon macOS update.

## New
- “Проверить перед установкой” on the world hero and native world screen.
- Point-in-time RAM, containing-volume free space, Java version and selected-server DNS+TCP checks in a background worker.
- Owner-selected diagnostic design: cyan detail, numbered cards, vector status symbols and readable caveats.
- Explicit start, manual retry, cooperative cancellation and scrollable results with reachable footer actions.
- Previous diagnostics, dependency review and reversible diagnostic-copy features are retained.

## What the results mean
The check does not install files, migrate a pack, start Minecraft, change settings or grant server access. A TCP connection time includes DNS and is not game/ICMP ping or proof that Minecraft is ready. Java is checked only in the selected path, PATH and JAVA_HOME; this is not a complete installed-runtime inventory. Available RAM may be unknown on macOS. Without a complete pack-size requirement, disk sufficiency stays unknown. FPS and download throughput are not measured. System DNS can delay cooperative cancellation.

## Platforms and updates
Windows managed installations use the existing signed update feed. The online installer binary is reused unchanged and downloads the new signed launcher package. Choose a short install folder on Windows systems with long paths disabled. EXEs are still without an Authenticode certificate; Smart App Control can block them.
Linux baseline: Ubuntu 24.04 x64; download/extract the full tar.gz as your normal user. macOS: Apple Silicon, macOS 15+. Linux/macOS updates are manual. Intel Macs and all Linux distributions are not qualified. The Mac app is ad-hoc signed, without Developer ID or notarization; downloaded-copy Gatekeeper acceptance is not guaranteed. No OS security bypass is included.

## Verification scope
Native CI runs model/UI/boundary regressions. Frozen-package checks open the preparation screen using explicitly synthetic data, without live network probes or game launch. Windows update acceptance checks the normal signed bootstrap transition and user-data preservation. These checks do not establish performance or real game launch on every user's machine. Production website 2FA enrollment remains a separate rollout.

GPL-3.0-only. Copyright 2026 Икрам Ikram / ForceCore.
