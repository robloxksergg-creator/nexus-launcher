# NEXUS 2.0 — polish audit, 2026-10-08

Baseline: `D:/nexus2/backups/source-before-polish-v19`. Git status, branch and HEAD cannot be read: this restored checkout has no `.git` directory. No Git operations are planned.

DESIGN.md and UX-CONTRACT.md remain the presentation contract. Home, Worlds and Profile are the approved benchmark and will retain their layouts. DesignHost, its restricted bridge and native operation owners remain in place.

Observed issues before editing: ProjectBody exposes authored HTML because MarkdownNoHTML disables rendering; New Build inherits a plain, excessively wide label column with an unbounded advanced form; shared empty states stretch into dead space; build cards omit memory/world counts; native context menus and reading typography lack the same finish as the shell. Catalog author fallbacks and excessive version metadata need presentation cleanup.

Scope: safe rich text/media presentation, native dialog/menu composition, reusable cards, empty states and canonical Qt theme. Creation, validation, launch, Java/JVM, instance schema, transfer, backup, network providers, signing and production manifests are protected. A bounded CDN image fetch is presentation media only, following the gallery's existing HTTPS policy.

Baseline known limitation: Windows long-path replacement test (WinError 206). Do not modify nexus_launcher/safe_paths.py to conceal it. Keep the existing migration guards against source-before-ui2-20261008.

Review: real Windows Qt captures at 1280×720, 1366×768, 1920×1080 and 2560×1440, all native detail tabs, collapsed/expanded creation dialog and all ten context actions. Build a separate v19 local candidate; never rebuild over a directory containing user data.
