# UX Contract

## Startup package-update contract (2026-10-16)

- StartupFlow owns checking → download → signature/inventory verification →
  startup → authenticated readiness. StartupUpdateWindow projects this state on
  one Qt worker; portable package/transition/bootstrap modules retain authority.
- PortableStartupBackend composes those owners for an already provisioned slot
  installation. HTTPS feed and reviewed native health/process adapter are explicit
  dependencies. No default endpoint, auto-publication, or RC4 migration is enabled.
- Never infer readiness from a constructor, show(), loadFinished or Popen.
  COMPLETE requires the portable bootstrap's authenticated health contract.
- Prelaunch errors permit an explicit retry. An installed-version action appears
  only after signature and complete installed inventory verification, with no
  unresolved transition. No automatic error retry or silent second launch.
- A possible child without confirmed outcome is BLOCKED; no retry/current launch.
  ROLLED_BACK permits recovery only after the bootstrap confirms child exit and
  restores the previous pointer. Raw exception strings never reach presentation.
- Busy operations prevent dialog destruction, Escape and closing. Network reads
  are bounded; a native adapter must also enforce finite process/health deadlines.
  Native deadline/cross-process lease/IPC verification remain release gates.
- This source-level integration does not change tester_main/portable_main or
  distributed RC4. Tests with synthetic process adapters are not native proof.

Continuation: startup_bootstrap_main is the dedicated stable tester bootstrap;
managed_tester_main is its child entry. WindowsProcessAdapter uses inherited
private handles and a session-local lifetime lease shared with the child. Native
Python and frozen Qt fixtures test valid/invalid/missing ACKs; these are not
account-flow or complete application acceptance tests. TesterReadinessProbe
requires initialized services, resolved authentication, a usable native gate or
launcher route, renderer navigation handlers and a subsequent Qt event-loop turn.
First provisioning uses an authenticated exact-slot receipt; it never adopts an
arbitrary RC4 directory. Installed old-package expiry does not invalidate rollback
identity. A dedicated packaged beta trust store leaves stable trust untouched.
The packaged feed policy is currently local-only; enabling a remote feed and
publishing updates remain separate actions. Existing tester data stays at its
established location, with no automatic schema/account-token migration.

## Product context

Russian desktop Minecraft launcher; Qt/PySide6, not Electron. Current portable
NEXUS 2.0 uses DesignHost, a restricted WebEngine shell and existing native
service workspaces. Browser state is a read-only projection, never domain state.
All changes use original services and confirmations. The earlier exact-source
PrototypeHost is a retained reference, not the portable candidate's renderer.
Accessibility: native controls/semantic browser buttons, accessible names,
visible focus, keyboard operation; assistive-technology certification is pending.

## NEXUS 2.0 behavior contract

- Creator Studio property choices use authored keyboard-operable disclosures in assets/studio/workspace.js, scoped to this editor; original select change handlers own values/validation. Studio's model/geometry/file rules remain in approved-ui/index.html. Academy observes semantic commits independently. Other native workflows retain their existing choice owners.

- Canonical navigation: assets/ui2/launcher.js + DesignHost. Collapse retains a
  compact icon rail. Web routes preserve per-route scroll; native library owns
  its existing selection/search state. Original utility routing is mirrored.
- Form/CRUD/confirmation: InstancePage/CreateInstanceDialog/InstanceService and
  existing account dialogs. No second validation, deletion or auth implementation.
- Browser actions: exact same-origin, top-level `/ui-action/<whitelisted action>`.
  Optional one `id` parameter must be bounded ASCII identifier; duplicate keys,
  paths, fragments and foreign origins are denied. Python looks up IDs in owned
  instance items/world models before operations. No URLs/paths from JS are opened.
- State projection exposes nick, real counts, real status, versions and selected
  public metadata only. No token/email/PII/session object serialization. No news,
  authors, achievements, purchases or profile IDs are invented.
- Library read worker is single-flight; errors retain a readable recovery state.
  Mod catalogue keeps generation/timeout/media bounds and busy installation lock.
- Settings and downloads use service-owned config/events in integrated native
  workspaces. Reduced motion updates both browser and native wheel owner.
