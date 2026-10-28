# NEXUS Launcher: assessment for migration to Rust

2026-10-24. Repository assessed: D:/nexus2/launcher-next.
Actual branch read: phase2/trust-key-management. This is NOT the website repository
or its historically reported branch. Analysis only; no migration code, dependency
installation, application launch, network-service probing or user-data modification.
Official technology documentation was read on the web; no project endpoint called.

## 1. Recommendation

Use Rust for the long-term launcher core and retain the existing HTML/CSS/JS visual
assets where useful. Tauri 2 is the strongest current shell candidate because the
project already has a browser presentation layer, not because it guarantees the
fastest UI. First migrate bounded transfer/staging work behind a narrow Python
adapter; retain existing Python install/apply/trust owners until parity is proved.
Replace the Qt host only after identifying and replacing its embedded native pages.

Do not translate all 137 Python files line by line or delete the working launcher.
An eventual Rust core plus web frontend is not an application written entirely in
Rust. A pure Rust UI would be a separate visual/workflow rewrite with substantially
less reuse, and no measured reason presently justifies it.

Before Rust implementation, resolve existing data-contract regressions introduced
during source reorganization. Otherwise Rust could faithfully preserve accidental
new behavior and appear correct against already altered fixtures.

## 2. What changed and what actually exists

The new docs/PROJECT-STRUCTURE.md describes the observed layout:

- nexus_launcher/: runtime services, entry points, build/signing and QA utilities.
- nexus_launcher/nexus_platform/: PySide6 presentation, browser adapters, learning UI.
- tests/: Python/JavaScript tests and fixtures.
- packaging/specs/: 20 PyInstaller specifications; metadata and optional requirements
  are separated from runtime source.
- assets/: existing browser UI, artwork, sample packs and release metadata.
- root nexus_platform/: residual __pycache__ files were observed, not a second
  current source package. Do not delete them as part of this analysis.

Read-only AST inventory (not an executed test suite):

| Metric | Observed value / qualification |
|---|---|
| Python files under nexus_launcher | 137, including previews/build/QA utilities |
| Raw Python lines there | 28,378, including comments/blanks; not an effort estimate |
| Files importing PySide6 | 52 |
| Python files under tests | 88 |
| Statically named test_* functions | 605; parametrization means this is NOT a test-run count |
| AST parse errors in these source/test files | 0 |
| Missing explicit absolute nexus_launcher module targets found by the limited AST check | 0; does not prove relative/dynamic imports or installed dependencies work |
| Assets | 71 files, 30.44 MiB |
| Browser sources | 13 JS, 9 CSS, 2 HTML files |
| PyInstaller specs | 20; multiple historical/test/portable variants, not 20 required Rust products |
| Git tracked baseline | 9 files in one visible commit, 683d49c; most current source/tests/docs/assets are untracked |

Git shows seven old root files deleted, requirements modified and the moved package
untracked. This is consistent with a reorganization but is not a committed complete
source baseline. No reset/stash/checkout/commit was performed. An owner-approved
snapshot/commit or equivalent backup is prerequisite to a broad migration, not
permission for the agent to make one automatically.

Dependencies currently pinned in requirements.txt include PySide6/PyInstaller,
minecraft-launcher-lib 8.0, cryptography, keyring, Argon2, pyotp, qrcode, Pillow,
zxcvbn and newly added tuf/securesystemslib/urllib3. Installation was not verified.
There is no Cargo workspace or Rust implementation established in the inspected
project. Do not confuse package declarations with available build tools.

## 3. Current execution architecture

Observed entry paths are different products/configurations, not interchangeable:

1. stable_main -> PlatformLauncher -> modern_main.Launcher, with native Qt pages.
2. portable_main -> preview_prototype -> NexusLauncher/PlatformLauncher service
   tree -> DesignHost/PrototypeHost browser presentation when NEXUS_UI_2=1.
3. startup_bootstrap_main -> PackageTransport/PortableStartupBackend -> managed
   slots, WindowsLaunchLease/WindowsProcessAdapter and health IPC.
4. tester/private/managed_tester entries additionally select channels and storage.
5. admin.py/control-center, installer and signing/build utilities are separate roles.

