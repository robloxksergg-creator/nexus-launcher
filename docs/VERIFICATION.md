# First migration slice — verification

2026-10-03. Native navigation adapter, isolated 1.0.0 source candidate; not a production release.

Stage 2: compact collection adapter. Combined command:
`python -m pytest tests/test_next_shell.py tests/test_migration_manifest_guard.py tests/test_user_instances.py tests/test_runtime_settings.py tests/test_file_transaction.py tests/test_servers_dat.py -q -p no:cacheprovider --tb=short`
Result: 62 passed. Includes twelve byte-identical protected baseline comparisons, card-to-detail/back routing, local no-results/clear, selection refresh, hidden detail containment, and original service regressions. Populated `assets/previews/pack-library-preview.png` inspected after correcting widget reparenting; no old-page overlap in the collection. Live Microsoft/Minecraft calls and real interactive installation remain untested. No protected implementation or release manifest edited.

Stage 3 live checks (2026-10-03):
- Modrinth search `sodium`, Minecraft 1.21.1/Fabric: 47 projects; hit loader categories matched Fabric.
- `python -m smoke_modrinth`: actual Sodium download/install into a disposable Fabric 1.21.1 instance; one installed/registered mod; SHA-512 independently verified. Existing provider/installer unchanged. Does not establish transaction safety of multi-mod installs (audited P1 remains open).
- `python -m smoke_installed_minecraft 1.21.1 --seconds 35`: isolated demo, Java 21, render-thread/backend initialized, process alive at timeout, no detected fatal startup error; test-owned process terminated; installed manifest SHA-256 unchanged.
- `1.21.11`: fails main-class loading because this installed directory contains its JSON only, no client JAR. No repair/write to the original installation.
- `26.2`: requires Java 25; not installed locally. Java 8/21 present; Java 17/25 not found. These other versions are not claimed working.
- `assets/previews/modrinth-catalog-preview.png`: Qt offscreen catalogue populated with test data; separate toned header and results; fixed header, only results scroll. Live API/install checks above are independent of screenshot data.

New UI checks: catalogue context, native filter popup, stale/empty/error states, paging/scroll ownership at 1280x720 and 1920x1080, guarded instance-ID install routing; original launcher_core and Modrinth regressions included. Skill influence: shared chrome token owner moved to nexus_launcher/nexus_platform/theme_tokens.py so shell/library/catalogue use the same palette. Native Qt selection/popups are the intentional platform-owned variant. Full Microsoft authentication, installer/version matrix, modded game execution, real DPI/mobile/assistive-tech remain unverified; no production build issued.

Final combined stage-3 regression command adds `tests/test_mod_catalog.py tests/test_modrinth_provider.py tests/test_launcher_core.py` to the stage-2 suite: 76 passed. Premium strict audit: zero findings. Twelve protected baseline files remain byte-identical; original Modrinth installer and Minecraft core not edited.

Stage 4 — 2026-10-04: website-linked registration.

