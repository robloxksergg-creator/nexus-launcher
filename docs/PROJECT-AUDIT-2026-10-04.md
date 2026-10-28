# Project integration audit — 2026-10-04

## Scope and conclusion

Inspected the prototype source, runtime entry points/spec, native service adapter, settings migration, earlier manifest/security audit and service authority documents. Ran the complete discovered Python test suite. This is not a claim of line-by-line review of all archived releases, a live backend pentest or a full game-version acceptance matrix.

The central visual defect was architectural: successive native layouts did not execute the approved HTML/CSS/JS. The new separate candidate entry point loads that whole source in Qt WebEngine. The source remains byte-identical; a separate desktop adapter adds explicit service access and truthful preview labeling. The old installed executable and protected modules stay unchanged.

## Findings and fixes

| Finding | Resolution |
| --- | --- |
| Prototype was packaged but never rendered | PrototypeHost is now the candidate's first screen |
| Root-relative Gearmorph image missing in prototype | Whitelisted local asset endpoint supplies the real bundled PNG |
| Native port omitted prototype animations/editor/sound implementation | Whole original script/style executes; actual audio-device acceptance remains pending |
| Risk of privileged local HTML or external page gaining service access | GET-only loopback assets, exact Host/origin checks, no Python WebChannel, three fixed commands, no arbitrary paths/commands, remote navigation/resources/downloads blocked |
| Site security tests assumed original sibling checkout | Explicit NEXUS_WEBSITE_SOURCE points to maintained website source; isolated SQLite tests remain real |
| Staging test incorrectly expected environment variable to expand trust | Test now asserts compiled build-channel gating; production protection unchanged |
| Invalid config could be overwritten with defaults | Fail on malformed JSON/type/version without modifying source bytes; five recovery tests added |
| Custom desktop command navigation was suppressed by browser policy | Same-origin fixed command paths intercepted before network; actual renderer dispatch/rejection integration test passes |

## Verification evidence

- Complete Python run: 384 passed, 2 skipped; deliverables/full-audit-tests.xml. Later renderer command transport is covered by 4 passing tests/test_prototype_host.py tests, including actual WebEngine dispatch and rejection of unknown commands.
- Protected-source guard passes; prototype source hash matches original exactly.
- Ruff passes for changed files; premium strict audit reports 0 findings; DESIGN.md lint has 0 errors/warnings. These static checks do not establish whole-product accessibility or security certification.
- Native source and packaged WebEngine smoke both load the original DOM/artwork with no JavaScript errors; screenshots inspected at 1366×900. Real audio output, DPI and every prototype interaction remain unverified.

## Remaining limitations — do not treat as completed

Prototype pack/settings/profile operations still include transient UI simulations. Actual installation, Modrinth, game launch, backup and runtime operations are accessible through a temporary native services window; they are not yet mapped to every prototype control. Entry point uses disposable config/instances; explicit account creation/sign-in remains real.

External YouTube/CDN/media are blocked in this first isolated renderer; author-font fallbacks and visible external-link behavior still need a reviewed policy. No live Microsoft login, new account/email acceptance or full Minecraft version launch matrix was performed here.

The previous audit's protected-core P1 items (release expiry/trust binding/minimum launcher version and mod transaction scope) are not declared resolved. Modifying signed manifest policy blindly to get a passing visual preview would be unsafe and conflict with the user's preservation requirement. Candidate remains unsigned and not production-ready.

## Reconcile drift

| Rule | Evidence | Action |
| --- | --- | --- |
| Exact approved prototype | Native widgets repeatedly diverged | Execute whole source instead of reconstructing it |
| Services own authority | Prototype has DEMO data and temporary actions | Label preview; keep real commands in original service layer |
| Old native-only contract | New explicit exact-source request | Document isolated renderer while retaining native fallback for rollback |

Design skills influenced source fidelity, isolation boundaries, explicit unconnected state and retention of authoritative handlers, rather than another palette/layout invention.
