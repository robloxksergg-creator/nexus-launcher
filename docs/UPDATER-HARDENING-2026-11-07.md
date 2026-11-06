# Managed updater reliability — 2026-11-07

Scope: existing managed Windows and shared POSIX source. No production feed, release assets, trust keys, OS policy, player data, migrations or installed launcher files are changed by this work. Existing historical installation-contract and release reports remain historical evidence.

## Changes

- Canonical four-component version ordering rejects equivalent spellings such as 1.0.9 and 1.0.9.0 as an upgrade. The installation gate and signed watermark use the same ordering.
- Anonymous transfer has bounded retry counts/time, exponential delays and bounded Retry-After handling. TLS failures/refusals remain terminal; disk/cache/UI callback errors are not retried as network failures. Byte ranges, segment lengths and encoding are validated; signed size and full SHA-256 remain mandatory before staging.
- A managed backend holding its existing trusted adapter's lifetime lease can reconcile PREPARED (cancel before launch), COMMITTING (finish a recorded healthy decision) and ROLLING_BACK (finish a recorded failed decision). Each selected slot and signed history is reverified. LAUNCHING and UNKNOWN stay blocked: no inferred process exit, blind relaunch or forced rollback.
- A completed journal must agree with the selected pointer and package identity. Installed packages must match platform/architecture. This detects pointer-only local rollback; it does not defeat restoring the entire installation/history together.
- Staging consumes only its exact owned cache archive, including on rejection. No recursive cleanup of slots, saves or user directories is introduced.
- Startup failures expose fixed TLS/network/IO/rejection categories without exception text, URLs, paths or credentials. Offline launch remains conditional on installed integrity and resolved process state.

## Evidence

Local Windows/Python 3.12.14: 268 passed, 2 POSIX-only checks skipped across the 15 selected updater suites. Tests include newly generated Ed25519 signatures, controlled stream interruptions, simulated journal-write faults, real subprocess termination of the legacy test helper, and synthetic process adapters for the new managed reconciliation. No game, account or production feed was executed.

Cross-platform workflow: `.github/workflows/updater-hardening-20261107.yml`, one Windows/Linux/macOS job, at most 15 minutes each, no signing/publishing permissions or product secrets. At document creation CI was pending. Final verification: [run 42302472115](https://github.com/robloxksergg-creator/nexus-launcher/actions/runs/42302472115), source commit `46c8db0574de1966e709e5097fe0684e31d28d35`, completed successfully: Ubuntu 24.04 — 270 passed; macOS 15 — 270 passed; Windows 2025 — 268 passed, 2 POSIX-only checks skipped. `packaging/verify_updater_hardening.py` specifies the exact suites and rejects unexpected parent outbound connections.

HTTP transfer interpretation follows [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-content-range). Partial segment length is distinct from complete representation length; a successful transfer still requires the signed complete-file hash.

## Limits and release gates

- This is source hardening, not delivery of a new installer. The deployed bootstrap is a distinct binary; publishing only a new child slot cannot replace that bootstrap. A rebuilt starting package/installer and package-level acceptance are required before users receive these changes.
- CI source tests do not qualify the complete frozen Windows/Linux/macOS builds or Windows SAC/macOS trust approval. Real power loss, hardware write-cache behaviour and directory-entry durability are not proved by injected Python exceptions. Atomic JSON currently flushes file data before replacement; this work does not claim full filesystem/power-loss durability.
- Downloads resume within a transfer's bounded retries. Persistent cross-process download checkpoints and automatic garbage collection of abandoned extraction slots are not introduced.
- Whole-history rollback, signing-key theft/revocation/rotation, a compromised publisher, and an independently trusted latest-head source require their own qualified mechanisms. Existing v2 trust gates are not opened by these changes.
- A surviving/unknown managed child remains a manual reconciliation condition. No prompt or administrator launch bypasses OS security.
- Prior source/user changes are preserved; backups and SHA-256 baselines for the five changed source files are outside the checkout in `D:/nexus2/backups/updater-hardening-20261107`.
