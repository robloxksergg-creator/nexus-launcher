# NEXUS Launcher 1.0.4 — coordinated preview

Windows x64, Linux x64 and Apple Silicon macOS packages are built from the same source commit.

## Three shared features
- Instance diagnostics: bounded local mod metadata inspection, nested Fabric inventory and crash-log hints.
- Dependency review: missing-mod candidates and supported version conditions. Unsupported conditions remain unknown; there is no claim to resolve every loader/version rule.
- Reversible diagnostic copies: explicit confirmation creates a separate personal-instance copy with one selected JAR disabled. The original pack and its saves are preserved. Launch uses the normal launcher flow; success is not proof that the selected mod caused a crash.

## Platforms and updates
- Windows: the existing installer downloads the signed NEXUS package. Existing managed installations receive 1.0.4 through the signed manifest feed after publication.
- Linux: Ubuntu 24.04 x64 baseline; extract the full tar.gz and run as your normal desktop user. This release uses manual full-package updates; it does not include a Linux binary auto-updater.
- macOS: Apple Silicon, macOS 15 or newer. Replace the app bundle; user data remains outside it. Manual update only. Intel Macs are not covered.

## Important limits
- Windows EXEs remain without an Authenticode certificate; Smart App Control can block them. NEXUS update signatures do not replace Windows code signing.
- The Mac bundle is ad-hoc signed, without Developer ID or Apple notarization. Gatekeeper acceptance is not guaranteed; no security bypass is included.
- A deeply nested Windows installation can exceed path limits on systems with long paths disabled. Choose a short installation folder; the installer preflight remains fail-closed.
- Native CI includes feature/UI regression tests and Linux/macOS frozen-window smoke tests. It does not qualify real Minecraft launch, every modpack, every Linux distribution, hardware graphics or actual account login on all platforms.
- Second-factor input is present in the client; production website 2FA enrollment is a separate rollout and is not activated by this release.

Source commit: ca1329a019f1a0aad2c620f88579d6a7b396a3c1
GPL-3.0-only. Copyright 2026 Икрам Ikram / ForceCore.