- Empty/loading/error treatments share explanation and real next action. A
  loading label never implies success. Technical details remain available in logs.
- Locale ru-RU, readable Cyrillic. Native Qt select popups retain standard keyboard
  semantics; Modrinth uses Qt Fusion list popups for consistent dark styling. New HTML catalogue filters are simple pressed buttons.
- Artwork permission does not imply permission to publish a world. Production
  signing/updater endpoints/infrastructure stay outside this presentation scope.

Older exact-preview observations below are historical and do not reauthorize
mock state as current backend data.

## Business-context sources

| Scope | Source | Type |
| --- | --- | --- |
| Permission / publishing | NEXUS_BACKEND_SECURITY_MODEL.md | Existing authority contract |
| Domain lifecycle | NEXUS_CONTROL_PLANE_ARCHITECTURE.md | Existing architecture |
| Baseline / defects | ../NEXUS-Design-Review/OLD-LAUNCHER-AUDIT-2026-10-03.md | Source audit |
| Navigation labels / collapse | User-approved launcher-stage-1 prototype and current request | Explicit user decision |

Billing and legal policy are outside this slice. Existing deletion/retention behavior is unchanged, not newly authorized by this contract.

## Visual contract

DESIGN.md mirrors runtime TOKENS in nexus_launcher/nexus_platform/theme_tokens.py. WorldTheme is independently scoped. `nexus_launcher/nexus_platform/presentation_style.py` replaces the old shell stylesheet rather than layering new CSS over it. InstancePage's local legacy stylesheet is removed by PackLibraryPage; the service/model contract stays unchanged.

## Canonical UI Map

The table below describes the retained native service-workflow owners. PrototypeHost is the separate exact-design renderer: its GET-only loopback assets and same-origin desktop command paths expose login/register/services only, never an arbitrary Python or filesystem API. Prototype CRUD/settings simulations are not authoritative service state; their temporary status is visible in the UI.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Scrollbar | NexusLauncher._style / QScrollArea | Explicit user request + DESIGN.md | Hidden chrome, working wheel/keyboard | Qt geometry + manual wheel pending |
| CRUD | InstanceService + InstancePage | Existing instance schema/services | Existing flows unchanged | Service regressions |
| Navigation | WorldRail signals / PlatformLauncher._navigate | Existing routing | New NexusSidebar adapter | tests/test_next_shell.py |
| Registration | RegistrationDialog / WebsiteRegistrationClient | Existing website email/request-code and auth/register routes | Native Qt two-step form, no new identity provider | tests/test_registration.py |
| Form | RegistrationDialog / NexusLogin / InstancePage | Account and instance service validation | Labeled native Qt fields, sensitive values masked | tests/test_registration.py / tests/test_next_shell.py |
| Select/Listbox | QComboBox / QListWidget | Native Qt keyboard/popup geometry accepted | Catalogue filters and settings | tests/test_mod_catalog.py |

Existing Qt fields, dialogs, selections and feedback remain canonical. RegistrationDialog is the native two-step registration form owner; sign-in reuses LoginDialog and the original account worker. No new session, toast, deletion or browser-privilege primitive is introduced.

Password visibility is owned by `password_visibility.PasswordVisibilityButton`, embedded in each existing QLineEdit in LoginDialog/NexusLogin and RegistrationDialog. It stores only the checked visibility state, exposes native accessible name/checked state and keyboard focus, and never reads or stores password text. Registration password and confirmation toggle independently; hiding a field resets its visibility. Microsoft sign-in is not exposed without a verified server integration; no social-login success or fallback is simulated.

## Navigation and responsive behavior

V12: the shared skin preview has continuous pointer yaw and wrapping Arrow/Page-key rotation, with a one-revolution position slider. Native radio choices select standard 4px / thin 3px arms; geometry and UV crop update without losing pose or decoded texture. Manual model choice and pose persist across profile tabs in the current session, resetting the model choice when the account profile changes. These controls do not upload or change the website skin.

