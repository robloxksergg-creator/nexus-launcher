# NEXUS Launcher

Minecraft launcher and local build library maintained by Икрам (Ikram), ForceCore.
The current application combines a Python/PySide6 desktop shell with a Rust
extension. Migration to Rust is ongoing; this is not an all-Rust application.

## License and attribution

Original first-party code is GPL-3.0-only. See [LICENSE](LICENSE) and
[COPYRIGHT.md](COPYRIGHT.md). Preserve upstream notices; this grant does not
relicense third-party code or Minecraft content. Owner grants for the selected
launcher artwork and icons are recorded in COPYRIGHT.md and the asset inventory.
Public redistribution
readiness is still under review. NEXUS is not an official Minecraft product and
is not approved by or associated with Mojang or Microsoft.

## Code signing policy

See [Code signing policy](docs/CODE-SIGNING-POLICY.md). SignPath Foundation has
not accepted the project and currently does not sign these builds. Windows may
block unsigned executables. Do not disable Windows security as an installation
requirement. A successful source-mode run is not a signed release qualification.

## Build status

Rust verification is defined in `.github/workflows/rust-core-verification.yml`.
The complete unsigned candidate workflow is
`.github/workflows/launcher-candidate.yml`: it builds the Rust extension from the
same checkout, runs tests, collects checksum-pinned source notices, packages the
launcher and executes an offline frozen-UI check. Private CI review of commit
`e34be1dde66e6cba344d0dd140a7a73b46889bcd` passed 34 Rust tests, 85 Python tests
and the packaged UI check. This is not public attestation or SignPath approval.
The candidate spec is `packaging/specs/NexusSignPathCandidate.spec`.

Direct Python requirements are in `requirements.txt` and
`packaging/requirements/`. Rust dependency resolution is in `Cargo.lock`.
No public release or full reproducible-build claim is made by this README.

## Collecting dependency notices

In the intended installed build environment, run:

```text
python -B packaging/collect_python_notices.py --output <new-directory> <distribution> [<distribution> ...]
```

This only reads named installed Python distributions and writes copied texts
and a SHA-256 inventory to a new output directory. It never installs packages,
accesses the network, overwrites an existing output, or grants license clearance.
It does not discover all dependencies or cover bundled native libraries. Missing
notices are errors. Review the output before inclusion in any distributable.

## Public release blockers

See the scoped [readiness audit](docs/SIGNPATH-READINESS-AUDIT-2026-10-28.md)
and [asset inventory](docs/ASSET-LICENSE-INVENTORY.csv). Withdrawal of demo worlds
from the visible catalog does not remove all historical resources from a package
that collects the entire assets directory. The portable spec now uses an explicit
resource selector to exclude retired artwork, demo ZIPs and previews. Historical
specs and previous binaries are not retroactively changed. Owner statements and
GPL-3.0-only grants are recorded for all 30 selected raster/icon resources;
those statements are not independent authentication of creation history.
NEXUS login and game tickets are not Minecraft purchase evidence;
game licensing/entitlement questions remain unresolved for public distribution.

User credentials, device IDs, local libraries, build output and historical private
backups must not be uploaded as source or signing artifacts. A complete privacy
policy and release removal instructions are still required before application.
