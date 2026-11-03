# NEXUS Launcher 1.0.6 — Package Protection Preview

Coordinated Windows x64, Linux x64 and Apple Silicon macOS update.

## Changes
- Game-pack admission rejects explicit OS executables, native libraries, shell scripts, shortcuts and ambiguous paths before applying pack files. The same policy covers file manifests and legacy pack ZIPs.
- Manifest parsing rejects duplicate JSON fields and credential-bearing or invalid HTTPS download URLs.
- Bisquit credentials are confined to the configured supported Bisquit panel origin. Forged panel hosts or server-ID paths are refused before the keyring token is read. Other panel providers need independently bound credentials; this release does not grant generic panel trust.
- Developer tooling in the source tree: read-only server-pack onboarding review reports declared content and unresolved publisher/player/tenant trust. It is not an installation approval or antivirus result.
- Source-tree manifest generation accepts explicit pack, Minecraft/loader, game address and GitHub repository parameters for other server owners, retaining the previous Gearmorph defaults.
- Existing pre-installation checks, diagnostics, dependency review and reversible diagnostic-copy features are retained.

## Verification and limits
The complete deterministic source suite passed with the native Rust extension on Windows, Ubuntu 24.04 and macOS 15, including a separately executed legacy Tk window. Rust formatting, Clippy for all workspace components, pure Rust tests and dependency consistency passed. Platform-specific cases and opt-in live-network tests remain skipped where declared. Twelve old migration-baseline comparisons cannot run in CI without their historical local source; they are not counted as PASS.

This is a narrow package-admission policy, not an OS sandbox or malware detector. A JAR or KubeJS file can still execute code with the game user's privileges. Renaming a payload does not prove it harmless. Host tenant authorization, malicious-mod behaviour, real game launch, FPS and downloaded-copy OS reputation are not established by these tests. Gearmorph host-file review remained blocked by the hosting suspension. No hosting permissions, quotas, production account data or C2 gates were changed.

## Platforms and updates
Windows managed installations use the existing signed update feed. The existing online installer EXE is reused unchanged. Short Windows install paths remain recommended when long paths are disabled. Windows EXEs and the native Rust extension have no Authenticode certificate and may be blocked by Smart App Control/Code Integrity. On the owner test machine, Code Integrity blocked the native .pyd in the initial 1.0.5 baseline, so the local update attempt did not reach 1.0.6. The exact signed-package update is therefore tested separately in disposable Windows CI; that does not establish Smart App Control acceptance. A Microsoft Not malware decision for the installer does not cover the native extension.
Linux: Ubuntu 24.04 x64 baseline, full-folder tar.gz; other distributions are not universally qualified. macOS: Apple Silicon and macOS 15+; no Intel build. The Mac bundle is ad-hoc signed without Developer ID or notarization. Linux and macOS updates remain manual. No OS security bypass is included.

GPL-3.0-only. Copyright 2026 Икрам Ikram / ForceCore.