V11: skin preview consumes the existing NexusProfile.skin_png/skin_model from the native signed-in account. It exposes no token, email, remote URL or new network authority to JavaScript. Missing/invalid textures and logout clear the model to grey; 64x32/64x64 PNG under 1 MiB only. This is the NEXUS website profile contract, not Microsoft OAuth nor a Minecraft version-manifest change. Profile content is natural-height with aligned-start rails. Window restoration reapplies bounded normal geometry after the native event-loop transition.

V10: world card open is a native full-card button, not a separate «Посмотреть» action. Save/add remain sibling controls and never open the card. Profile category navigation retains scroll and stable height. First-launch interface sounds default on; the native `UIPreferences` owner persists only soundEnabled between launches. Fixed same-origin sound-on/off commands extend the whitelist; arbitrary paths/arguments/tokens remain blocked. Local banner preview validates and decodes media before applying, cancels stale selections and revokes cancelled blobs; videos are muted with pause/fullscreen and reduced-motion support. No upload, role assignment or public publication is added.

Exact preview v9: Overview owns scene-led discovery. Catalogue search opens Gearmorph as a separate page; new overview/catalogue/server routes support Back/Forward. Public project editing is hidden and handlers deny access by default, independent of the profile-preview checkbox. Local draft editing confers no publication authority. `project_permissions.ProjectAccess` requires a verified session AND verified project creator identity and denies missing/mismatched data. This tested contract is prepared for a future service mutation boundary, not wired backend authorization. No public creator roles are assigned locally; ownership integration is pending. UI hiding alone is not production security.

Navigation opens registered service-backed adapters. The profile button opens a full NexusProfile route; the old downward footer popup is not used. Sign-in uses the existing credential worker through NexusLogin (labeled fields and password reveal). Profile identity comes only from account_profile; editing opens the existing website profile, not a synthetic local identity. My Worlds and Catalogue are separate routes. Saving/un-saving a world updates only local savedWorlds config; it never installs a pack. Settings stay in the footer. Unpinned worlds retain a button object so pinning can reveal them without rebuilding. The hide/show control remains reachable while the sidebar is hidden. Settings no longer require a 900px inner shell and scroll within the content workspace. Start the isolated preview maximized, not exclusive fullscreen.

## Async and resilience

V14: catalogue UI ends search loading after 12 seconds and ignores late responses. Read-only API calls use an 8-second socket timeout and a bounded 64-entry, five-minute memory cache. Icons load independently on four workers, accept only HTTPS cdn.modrinth.com with validated image size and a 1MiB body bound, and never delay results. Project descriptions display as plain text (including Markdown), never untrusted HTML. Packs/mods embed in the main host with a return-to-NEXUS action; old service-shell navigation no longer appears for these commands. Complete retirement of legacy settings/auth/maintenance design remains pending.

Modrinth catalogue: `CatalogProvider` extends the existing HTTPS provider for paged read-only mod search. Native Qt QComboBox owns filter popup geometry and keyboard behavior; native clearable QLineEdit and QListWidget own search and single selection. Explicit Enter/Find submission avoids IME typing dispatch. Editing invalidates results immediately; request generations reject stale responses. A bounded two-worker executor cancels queued obsolete work. Error/empty/loading stay in the fixed header; only results scroll. Version and loader are immutable context from the selected instance. Installation delegates to the original resolver/installer with dependency confirmation, backups, compatibility and SHA-512 checks; duplicate catalogue activation is blocked until completion/cancel/error. Vanilla may browse but cannot install mods. Catalogue search is transient native state, not a shareable URL. Resource packs and shaders are not implemented by this mod-install slice.

Installation/update permissions remain service-owned. Preview blocks automatic account restore/server polling, isolates APPDATA and never starts self-update. Explicit registration and sign-in now contact the real NEXUS account service. No existing credentials are copied into the preview; user-initiated sign-in uses the existing OS keyring and persistent device identity.

Registration source of truth: `E:/nexus-work/website_NexusMC/app/api/auth/email/request-code/route.ts`, `app/api/auth/register/route.ts`, `db/authRateLimit.ts`, `app/api/launcher/auth/login/route.ts`; production website and worker bind the same DB in `wrangler.production.jsonc`. The new client uses the configured account client's base URL, preserving environment selection. It does not create a local user database, bypass email verification/device binding/rate limits, mint sessions, modify server roles, or alter Microsoft authentication. A successful register response leads to the existing sign-in flow with email prefilled and password entered again. Registration is not retried automatically; transport uncertainty says the account may already exist and to check sign-in. Password/code fields are cleared on completion/cancel; no credentials in config or logs. The UI blocks duplicate requests and close while a non-idempotent request is pending. Real email delivery and end-to-end account creation require a user-controlled email and are not claimed by mocked tests.

