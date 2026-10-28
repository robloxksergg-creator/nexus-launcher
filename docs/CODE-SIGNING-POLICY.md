# Code signing policy — preparation status

NEXUS Launcher is maintained by Икрам (Ikram), ForceCore.
First-party licensing is described in [COPYRIGHT.md](../COPYRIGHT.md) and
[LICENSE](../LICENSE).

## Current status

SignPath Foundation admission is pending. No subscription, certificate or signing
approval has been obtained. Current builds must not be described as signed by,
approved by, or sponsored by SignPath Foundation. The program's attribution text
will be added only after actual acceptance and enablement.

## Proposed release responsibilities

The owner is the proposed release approver and maintainer. Actual account
identities, MFA enforcement and signing roles must be verified before activation.
Every release requires explicit human approval tied to a reviewed source commit
and the exact artifact digest. CI success alone cannot authorize signing.

Only first-party binaries built from the reviewed published source may be
submitted as first-party code. Upstream runtime DLLs must retain their original
license notices and signatures; inclusion in a package does not make them ours.
Repository workflows and packaging scripts are part of the source review.

## Required checks before submission

Preparation progress: GPL-3.0-only is declared for the three Rust workspace
crates. `packaging/collect_python_notices.py` collects exact notice bytes from
explicit installed distributions with SHA-256 inventory. Its focused tests pass;
it does not establish the complete frozen/native dependency closure. The local
collection and verification results are not an approved public release.

- Resolve all entries in ASSET-LICENSE-INVENTORY.csv for the candidate package.
- Preserve dependency notices and supply corresponding source/build information
  required by the applicable licenses.
- Verify the exact full build and consistent executable product/version metadata.
- Exclude account data, device IDs, credentials, signing keys and private backups.
- Review Git history before making an existing repository public; prefer a
  separately inventoried public candidate over exposing the private backup.
- Document actual network/privacy behavior, installation changes and removal.
- Resolve Minecraft entitlement and redistribution questions identified in the
  readiness audit; NEXUS account identity is not game ownership evidence.
- Verify MFA and human signing approvals. No automatic release authority.

## Privacy disclosure boundary

A final privacy policy is not yet approved. The launcher uses an account service,
device identity, session storage and remote content services. We cannot claim
that it never sends data or that every connection is manually initiated.
Document recipients, data, purpose, retention where known, controls and third-party
policies before a public release. This document is not a substitute privacy policy.

## Distribution — owner direction 2026-10-28

GitHub Releases is the intended download channel for the launcher itself, not a
replacement download location for Gearmorph. No runtime URLs, update trust roots,
server bindings or release feeds have been changed by this decision.

Intended order: reviewed source commit -> full build and tests -> exact candidate
inventory -> Foundation signing approval (only after acceptance) -> verification
of returned signatures and product identity -> archive the complete onedir bundle
with license texts -> human-approved release upload. Do not publish only the EXE:
the sibling runtime and Qt resources are required. Exclude portable user data.
Publish source identity and archive SHA-256 with the release. A GitHub checksum
does not replace Authenticode, and a release on GitHub does not grant Minecraft
rights or Foundation approval. Verify the repository owner and release target
before publishing; the private historical backup must remain private.

Do not attach GitHub PATs to anonymous download requests or embed them in the
launcher. Public download infrastructure must be configured only after the
public candidate and its publication are approved. The existing update verifier
must not be bypassed merely because a file is hosted on GitHub.

Portable candidate selection now uses `packaging/portable_assets.py`; retired
world artwork/ZIPs and preview captures are excluded without deleting originals.
This selection narrows content, not license obligations: retained Gearmorph and
generic artwork still require provenance. Dependency notices collection remains
separate until the exact frozen inventory is complete.

## Dependency intake progress — 2026-10-28

All 166 registry archives referenced by the current Cargo.lock are now accounted
for by SHA-256 against their lock checksums: 158 were cached locally and eight
were fetched from static.crates.io without installing or executing them.
304 license/notice-named files were collected. r-efi 6.0.0 has no separately named
LICENSE file; its AUTHORS, README and Cargo.toml were preserved as additional
upstream attribution/declaration evidence. This does not independently establish
complete license text obligations or clearance for every crate.

These are review artifacts outside the repository. The previously produced
UNSIGNED-REVIEW archive is intentionally unchanged and still contains the older
partial Rust notice set; its embedded warning and checksum remain accurate for
that artifact. Incorporate the reviewed complete set only in a new candidate.
Do not replace historical artifacts or describe a checksum inventory as a
complete SBOM, licensing approval, malware scan or successful signature test.

## Owner media decisions — 2026-10-29

The owner has now expressly stated ownership and permitted GPL-3.0-only
redistribution of Gearmorph artwork, launcher icons, the four minecraft-*.png
decorative images, NEXUS action/navigation icons and sprites, control-panel icons
and the two NEXUS backgrounds. See COPYRIGHT.md and the asset inventory for exact
scope and hashes. Treat these as owner statements and grants, not independent
authentication of creation history. Do not ask the owner to repeat those grants.
Rights in third-party code and the NEXUS/ForceCore brand are not transferred.

The owner selected teentitans645@gmail.com as the public privacy/deletion contact.
No email was sent as part of preparation. Server retention/deletion semantics
and effective privacy controls remain to be verified before finalizing the draft.

## Account and verification status — 2026-10-29

The connected GitHub login was read as `robloxksergg-creator`, matching the
repository owner. The owner states GitHub 2FA is enabled. The available profile
and account API did not return an independent MFA flag, so label this as an owner
confirmation. No security settings or recovery codes were accessed or changed.
SignPath account access/MFA and acceptance are not established.

Private complete-candidate CI for commit
`e34be1dde66e6cba344d0dd140a7a73b46889bcd` passed: 34 Rust tests, 85 Python tests,
checksum-pinned notice collection, complete packaging and offline execution of
the packaged UI. This does not certify licensing, provenance outside the stated
inputs, game entitlement, Foundation approval or public release readiness.
