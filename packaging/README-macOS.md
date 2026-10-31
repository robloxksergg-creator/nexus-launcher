# NEXUS macOS Apple Silicon review build

Initial target: Apple Silicon (M1 or newer), macOS 15 or later. Intel and older
macOS versions have not been qualified. This is a development review build.

Extract the full application bundle and copy `NEXUS Launcher.app` to your
Applications folder. Python, Qt and the Rust extension are included. Java is
not included; Gearmorph needs Java 21 and compatible game entitlement/drivers.
Never run the launcher as root.

User data is stored outside the bundle at
`~/Library/Application Support/NEXUS Launcher`. Session tokens use the macOS
Keychain. Existing Windows/Linux data is not migrated or deleted. There is no
automatic binary updater in this first Mac build.

The bundle is locally ad-hoc signed for executable integrity. It has no Apple
Developer ID certificate and is not notarized by Apple. A successful CI launch
is not proof that Gatekeeper will allow a downloaded copy on your Mac. This
package does not remove quarantine or change Gatekeeper/security settings.

GPL-3.0-only. Copyright 2026 Икрам Ikram / ForceCore. See LICENSE, COPYRIGHT.md
and the bundled third-party-notices. Actual account login, game launch and
downloaded-bundle acceptance require separate real-Mac testing.