## Migration status

Pack content tabs are Mods, Resource Packs, Worlds, Data Packs and Shaders. Runtime parameters/files/logs/backups are a separate collapsed maintenance tab group, preserving their original handlers. Non-mod categories read local directory entries without creating files on selection. Data packs are enumerated from saves/<world>/datapacks, not an invented global Minecraft datapacks directory. Non-mod remote catalogue installs and publishing/tutorials remain unimplemented; no disabled feature is represented as connected.

Stage 2: `PackLibraryPage` owns only the compact collection view and local search. Search is transient native-desktop state, not a shareable URL. Card click/keyboard activation opens the existing instance workspace; its back button returns to the collection. Successful original create/import calls `refresh(id)` and opens that instance. Navigation “Мои сборки” always returns to the collection. Original service schemas, installation, mods, backups and launch guards remain authoritative. Twelve protected source/release files must stay byte-identical to the audited candidate baseline (`tests/test_migration_manifest_guard.py`).

Ledger: MIGRATION.md. Preserve original launcher at E:/nexus-work/launcher unchanged. Candidate baseline copied from rc-1.0.0-rc.1-source; release identity remains 1.0.0. Not approved for production distribution until audited P1 defects and integrated regression matrix are closed.

## Verification

V19 presentation polish preserves every original creation field, template
signal, accept validation and apply_options behavior. NativePresentation styles
only the owned CreateInstanceDialog and build QMenu; it removes its application
event filter on accepted host close. Refused close still preserves the draft.
No launch/transfer/mod installation, schema, provider, auth or production release
logic changes. The separate v19 folder is a local candidate, not a new updater
release. Existing user data is copied only after packaging into a fresh folder.

Rich descriptions accept supported presentation tags and inert Markdown.
Script/style/frame/form content is removed, file/data/javascript URLs denied,
and external links require HTTPS plus explicit user activation. Inline media is
limited to the gallery's existing HTTPS CDN, with bounded bytes/dimensions and
stale-result invalidation. Unsupported media is visible as an unavailable
image message. No browser bridge capabilities or CSP allowances were added.
At small windows the complete build detail can scroll; inputs and bottom
actions must be reachable without compressing text into clipped controls.

V13 portable: `nexus_launcher/portable_main.py` sets persistent APPDATA to `data` beside the executable. Source preview remains temporary; do not install real packs in that transient preview. `packaging/specs/NexusPortable.spec` builds a one-folder distribution, with no one-file DLL extraction. Keep `_internal` alongside the executable. Existing installed launcher/configuration are not migrated or overwritten.

`live-services.js` replaces demo pack/mod entry points with fixed same-origin desktop commands. Packs open the existing native collection; mod search opens the canonical native Modrinth catalogue for a selected real instance. No selected instance means create/select one first. These actions currently open a separate service window; web catalogue parity, public publishing and remote non-mod installs remain incomplete. Native WebEngine context menus and page contextmenu events are disabled.

`python -m pytest tests/test_next_shell.py -q -p no:cacheprovider`. Qt offscreen geometry/interaction tests use temporary instance/config directories and suppress all network/account workers. Additional original service tests are run separately. Visual capture, screen-reader, real DPI and live Minecraft acceptance remain mandatory before release.

V20 Modrinth media: install the presentation dependency with
`python -m pip install -r packaging/requirements/requirements-media.txt` before packaging. Search icons
use search payloads; profile icons use their own project payload. Body/gallery
share the verified CDN cache and reject stale generations. Qt rich text resolves
only prevalidated in-memory resources and never loads arbitrary URLs or files.
Gallery captions are plain text. Failed media stays compact and retryable;
missing gallery/icons retain their empty state/placeholder. Author media stays
inside the existing dark layout and shrinks when the viewport narrows.

