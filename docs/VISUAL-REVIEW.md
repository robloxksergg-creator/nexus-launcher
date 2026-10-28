# First review, 2026-10-08

Evidence: ../ui2-review-windows/*.png, real Windows Qt/WebEngine renderer.
Offscreen Qt captures browser pixels as black here; they were rejected as visual
evidence. Geometry/DOM tests still run offscreen; Windows captures are required.

| Kind | Observed issue | Correction |
|---|---|---|
| Visual 1 | Profile copy stretched to skin-control height, huge dead upper area | Align start; bounded cover and skin stage |
| Visual 2 | Catalogue Add world duplicated active highlight | Exclude secondary navigation from current-page selection |
| Visual 3 | Pinned heading consumes space when list empty | Hide absent pinned section |
| Visual 4 | Sidebar groups crowd lower rail at 768px | Reduce group spacing while retaining scroll |
| Visual 5 | Baked artwork titles double card identity and crop poorly | Supplied clean Minecraft scenes for discovery covers |
| Visual 6 | Empty installed-mod list shows a large blank bordered box | Shared visual empty state with real Modrinth/create action |
| Visual 7 | Detail has ten crowded single-line tabs | Eight primary sections and original file/log/backup subnavigation |
| Visual 8 | Empty search displays X even when hidden | Explicit shared hidden-state rule |
| Visual 9 | Overview exposes paths as primary content | Readable facts; file paths remain in settings/files |
| Visual 10 | Library metadata truncates and old N icon remains in mod profile | Wider landscape cards, bounded name, designed seeded fallback |
| UX 1 | Server menu routes point to hidden service pages | Mirror original service route decisions into persistent shell |
| UX 2 | Reset-search action doesn't reset filter/query | Clear both before reopening catalogue |
| UX 3 | Vanilla empty-mod action suggests incompatible installation | Create a loader-enabled build through original dialog |
| UX 4 | Updater button disappeared with retired old catalogue tab | Restore existing _update_mods handler in installed-mod workspace |
| UX 5 | Breadcrumb uses forward arrow to return | Back glyph for parent route |
| Consistency 1 | Login/create all receive Play glyph | Glyph tied to operation |
| Consistency 2 | Web/native loader capitalization differs | Central display labels |
| Consistency 3 | Native lists and settings have legacy box borders | Shared surface/border policy |
| Consistency 4 | Native sliders retain unrelated accent | Shared slider accent |
| Consistency 5 | Native N fallback conflicts with designed web landscape | Shared deterministic landscape concept |

Second review and remaining limits are recorded after final rendered captures.


# Second review, 2026-10-08

Evidence: ../ui2-review-final/*.png (Windows renderer, 28 captures) and
../frozen-smoke-v18-final.png (packaged EXE with the copied real v17 library).
Screens with `fixture` in their filenames contain isolated test data only.
No fixture content is shipped into the user library.

- Reviewed Home at 1280×720, 1366×768, 1920×1080 and 2560×1440.
  DOM geometry reports no horizontal overflow; wide composition is bounded.
- Reviewed catalogue, saved worlds, server, profile, library, build overview,
  eight build sections, settings, downloads and creation dialog.
- Profile library now follows its cover in the left column instead of waiting
  for the taller 3D-character controls. No blank stretched cover remains.
- Removed duplicate Modrinth action underneath the empty mods artwork.
- Downloads reuse their real state owner; empty does not claim every pack is
  up to date. Progress is driven by byte events; error includes recovery.
- Mod search now has shared designed empty/loading/error states. Project body
  is dark and reads Markdown without executing embedded HTML/scripts.
- Native Modrinth category popup tested open on Windows. Qt Fusion owns its
  themed list, selection and keyboard behavior. Geometry polling no longer
  repeatedly raises the overlay and disturbs native popup focus.
- Local saved-world folders render real names/icons with deterministic artwork
  fallback. Enter opens the original per-build folder operation.
- Browser action bindings checked across routes; no enabled orphan button.
- Explicit stop-game action restores access to the original process owner.
- Unsaved studio guards also prevent closing the outer host; refusal keeps
  the UI timers and draft alive. Reduced-motion state works in both surfaces.
- Frozen acceptance: loaded=true, artwork decoded, off-record profile=true,
  no JavaScript errors. The real existing build appears in Home.

Remaining verification limits: real screen-reader/high-DPI certification and
full live Minecraft launch/account registration were not performed.
Existing Windows long-name file replacement and expired public update envelope
remain outside presentation changes. No claim of production-release readiness.

## Static audit interpretation

The upstream strict auditor reports 15 `affordance.actionless-button` findings.
Its detector accepts only inline onclick/Vue directives; it does not recognize
vanilla JS delegated listeners or property-bound onclick in launcher.js.
All 15 literal controls have data-route/data-action/data-filter or a named
external handler. test_design_host checks enabled controls across web routes,
search clearing, native routing and real action dispatch. No inline handlers
were added and CSP was not weakened to satisfy a static heuristic.
The original strict JSON is retained unchanged at ../ui2-premium-audit.json;
it is not reported as a zero-error automatic audit. DESIGN.md lint, Ruff,
Pyright and project runtime checks are separate evidence.

## V19 consistency polish review — 2026-10-08

Fresh Windows Qt captures: `D:/nexus2/ui2-polish-review` (89 page/dialog captures
plus a contact sheet). Offscreen WebEngine captures were not used as visual
evidence. Review sizes: 1280×720, 1366×768, 1920×1080 and 2560×1440.

Reviewed Home/Worlds/Profile/Catalog, build cards and all eight detail tabs,
Files/Logs/Backups, installed-mod selection/toggle, Modrinth rows/filter popup,
project Overview/Changes/Gallery/Versions, Downloads empty/progress/error,
Settings, collapsed/expanded creation dialog and its advanced bottom fields,
and the ten-action build menu. Catalog/mod content screenshots explicitly use
test fixtures; the packaged Home capture uses the user's actual two builds.

Iteration fixes: at 1280×720 the large header compressed fields/buttons. The
whole native detail now scrolls, with a 440px minimum for the tab region. Tests
check button heights/containment, tab visibility and bottom scroll captures.
The mods search/update toolbar is one row; content empty states are bounded.
The collapsed creation dialog now exposes its advanced toggle immediately;
fixed footer, inherited primary style and grouped advanced sections were
verified again. Reading blocks now have explicit line height, heading spacing
and a bounded text measure. Corrupt/stale/unsafe images have separate tests.

Windows runtime checks: 41 passed across DesignHost/native adapters/NextShell;
17 passed again after the small-window containment fixes, and 3 rich-content
checks after the final reading-spacing change. Frozen candidate acceptance:
loaded=true, artwork decoded=true, off-record=true, JavaScript errors=[].

The strict static auditor still reports the same 15 delegated-button heuristic
findings; original output retained at `D:/nexus2/polish-premium-audit.json`.
No new rule classes, inline handlers or CSP allowances were introduced. Actual
button ownership remains checked by runtime tests. DESIGN lint: 0 errors /
0 warnings. Ruff and the eight-module Pyright scope pass.

Largest remaining visual weakness: some retained maintenance/auth/system file
dialogs still use native Qt/Windows conventions. Untrusted external image hosts
remain unavailable in authored mod descriptions; they are not silently granted
network/file access. Screen-reader/DPI certification and a full live Minecraft
launch/account/mod-install run are not claimed by this local polish pass.