The visible browser window is not a detached web frontend. DesignHost dispatches
to private Qt widget methods; some native pages are embedded/reparented into the
browser host. Replacing QWebEngineView with Tauri does not carry those QWidget
pages across. Startup currently constructs a service tree that also constructs UI.

Largest modules: admin.py 2273 lines, modern_main.py 2190, pages.py 1059,
updater.py 994, security.py 980, instance_ui.py 906, window.py 877.
The key extraction target is a headless application service boundary, not Rust
wrappers around QWidget. Separate operation owners from presentation callbacks.

## 4. Findings to resolve before migration

### F1 — confirmed identifier incompatibility after namespace refactoring

projects.py DEFAULT_PROJECTS uses server ID nexus_launcher.main (line 50).
design_bridge.py IDENTIFIER (line 22) accepts ^[A-Za-z0-9_-]{1,128}$ and
DesignPage.acceptNavigationRequest requires it for /ui-action/?id= values.
Static evaluation of the actual regex against the actual server IDs rejects
nexus_launcher.main and accepts building/pinewood/elderfall/tech.

Thus browser actions carrying the first server ID cannot pass that action boundary.
No live UI claim is made: the incompatible constants and guard are source-backed.
Decide whether the persistent ID remains legacy main or requires an explicit data
migration; do not widen an action grammar merely to mask an import-renaming error.

### F2 — confirmed persistent catalog-key change, compatibility risk

ProjectCatalog.load/save now read/write nexus_launcher.projects while format stays 2
(projects.py lines 166/240). The adjacent older source copy at
D:/nexus-work/launcher/projects.py reads/writes projects and uses ID main.
That older copy is a comparison source, NOT an independently approved release baseline.

Current load does not read the old projects key: it falls back to defaults when
the new key is absent. Existing personal entries in old-format catalogs can therefore
be omitted from the loaded result. Conditional subsequent save is possible; this
analysis did not touch or execute against any actual user's catalog.
tests/test_projects.py fixtures were also changed to the new key/ID, so internal
agreement of source/tests does not validate backward compatibility.

### F3 — permission/role/audit strings were also namespaced

security.py declares nexus_launcher.projects.view/create/edit/delete and
nexus_launcher.security.manage; the older adjacent security.py uses projects.view
and security.manage. creator_services.py includes nexus_launcher.admin as a mode;
modrinth_provider.py uses nexus_launcher.projects in audit payloads.

These are data/policy values, not Python imports. The exact effect on each existing
DB/server consumer needs compatibility tests with approved old fixtures; no actual
permission bypass or data loss is claimed from this static inspection. Review each
string replacement separately before defining Rust enums or migration rules.

### F4 — historical verification is not a current package baseline

docs/MIGRATION.md and VERIFICATION.md retain old E: commands and earlier reported
results. tests/test_migration_manifest_guard.py skips when its default E:/... audited
baseline is absent; that directory was checked absent in this environment.
This is an evidence gap, not proof all tests fail. The historical byte guard does
not cover a complete fresh rewrite and normalizes import lines only.

### F5 — package and startup target need a single owner decision

Twenty specs and several entries target different variants. Managed startup,
portable data roots, stable app-data and staging/tester channels have different
contracts. docs/DESKTOP-INSTALLATION-CONTRACT.md is still a design document, not
proof that the final setup/storage transition exists. Choose the supported first
Rust artifact before bundling, migrating paths or replacing the updater.

## 5. Performance: proven code structure vs unmeasured effect