V21 Markdown parsing also requires `packaging/requirements/requirements-markdown.txt`. The CommonMark
token renderer distinguishes links from images, emits only inert Qt formatting
and validated image markers, and never permits resource loading from authored
HTML. Descriptions with blocked external badge images keep their textual links;
unavailable decorative images do not create repeated error paragraphs. Gallery
and media transport remain the v20 owners. `--self-test-report <path>
--content-smoke` exercises the frozen parser/resource path offline without
creating instances or making network requests. It is a QA-only opt-in flag.


## Controlled tester client
AuthState is the single session owner for tester_main. Startup shows a native gate before any launcher surface; only a valid server profile with tester=true opens the shell. Register reuses the email-verification flow; login reuses NexusLogin. Logout removes only auth state, never projects/instances. Staging Credential Manager namespace is independent from production. Periodic session restore detects expiration. Browser projection includes display name/username only. Test-only email delivery is injected in isolated backend tests; public endpoints never return verification codes.

## Catalog identity compatibility — owner decision 2026-10-25

The owner selected old IDs with both catalog formats readable and conflicts
blocked. `projects.ProjectCatalog` owns this contract; the renderer does not.
The canonical server ID is `main`; `nexus_launcher.main` is an input alias only.
`projects` and `nexus_launcher.projects` are accepted input JSON keys; explicit
saves write the legacy `projects` key. Divergent dual-key values, duplicate JSON
fields, duplicate project IDs, colliding server aliases and unsupported catalog
versions refuse before temporary output/default replacement. No automatic merge
or privilege grant follows from accepting an alias. Existing unknown root,
project and server fields survive explicit saves of retained objects.

Catalog reads project aliases in memory; they do not rewrite a custom unchanged
catalog merely to rename its key/ID. Existing official-server synchronization
continues through the same owner. UI model identity, artwork, selected/pinned/
recent-world projections use canonical IDs. Projection itself performs no disk
IO; normal existing user save actions may persist canonical preferences.
The action identifier grammar remains unchanged; `main` fits it. Gearmorph's
maintenance refusal remains associated with `main`; role/permission identifiers
and account data are outside this catalog change. Visual tokens/layout, account
trust, release gates and installed profiles are not changed.

Evidence: tests/test_catalog_compatibility.py, tests/test_projects.py and
tests/test_config_recovery.py use only temporary catalogs/configurations. Static
UI grammar/model checks are not live Qt/browser navigation evidence.


## Portable registration handoff and account-storage recovery (2026-10-26)

The portable NexusLauncher uses the existing RegistrationDialog/website client.
After confirmed nickname completion, Continue removes the registration surface
and queues the existing NexusLogin with the nickname prefilled and password
focus. It does not reuse a registration password or create a launcher session.
Cancelled or incomplete registration does not queue login. The deferred callback
is bound to the owning QObject and is cancelled on its destruction.

Keyring read/write errors become controlled AccountError feedback. A failed
session save clears the provisional support binding; there is no plaintext token
fallback. The startup restore worker reports AccountError through the existing
account_failed signal, restoring the UI's enabled state. Normal login, profile
verification, session storage and game-ticket authorization keep their owners.

Evidence uses synthetic API/keyring failures and real Qt/WebEngine surfaces:
tests/test_account_storage_failures.py and tests/test_portable_registration_handoff.py.
A live unauthenticated profile GET returned JSON 401; no real account/email-code
or game-login exchange was performed. This is not production admission evidence.

## Deployed registration compatibility (2026-10-28)

RegistrationDialog now collects a Minecraft nickname before requesting the email
code. The deployed register route requires `minecraftNick` in the confirmation
request; the local website source's deferred-profile flow is not the deployed
contract. WebsiteRegistrationClient validates and sends that nickname. A matching
valid nickname in the server's successful user response confirms profile
completion unless `profileCompleted` is explicitly false. Only that confirmed
result enables Continue-to-login; no password is reused or launcher session
created. Missing/deferred profile confirmation retains the existing profile-setup
path. Errors never automatically replay registration. Synthetic tests cover this
compatibility behavior; real email-code completion still requires manual testing.
