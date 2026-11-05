# NEXUS macOS Apple Silicon review build

Initial target: Apple Silicon (M1 or newer), macOS 15 or later. Intel and older
macOS versions have not been qualified. This is a development review build.

Extract the full application bundle and copy `NEXUS Launcher.app` to your
Applications folder. Python, Qt and the Rust extension are included. Java is
not included; Gearmorph needs Java 21 and compatible game entitlement/drivers.
Never run the launcher as root.

User data is stored outside the bundle at
`~/Library/Application Support/NEXUS Launcher`. Session tokens use the macOS
Keychain. Existing Windows/Linux data is not migrated or deleted.

Starting with 1.0.8, a dedicated signed Apple Silicon update channel is supported.
Install the complete 1.0.8 app once if upgrading from 1.0.7 or older. After the
first responsive launch, the installed bundle can be checked against its signed
release inventory and copied into private update slots under `.launcher-updates`
in Application Support. Initial preparation needs network access; if unavailable,
the original app remains usable and preparation is retried on the next launch.
Later launches verify inactive updates and require private-pipe UI readiness
before switching the active slot. User worlds and instances remain separate.

The bundle is locally ad-hoc signed for executable integrity. It has no Apple
Developer ID certificate and is not notarized by Apple. A successful CI launch
is not proof that Gatekeeper will allow a downloaded copy on your Mac. This
package does not remove quarantine or change Gatekeeper/security settings.
Quarantine is retained for adopted bundles and applied to downloaded updates.
Quarantined updates must pass the system's read-only execution assessment before
activation. Without Developer ID/notarization, macOS may require its own explicit
user approval or reject a new version. The NEXUS manifest signature is not Apple
publisher trust. If assessment refuses a staged update, the previously verified
slot stays selected; ambiguous process outcomes block further transitions.

GPL-3.0-only. Copyright 2026 Икрам Ikram / ForceCore. See LICENSE, COPYRIGHT.md
and the bundled third-party-notices. Actual account login, game launch and
downloaded-bundle acceptance require separate real-Mac testing.