| Area | Current source observation | Rust/architecture opportunity | Evidence still needed |
|---|---|---|---|
| Pack downloads | updater._sync_files loops over pending and awaits each synchronous _download_file before the next | Bounded parallel file downloads, one reusable HTTP client, shared byte/cache budget | End-to-end throughput and failure behavior on representative network/storage |
| HTTP sessions | secure_http.open_https builds a new urllib opener per call; no explicit shared pooling owner in that function | Long-lived reqwest clients separated by credential/origin policy | Actual connection reuse, TLS overhead and provider limits; do not infer whole-app behavior from one function |
| Resume | _download_file already implements Range, 206/Content-Range checking, retries, deadlines, fsync and final SHA-256 | Preserve behavior before improving scheduling; parallel files first, not arbitrary segmentation | Truncation/wrong range/changed content/disconnect tests and cancellation boundary |
| Hash/IO | Existing files and staged files are read to verify hashes; can_launch_offline hashes managed files; mod installer streams SHA-512 | Stream download+digest, bounded verification workers and explicit verification modes | Hash throughput and disk-read amplification; hashlib is native-backed, so Rust is not automatically faster |
| Apply/recovery | Journals/backups, fsync and safe replace exist in updater.py and file_transaction.py | Maintain single apply owner; batch only where crash semantics remain proved | Failure/restart/disk-full/rollback tests, not removing fsync for a benchmark |
| Startup/UI memory | Qt service/page construction plus QWebEngine-based presentation; DesignHost polls state at 750ms and library at 5s | Headless Rust core and one presentation host; lazy routes and coalesced events | Measured startup, full process-tree RSS/working set, idle CPU and event latency |
| Assets | 30.44 MiB, dominated by PNG artwork; AssetServer eagerly read_bytes resources into a whitelist dictionary | Thumbnail/lazy resource loading and explicit decoded-image cache budget | Loaded-route measurements; file size is not decoded GPU/CPU image memory |
| UI progress | Worker callbacks/signals and repeated display projections | Bounded event queue/coalesced progress, immediate terminal/error events | Cancellation responsiveness and update frequency under many small files |

No CPU/RAM/FPS/network or launch benchmark was run. No honest multiplier or exact
memory/startup saving can be promised. A larger language rewrite cannot exceed
network/CDN/disk limits and cannot improve Java's game FPS merely by being Rust.

## 6. Recommended target architecture

Long-term: existing HTML/CSS/JS visual assets -> typed Tauri commands/events ->
headless Rust application core -> HTTP/filesystem/Java/platform adapters.
Browser gets sanitized projections, never tokens, passwords, arbitrary paths,
shell commands or raw domain objects. Backend validates IDs, auth/session generation,
operation ownership, paths and origins even if UI buttons are enabled.

Start with a small Cargo workspace when implementation is authorized:

- crates/nexus-core: domain DTOs/errors, transfer scheduler, staging/inventory and
  later install/launch/account/update modules. Keep modules together until actual
  independent dependency/ownership reasons justify more crates.
- crates/nexus-python: temporary PyO3 boundary for existing Python launcher.
- desktop/src-tauri: later thin Tauri host using the same core; no business logic
  tied to Tauri types inside nexus-core.
- frontend: existing browser assets migrated route by route; choose TypeScript for
  future IPC typing if approved, not an automatic React/Vue rewrite.

These are proposed paths, NOT directories created by this assessment. Do not put
all business logic into main.rs, expose unrestricted filesystem/process commands,
or build eight speculative crates before a first consumer exists.

### Technology choices to qualify, not silently install

| Concern | Candidate / rule |
|---|---|
| Async HTTP | Tokio + reused reqwest Client; explicit HTTPS/origin/redirect policy, credentialed redirects denied, time/size/concurrency limits |
| CPU/IO | Bounded worker pool; spawn_blocking for blocking work with explicit concurrency limits, not one task per file without bounds |
| Data model | serde DTOs with exact version/unknown-field policy. Security JSON needing duplicate-key rejection requires an explicit duplicate-aware path, not plain map deserialization |
| Integrity | Existing SHA-256/SHA-512 and exact signed bytes preserved; reviewed standard implementations, never homemade crypto |
| Credentials | OS credential store with exact existing service/account identity and staging separation; no transfer to renderer/localStorage/plaintext |
| Update trust | Preserve existing Ed25519 protocol and separately qualified TUF semantics. tough/rust-tuf are candidates, not automatic drop-in equivalents to Python tuf |
| Windows OS | Explicit handle ownership, leases, reparse-safe paths, replacement and child wait/health IPC; use reviewed Windows bindings, not just generic Path canonicalization |
| UI | Tauri 2 candidate. Reuse visual assets, replace Python navigation bridge with narrowly scoped commands; configure CSP/capabilities and navigation restrictions |
| Python transition | PyO3/maturin candidate with release of Python thread attachment for long blocking work and correct callback/lifetime handling; packaging of native extension must be exercised |

