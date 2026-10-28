# SignPath publication readiness audit — 2026-10-28

Result: NOT READY FOR PUBLICATION OR APPLICATION.
Owner selected GPL-3.0 and attribution Икрам (Ikram), ForceCore.
No public repository, signing account, signing certificate, application or
release was created. No existing runtime logic was changed for this audit.

## Scope and evidence

Read-only inventory of 430 working-tree files, including 71 asset files;
169 packages in Cargo.lock; metadata from 44 locally installed Python
distributions. Machine-readable baseline and reports are kept outside the
repository at `D:/nexus2/backups/signpath-audit-20261028/`.
Installed metadata is not a complete inventory of the frozen runtime.
Git history, backup archives, external systems and all downloaded Rust package
sources were not exhaustively audited. This is not a malware certification,
legal opinion or complete license-compliance clearance.

| Area | Observation | Status / required closure |
| --- | --- | --- |
| First-party license | No root license was present. Added GPL-3.0-only text and scoped copyright notice after owner approval. | PARTIAL: verify authorship of imported/copied material before publication. |
| Secret patterns | No matches for private-key headers, GitHub token formats, AWS access-key IDs and selected literal credential assignments in files up to 8 MB. Values were never printed. | PARTIAL: arbitrary credentials, Git history, binary contents and private backups are not cleared. |
| Artwork and packs | 71 asset files lack an established per-file provenance/redistribution ledger. Three ZIP packs have 116, 82 and 3 entries; no JAR/CLASS/EXE/DLL paths or license-named entries were found. | BLOCKED: record origin, author, permission and license, or remove/replace from the public candidate. Filename inspection does not clear nested content. |
| Python dependencies | Metadata for all 44 discovered distributions includes license information and license-related files. PySide6/shiboken expose LGPL/GPL/commercial alternatives; minecraft-launcher-lib is BSD-2-Clause; certifi MPL-2.0; cryptography Apache-2.0/BSD-3-Clause. | PARTIAL: collect actual notices and exact shipped dependency inventory, including Qt modules, Chromium and MSVC runtime redistribution terms. Metadata alone does not prove compliance. |
| Rust dependencies | 169 lock entries; registry entries have checksums. Workspace crates have no declared license metadata. | PARTIAL: review exact transitive license expressions, notices and sources. Checksums are not license evidence. |
| Full build provenance | CI builds/tests the Rust wheel on a restricted branch. The portable spec bundles all assets and does not set EXE version metadata; the latest local development spec is outside the repository. | BLOCKED: one reviewed source-to-full-launcher pipeline, explicit release content, aligned product/version fields and retained artifact identities. Do not sign upstream DLLs as first-party code. |
| Privacy | Account client persists a device ID and sends credentials/device identity to the account service; support/account and background requests exist. | BLOCKED: accurate privacy/network disclosure, presentation and controls required by Foundation policy; do not claim that all networking is explicitly user initiated. |
| Minecraft rights | launcher_core launch options use offline_uuid(username) and token="0". NEXUS game tickets bind NEXUS account identity. These are not proof of Minecraft entitlement. | BLOCKED: assess game licensing/authorization and document a compliant supported flow before promising signing eligibility. No legal violation finding is made solely from the code snippet. |
| Release / uninstall | Current executable is unsigned and SAC-blocked. No Foundation-qualified release/download page or verified uninstall documentation established in this review. | BLOCKED: documented release, installation changes, removal and data-retention behavior. Source-mode success is not packaged-release acceptance. |
| Governance | MFA, human signing approver, public project reputation and Foundation approval not independently established. | UNPROVEN: owner completes account security and role decisions; Foundation independently assesses application. |

## Publication method

Keep the private historical backup private. Prepare a separate reviewed public
candidate with explicit file inventory; do not expose the entire backup or
history. Do not strip required upstream attribution. Preserve source and build
instructions needed to reproduce the distributed binary. An incomplete source
subset cannot be represented as corresponding source for the full release.

GPL protects license conditions and attribution, not exclusive access to the
technology. Forks and commercial redistribution remain permitted under its
terms. Brand policy must not impose extra restrictions on GPL-covered code.
Reserved artwork cannot silently remain a proprietary component of a claimed
Foundation-eligible package: resolve with open licensing or replacement and
confirm the intended package with Foundation.

## Next package

First establish the asset/third-party origin ledger and exact candidate file
inventory. Owner evidence is needed for artwork created or commissioned outside
this repository. Then close notices/privacy/packaging gaps together and verify
the full build. Only after review should the candidate be published and a
Foundation application submitted. Acceptance and future signing are not assured.

## Sources

- https://signpath.org/terms — eligibility, privacy, MFA, build provenance,
  release approval, metadata and reputation requirements.
- https://github.com/spdx/license-list-data/blob/main/text/GPL-3.0-only.txt —
  source of the unmodified license text fetched for LICENSE.
- https://doc.qt.io/qtforpython-6/licenses.html — Qt for Python licensing context;
  review the licenses of the exact shipped 6.8.3 components separately.
- https://www.minecraft.net/en-us/eula
- https://www.minecraft.net/en-us/usage-guidelines

No new compilation, tests, WSL/VM, Windows policy changes or live account
operations were needed. Previous test results are not reissued as new evidence.
