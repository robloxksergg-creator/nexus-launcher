# NEXUS privacy disclosure — release draft, not approved policy

Maintainer: Икрам (Ikram), ForceCore. This draft records observed client behavior.
Public privacy and account/data deletion request contact:
[teentitans645@gmail.com](mailto:teentitans645@gmail.com).
The owner explicitly selected this address for public use on 2026-10-28.
Requests are reviewed manually; no response deadline, automatic deletion or
verified deletion outcome is promised by listing this contact. Mailbox delivery
and access have not been tested as part of this documentation update.
It is not a claim about verified server retention, infrastructure ownership or
legal compliance. Do not publish it as final without resolving the open items.

| Feature | Observed information / recipient | Trigger and control |
| --- | --- | --- |
| Registration and login | Email or login name, password, challenge/code and device identifier go to the configured NEXUS account API over HTTPS. Source: nexus_account.py and nexus_platform/registration.py. | User submits native forms. Do not send credentials to renderer JavaScript. |
| Session restore | Bearer session token goes to the configured NEXUS API; the launcher reads its session from OS keyring. | May occur on startup; logout is explicit. Token removal is not a guarantee of server-side history deletion. |
| Device identity | A generated persistent device ID is stored locally and used by registration. | Not proof of hardware identity or game ownership. Removal/retention rules require owner review; do not advise deleting it to bypass registration limits. |
| Server status / content / build access | Remote hosts necessarily receive connection IP and request information. Configured world content and account/build access can refresh in the background. | Startup and refresh paths exist in modern_main.py and nexus_platform/window.py. Defaults and opt-outs must be reviewed, not inferred from decorative settings. |
| Mods and game preparation | Providers include Modrinth, CurseForge, Minecraft/loader distribution endpoints and configured pack hosts. Queries/downloads disclose requested resources and connection information to those recipients. | Catalog queries and installation actions. Full transitive endpoint list and vendor policies still required. |
| Support | Submitted text and account-associated requests go to the support service; support history may be fetched while the support UI is active. | User creates/opens an appeal. Do not upload logs, paths or diagnostics without reviewing the actual payload. |
| Local data | Configuration, libraries, worlds, logs, caches and builds are held in local folders chosen by the entrypoint or user. | Uninstall/data deletion needs separate documented choices; removing an EXE does not remove all data or OS keyring credentials. |
| Future downloads | GitHub Releases is the intended launcher download host. | Not enabled by this draft. No automatic update trust or new download URL has been granted. |

## Current known account origins

The default production source configuration references
`https://nexusmc-site.robloxksergg.workers.dev`; dedicated staging configuration
uses a different origin. User-configured endpoints and third-party downloads
must be disclosed separately. No assertion of data residency follows from these
hostnames. A server can observe IP/request metadata even if a client payload
does not explicitly contain them.

## Owner/server facts required before publication

- Confirm operation of the owner-designated public contact above before release.
- Server operator, processors, purposes, retention and deletion behavior.
- Which background collection can be disabled and the effective UI controls.
- What support content/diagnostics is transmitted and any downstream services.
- Exact third-party policies applicable to the enabled candidate features.
- Installation-time disclosure and control required by SignPath eligibility.

Do not promise "no telemetry", "no background traffic", "all data stays local"
or a retention deadline without evidence. No changes to network, account,
retention or consent behavior were implemented by writing this disclosure.