Tauri uses system WebView2/WKWebView/WebKitGTK; the current Qt Chromium behavior
does not establish rendering parity on those engines. Native Rust UI is an option
only after a measured visual/workflow comparison; it would discard more existing UI.

## 7. Module-by-module migration map

| Domain / current owners | Preserve | Migration difficulty / order |
|---|---|---|
| projects.py, user_instances.py, runtime_settings.py, config.py, pack_options.py | IDs, schema/defaults, paths, enum behavior, ordered args, game version/Java mapping | Medium; establish golden fixtures first, including pre-refactor catalogs |
| secure_http.py, resource_limits.py, updater._download_file | HTTPS origin/redirect policy, credentials separation, limits, resume/hash behavior | Medium/high; first performance slice |
| updater.py, file_transaction.py, safe_paths.py, update_state.py | Allowed roots, preserve/optional files, backups/journal/recovery, locks, reparse protections | High; apply remains Python until differential/fault parity |
| launcher_core.py, loader_providers.py, platform_support.py | Vanilla/Fabric/Forge/NeoForge metadata/inheritance/arguments, Java selection, logging | High; minecraft-launcher-lib is substantial functionality, not a single Rust spawn call |
| nexus_account.py, registration.py, auth_state.py, launch_identity.py | API/error semantics, keyring identity, persistent device ID, account-generation-bound ticket issuance | High security/compatibility; retain server contract, do not rewrite website/backend |
| signed_release.py, update_v2_trust.py, portable_*, startup_* | Canonical signature bytes, anchor/state/version/expiry rules, signed slots, active pointer and health transitions | Very high; separate final migration track, no reset or downgrade fallback |
| modrinth_provider.py, curseforge_importer.py, instance_transfer/backups.py | Dependency resolution, file identity/hash, zip/path limits, user saves, atomicity boundaries | Medium/high; reuse corpus and separate provider metadata from installer |
| modern_main.py / window.py / next_shell.py / design_bridge.py | Actual operations and route/error states, sanitized display and explicit action validation | High structural coupling; extract headless service API before replacing host |
| learning/*, studio_ui.py, creator_services.py, admin.py | Content/progress/project formats, permissions, export/publish roles | Later independent features; not prerequisites to first Rust download implementation |
| packaging/specs, build/signing utilities | Reproducible artifact identity/channel/update compatibility | High release risk; build a new candidate artifact, never replace deployed feed implicitly |

Current launcher_core.launch constructs offline UUID/token=0 options and obtains
a separate NEXUS game ticket just before launch. This is not evidence of a complete
Microsoft/Xbox/Minecraft ownership-login implementation. Do not accidentally claim
such support after translation or merge NEXUS credentials with game authentication.

## 8. Compatibility contracts that must be frozen

1. Persistent catalog/config/instance/backup/learning formats and stable IDs. New
   namespace for code must not rename JSON keys, permission strings or resource IDs.
2. User-data roots: normal/staging/tester/managed portable; active.json,
   transition.json, slot/data mapping and recoverability. No real user saves used
   for migration tests; old readable copies/backups are retained until acceptance.
3. Account wire/error contract: explicit 401 rejection vs transport/protocol failure;
   network loss must not erase a valid session; device and keyring identities stable.
4. Launch descriptor: Java executable/version, ordered args, cwd/environment,
   NEXUS_GAME_TICKET lifetime/redaction and original child ownership.
5. Download contract: trusted hosts/redirects, sizes/hashes, resume/deadline/retry
   limits, safe cancellation, never apply unverified or partially downloaded bytes.
6. Signed release canonicalization: Python json.dumps sort_keys/separators,
   ensure_ascii=True/allow_nan=False is not automatically byte-identical to serde_json.
   Unicode/escaping/numbers and TUF canonical rules need separate golden vectors.
7. Lock/journal/replace semantics and OS-specific ownership; Windows sharing,
   delete/reparse/handle rules are not inferred from Rust memory safety.
8. Typed service/UI events: operation ID, instance ID, generation, terminal/error
   states, bounded/redacted payloads. Exact DTO/version needs explicit review.

Unknown fields must not be silently dropped when roundtripping user data. For
security envelopes exact-key/duplicate rules come from the relevant protocol,
not a blanket one-size-fits-all JSON policy. Do not reuse the website C2 development
contracts as automatic authorization for launcher migration or production trust.

## 9. Recommended execution sequence (not executed)

| Stage | Concrete output | Acceptance before next stage |
|---|---|---|
| 0 stabilize current relocation | Reviewed import-only refactor, catalog/permission/ID regression decisions, reproducible source snapshot, one selected candidate entry/channel | Legacy fixtures retain same IDs/data/permissions; no unintended import-to-data replacement; baseline complete |
| 1 record real baseline | Disposable profiling harness and portable golden corpus for models/launch/download/update/errors | Current supported workflows and failures have actual results; no skipped legacy-baseline guard masquerades as coverage |
| 2 Rust transfer slice behind Python | nexus-core transfer planning + bounded download/hash/staging, narrow Python adapter, no final install/update authority | Same verified staged files/errors as Python; resume/cancel/limits/redirect rules pass; measured representative benefit |
| 3 storage/instances and transactions | Rust state model/readers, explicit format migration if needed, one mutation/apply owner | Differential fixtures plus disk-full/permission/failure/recovery tests; old data readable and no dual writers |
| 4 Minecraft provisioning/launch | Rust metadata/install/loader/Java/command logic replacing minecraft-launcher-lib responsibility incrementally | Supported version/loader/OS matrix; command snapshots redact secrets; actual authorized game smoke and exit handling |
| 5 account/provider services | Rust API/keyring/device/ticket and Modrinth/CurseForge boundaries | Contract/error parity; account switch/revocation/transport failure; no credential leaks or changed keyring namespace |
| 6 thin Tauri shell | Reused browser presentation with native Qt workflows replaced individually | Required routes/features, resize/DPI/accessibility/media/keyboard and startup/memory acceptance; no hidden Python UI dependency |
| 7 updater/bootstrap | Independently reviewed Rust implementation of existing signed release/slot/health/TUF contracts | Golden signatures/canonical bytes, downgrade/expiry/rotation/restart/rollback and bootstrap ownership evidence; no trust reset |
| 8 release parity/cutover | Separate signed candidate, installation/update/recovery and platform matrices, rollback instructions | Owner explicitly accepts supported feature set and release; deployed updater/feed unchanged until authorized |

Stages may be reordered by actual measured bottleneck/consumer dependencies, but
no stage may drop a security owner or require two runtimes to mutate one installation
concurrently. An early Rust Tauri prototype cannot replace missing native Qt pages.
No credible schedule follows from LOC alone; estimate after the first bounded slice
demonstrates actual Rust integration/build/test throughput.

### First practical slice

After stage 0/1, implement the transfer engine as a real consumer-backed slice:
Python supplies a bounded operation plan under existing trusted policy; Rust owns
only its staged download work. Initially Python still independently validates staged
hashes and owns final apply/recovery, avoiding a trust downgrade. Progress/error
DTOs cross a narrow adapter; do not pass QWidget, callbacks with arbitrary authority
or arbitrary shell commands. Cancellation stops download at a safe boundary, not a
half-applied filesystem transaction. Measure extra verification IO explicitly.

PyO3 is recommended for this transition because existing consumer is Python;
the final Rust core must not depend on PyO3/Tauri. A versioned sidecar could avoid
an extension ABI but introduces another lifecycle/IPC/update trust surface. It is
an alternative only after a measured packaging comparison, not an automatic new
process/backend. Keeping both architectures indefinitely is not the goal.

## 10. Evidence and performance acceptance

No current speed baseline was measured in this assessment. Proposed measurements:

- Full application process-tree startup to usable first frame; cold/warm separately,
  repeated runs with OS/storage/network versions recorded; p50/p95, not one run.
- Idle working set/RSS/private bytes and CPU; include Qt/WebView/helper processes,
  not just Python/Rust parent. Compare identical routes/assets/settings.
- Downloads: many-small-file and few-large-file fixtures, cache hits/misses,
  constrained bandwidth/latency, disconnect and wrong Range/length/hash cases.
- Verification/staging: bytes read/written, MB/s, CPU time, peak memory, event queue
  depth, cancellation latency and write amplification on representative HDD/SSD.
- Apply/recovery: induced exceptions and actual authorized process termination
  separately; disk full, locked files, read-only dirs, incomplete journal, unknown
  outcome. A mock does not prove OS crash/power-loss behavior.
- Launch/version/loader matrix and minimum supported Java/runtime; archive symlinks,
  traversal, duplicate/casefold names, long/unicode paths and user-preserve files.

Freeze workload and baseline before setting numerical performance gates. Reject a
rewrite that is faster only because it skipped hashes, backups, auth or durability.
Accept a slice only with no contract regression AND representative measured benefit
or a clearly agreed architectural reason. Do not promise a 2x/5x speedup in advance.

The 605 static test functions are reusable behavioral specifications, not 605 passing
Rust tests. Port fixtures/oracles by domain; retain Python reference where safe.
Supplement mocked units with real isolated filesystem/HTTP/OS integration evidence.
No test suite, GUI, game process, installer, updater or server was launched now.

## 11. What can be reused, retired or requires replacement

- Reuse artwork, approved browser structure/CSS/JS, content assets, test fixtures,
  server API contracts and established data schemas subject to compatibility review.
- Replace Python services incrementally, not the website/server implementation.
- Native Qt dialogs/pages need rewritten presentation and event bindings; they
  cannot be bundled into Tauri by renaming imports. learning/studio features need
  explicit parity scope, not accidental deletion in a smaller MVP.
- Retire obsolete entry/spec variants only after their installed/tester populations
  and update paths are accounted for. PyInstaller disappears only when no Python
  runtime is shipped; Tauri is not by itself an updater/bootstrap migration.
- Preserve managed user installations and signed metadata/keys; never read actual
  credential contents to make this analysis, and never generate replacement trust
  roots merely because the implementation language changes.

## 12. Tooling research (primary sources, checked 2026-10-24)

- [Tauri architecture](https://v2.tauri.app/concept/architecture/) and
  [process model](https://v2.tauri.app/concept/process-model/): Rust core and system
  webviews; verify platform behavior instead of assuming Chromium parity.
- [reqwest](https://docs.rs/reqwest/latest/reqwest/): reuse Client for connection pooling.
- [Tokio spawn_blocking](https://docs.rs/tokio/latest/tokio/task/fn.spawn_blocking.html):
  blocking/CPU work needs bounded concurrency; async syntax is not a CPU-speed proof.
- [maturin](https://github.com/PyO3/maturin) and [PyO3 threading](https://pyo3.rs/main/free-threading):
  Python extension integration exists, but deployment/ABI/thread behavior still needs
  project-specific qualification. Python 3.12/3.13 cache tags are not a runtime inventory.
- [TUF implementation list](https://theupdateframework.io/docs/getting-started/) and
  [tough](https://github.com/awslabs/tough): Rust clients exist; no protocol/artifact
  parity or approved replacement for current Python implementation inferred.

No library version or dependency lockfile was selected/changed here. Review exact
versions, licenses, supported OS/toolchains, security advisories and artifact
provenance when a concrete implementation scope is approved.

## 13. Actual checks and preservation

Read-only Git status/log/branch, scoped source/doc searches and Python standard-
library AST/statistics scripts were used. Bundled Python ran with -I -B, reading
source only, not importing the project or writing bytecode. Direct regex evaluation
of source constants demonstrated F1. File metadata established assets/spec counts;
legacy-key comparisons read only selected files in D:/nexus-work/launcher.

No live security exploit, GUI action or real-data corruption was tested or claimed.
No application benchmarks, tests, Rust compiler/toolchain, WSL/VM, native C2, cloud
operations, installations, deployments or VDI access occurred. Public documentation
search was the only network activity. A malformed PowerShell search was corrected;
it changed no files and is not counted as successful verification.

Baseline preservation inventory covers 356 existing non-cache files in this launcher
repository (excludes .git, __pycache__, .pytest_cache and .ruff_cache). The only
intended created file is this report. Final hashes and Git status comparison are
reported in the conversation after document validation; no clean-tree claim.

## Decision needed before implementation

Confirm Windows-first Rust core + reuse of current browser presentation as the
target, with existing Python launcher kept working through migration. Then scope
stage 0 compatibility corrections and stage 1 measurements before authorizing Rust
source/build changes. Do not start by converting modern_main.py or deleting Python.