Packaged user acceptance build: `deliverables/NEXUS-Next-Registration-Test.exe`, built with separate packaging/specs/NexusNextRegistrationTest.spec from nexus_launcher/preview_next.py (not stable_main/private_main). PyInstaller 6.22.2, Python 3.12.10. Size 92,890,199 bytes; SHA-256 `492302713557AA5B1E8E79624FDBAA4B6C829FB4B350E8A49AF47CD18B9189C5`; Authenticode NotSigned. Frozen offscreen acceptance exited 0 and verified main window, registration button, initial submit, email-code step, production account API and Windows keyring backend. No email/login/account mutations executed in this check. Protected baseline guard: 12 passed. Registration email delivery still needs user acceptance. Build warns about optional pycparser lexer/parser tables; no packaged startup failure detected.
- Source contract inspected in website_NexusMC: code request, registration, launcher login, auth rate limits and production DB binding. No website/server deployment or auth schema changes.
- Read-only website check: public /login and same worker /login respond HTTP 200. This does not prove email delivery or deployed registration behavior.
- New client calls existing `/api/auth/email/request-code` then `/api/auth/register`, including the same persistent device ID and email challenge. Existing protected NexusAccountClient remains byte-identical; after successful registration, its original login worker/keyring session handling is reused.
- Combined suite (stage-3 suite plus tests/test_registration.py and tests/test_nexus_account.py): 82 passed. Registration tests mock all external mutations and verify endpoint/payload parity, device continuity, bad/malformed replies, duplicate prevention, two steps, secret-input cleanup and uncertainty on transport failure.
- Qt offscreen `assets/previews/registration-preview.png` inspected: shared NEXUS colors, Cyrillic, native field labels, masked passwords, visible cancel/submit. Code-step dimensions additionally tested after this capture. No claim of real DPI/screen-reader/mobile coverage.
- Actual account creation/email delivery/login after signup not exercised: needs a user-controlled email and code. No synthetic production users, emails, sessions or device bindings created by automated tests.
- Preview now allows explicit real registration and sign-in; automatic account restore is still disabled. Accounts/session/device binding are durable; local preview packs/config remain disposable. This distinction is shown in registration copy and MIGRATION.md.

Skill influence: registration uses shared theme tokens and native labelled fields, server-owned verification policy, explicit non-idempotent pending/uncertainty states; no parallel local identity store or bypass introduced.

- Original service + new shell suite: 48 passed (test_next_shell before capture test, test_user_instances, test_runtime_settings, test_file_transaction, test_servers_dat).
- New shell suite after font registration/capture test: 8 passed; navigation, restore toggle, 1280×720 / 1366×768 / 1920×1080 geometry, isolated writes, pin/unpin, rendered capture.
- Ruff: nexus_launcher/nexus_platform/next_shell.py, nexus_launcher/preview_next.py, tests/test_next_shell.py — all checks passed.
- Premium strict static audit: 0 findings.
- DESIGN.md official lint: 0 errors, 0 warnings.
- Qt offscreen screenshot inspected: shell layout, cube and Cyrillic render. Qt offscreen exposes no system fonts; tests explicitly register local Segoe UI/Georgia, without redistributing those fonts.

Not tested: live account/API/Minecraft/install/update, real DPI/assistive technology, Windows interactive font selection, phone, full redesigned forms/editor/catalogue. These are not implied by geometry/static checks. Existing pages remain old during this first slice, so this screenshot is not the final approved prototype recreation.

Skill influence: shared sidebar adapter and durable DESIGN/UX contracts chosen instead of replacing old service-owned actions. User's hidden-scrollbar requirement is an explicit exception; scrolling remains enabled.
# Approved presentation replacement — 2026-10-04

- Combined account, Qt shell/catalogue, core, instance, runtime, transactions, servers.dat and protected-byte guard suite: **90 passed**. Added profile-route/no-popup tests at 1280×720, 1366×768, 1920×1080, world viewport containment, local save/un-save isolation, password reveal and logout-state recovery.
- Visual Qt captures inspected: deliverables/overview-next.png, profile-next.png, world-next.png. They are offscreen native Qt evidence, not real DPI, screen-reader, phone or end-to-end live account acceptance.
- Ruff changed Python files: passed. DESIGN.md lint: 0 errors, 0 warnings. Premium strict audit: 0 findings after explicit sourceRoots for application source (PyInstaller generated xref HTML is not product UI). Static audit does not establish native accessibility compliance.
- Separate PyInstaller one-file build: deliverables/NEXUS-Next-Design-Test.exe (93,591,921 bytes), unsigned. SHA256 FC05C1D566076B33ADDB7EDB8DC147007791F8811D438C2EAD8060F2008A7035. Packaged offline smoke report: frozen-design-smoke.json, visible window/registration/code controls true, production account API, Windows keyring, zero network calls. Test process ended. No real registration was performed.
- Complete prototype feature parity is pending as enumerated in MIGRATION.md. No claim of complete migration or production readiness.

