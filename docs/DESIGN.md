---
version: alpha
name: NEXUS Launcher
description: Russian desktop Minecraft library with quiet blue utility chrome and independently art-directed worlds.
colors:
  background: "#0a0e14"
  sidebar: "#10161f"
  surface: "#18212c"
  primary: "#a6c9ff"
  selected: "#20334b"
  text: "#f1f4f8"
  muted: "#a5b1c2"
  border: "#2b3747"
  hover: "#233044"
  success: "#9edbb8"
  warning: "#eac28b"
  danger: "#f4a4ab"
typography:
  sans:
    fontFamily: "Segoe UI, sans-serif"
  display:
    fontFamily: "Bahnschrift, Segoe UI, sans-serif"
    fontSize: "56px"
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "15px"
  metadata:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "12px"
rounded:
  DEFAULT: "8px"
spacing:
  navigation-width: "232px"
  navigation-collapsed: "72px"
  navigation-inset: "16px"
components:
  navigation:
    backgroundColor: "{colors.sidebar}"
    textColor: "{colors.muted}"
    rounded: "{rounded.DEFAULT}"
  selected-navigation:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.primary}"
  heading:
    textColor: "{colors.text}"
  catalogue-header:
    backgroundColor: "{colors.selected}"
  positive-status:
    textColor: "{colors.success}"
  warning-status:
    textColor: "{colors.warning}"
  error-status:
    textColor: "{colors.danger}"
  divider:
    backgroundColor: "{colors.border}"
  catalogue-row-hover:
    backgroundColor: "{colors.hover}"
---

# NEXUS desktop design

## Startup updater presentation (2026-10-16)

`startup_update_window.StartupUpdateWindow` is an adapter-injected startup
surface, not yet a distributed executable entrypoint. It reuses NexusDialog,
launcher TitleBar, presentation_style and theme_tokens. Quiet NEXUS wordmark,
one current action and a thin progress line; no copied Discord branding.
Recovery actions stack vertically so Cyrillic labels fit at 480px width.
No animation is required; loading uses the native progress indicator.
The package namespace loads PlatformLauncher lazily so shared chrome/tokens
can be used before application initialization. Existing explicit imports remain
compatible. WindowsProcessAdapter now owns the inherited private IPC and lifetime
lease. Managed tester readiness uses an explicit service/auth/navigation probe;
full-client acceptance is separate from fixture and offscreen verification.

## Overview

NEXUS 2.0 is a world-led Minecraft launcher for Russian-speaking players.
The user explicitly authorized a complete redesign on 2026-10-08, superseding
exact-prototype preservation for the portable candidate. Its signature is a
large Minecraft landscape, clear world identity and one immediate play/install
action inside a compact persistent rail. Utility lists are quiet and dense;
artwork, not borders, creates the main hierarchy. Avoid administrative dashboards,
uniform empty boxes, fabricated player counts and decorative news.

`portable_main → DesignHost` uses `assets/ui2`: components.js (pure shared
primitives), screens.js (read-only page compositions), launcher.js (visual
navigation state). `nexus_launcher/nexus_platform/design_bridge.py` owns sanitized view models and validated
service actions. Existing native workspaces occupy the same content region.
No tokens, email, credentials, raw paths or arbitrary filesystem API reach JS.
The legacy PrototypeHost remains available only as a preserved reference.

## Colors

Runtime canonical owner is `nexus_launcher/nexus_platform/theme_tokens.py`: TOKENS, TYPE,
SPACING, RADIUS, MOTION and LAYOUT. `browser_tokens()` generates CSS variables
at asset-serving time; `presentation_style.stylesheet()` is the Qt adapter.
ArtworkSurface/ArtworkCard and ModCatalog consume the same owner. This document
mirrors that source. WorldTheme remains independently scoped; world accent is
never a trust badge.

## Typography

Bahnschrift display with Segoe UI Cyrillic fallback; Segoe UI body and controls.
Type roles: display 56, heading 36, section 24, body 15, caption 13, metadata 12,
label 14 px. Hero titles adapt down to 38px. Metadata stays secondary; titles
wrap or elide with full accessible name/tooltip. No font download or late swap.

## Layout

Current portable: 232px rail / 72px compact icon rail, 64px topbar, natural-height
scrolling content capped at 1760px. Spacing scale 4/8/12/16/24/32/48/64/96.
Landscape cards adapt to available width; primary hero 360px compact / 520px
wide. Profile skin panel aligns at start rather than stretching its copy.
Build details use one content navigation plus original files/log/backups panels.
Target viewports: 1280×720, 1366×768, 1920×1080, 2560×1440. No horizontal page
overflow; fullscreen retains meaningful grid/content bounds.

The historical v7–v17 notes below describe the retained legacy renderer only;
they do not override the current portable foundation and IA above.

V10 refinement: discovery uses only the supplied Minecraft meadow/desert/city/mountain scenes and the retained Gearmorph build. Fantasy artwork is no longer served by the preview. World cards use a native stretched open button, with save/add actions remaining independent siblings. Hover/focus highlights the card; reduced motion removes translation. Profile tabs belong inside the identity header, with a subdued active underline and content fade. Switching profile sections preserves current scroll; a stable minimum height prevents shorter sections clamping the page.

V9 user-approved revision: `discover-page.js/css` own scene-led Overview, separate catalogue server route and detached rails. Project identity and authors are merged on the left; advertisement preview stays on the right. Creator background belongs only to the central webpage, including its tabs and lower content. Breakpoints: advertising below center at 1500px, identity below center at 900px. Earlier v8 three-zone background is superseded by these overrides. Existing packaged artwork is reused, no fabricated live streams/statistics. Editing shortcuts move into the single profile-edit entry; public projects remain read-only until verified creator ownership is connected. Local draft editing is not a public role.

Exact-design desktop adaptation is owned by `assets/approved-ui/desktop-adapter.css`: presentation-only artboards cap at 680px, minimum 520px on desktop, with text capped at its authored size. Studio coordinates and source HTML are unchanged. `nexus_launcher/nexus_platform/window_chrome.py` owns a 36px title bar, consumes TOKENS and uses native system move/resize operations; standard Windows title decoration is removed. Fullscreen hides this bar; restored windows expose six-pixel resize edges.

Desktop v7 adds one sign-in entry below the sidebar account row and an app-owned modal choice screen. Login/registration credential forms remain native service-owned; no credentials enter JavaScript. Preview artboards are capped by background image native width divided by device pixel ratio to avoid oversized low-resolution artwork. The current Gearmorph source is 735×533; high-resolution replacement is pending user attachment. Window restoration explicitly reapplies a bounded normal geometry, and dragging a maximized window first restores it.

258px sidebar, scrollable menu, stationary account/settings footer; one-click collapse releases the entire width. Titlebar toggle stays outside the sidebar. PresentationSurface is centered and capped at 1600px including its 40px side insets, matching the prototype's content container. Home Hero is 440px tall on compact desktops and 530px when the workspace viewport is at least 1400px wide. RoundedHero clips the child image to 14px corners, not merely its background. Settings own an internal scroll surface. Desktop acceptance sizes: 1280×720, 1366×768, 1920×1080, 2560×1080 and 3840×2160; mobile support is not claimed for native Qt.

Settings use the prototype's two-column workspace: 250px category menu (200px below 1000px workspace width), 24px gap, 40px outer insets and 32px content insets. The form scrolls independently; no legacy 1100px/650px shell cap remains. SettingsWorkspace consumes canonical surface/border colors through nexus_launcher/nexus_platform/presentation_style.py and retains SettingsPage controls/signals, not its old layout.

## Elevation & Depth

V12: continuous yaw has no drag or keyboard end-stop; the position slider shows one wrapped revolution. Native radio rows select standard 4px / thin 3px arms in the shared skin-preview owner, using existing surface/accent tokens. Pose and manual model choice survive profile tab changes in-session; incoming account-profile changes restore the service-reported model. The selector changes preview geometry only, not the published skin.

V11: `skin-preview.js/css` owns shared articulated CSS-3D Minecraft cuboids and a textured head avatar. Grey untextured fallback, pixel-exact atlas faces, classic/slim dimensions, pointer rotation and keyboard-accessible rotation/zoom ranges. Existing account client owns skin retrieval; only validated PNG texture/model reaches the page. Profile panels no longer stretch to the summary height, and tabs have a single active marker (not the original border plus underline).

Tonal hierarchy, thin borders, no decorative new shadows. The avatar is a vector-rendered three-face grey cube, without eyes or a PNG; it is a placeholder, not a full interactive 3D skin renderer.

## Shapes

V13: skin face canvases pre-rasterize nearest-neighbor atlas pixels at 16x backing resolution while retaining logical cuboid dimensions. This reduces compositor texture blur without inventing skin detail. The real pack/mod actions reuse the existing service window; no new global design tokens or fake catalogue results are introduced.

8px navigation corners; 46px navigation row; 40px settings square. Keep badges/status/progress attached to the existing RailButton contract.

## Components

Current 2.0: shared browser hero/world-card/build-row/button/state primitives;
native ArtworkSurface, ArtworkCard/ArtworkGrid and ContentState. Landscape art
crops to fill without distortion. Hero overlay concentrates darkness at bottom.
Missing build/mod artwork is a seeded voxel landscape, never a huge letter.
Library mutation handlers, mod resolver and confirmations remain original.
Motion: 160/220/300ms for controls/pages/artwork; smooth scrolling retains the
existing shared owner, scopes wheel events to its window, and respects reduced
motion. Missing backend data is omitted or explicitly unavailable.

Historical component notes below remain relevant to the legacy reference and
retained shared skin/media/security owners; exact-preview layout is superseded.

V19 polish: retain Home/Worlds/Profile compositions. Native build cards add
truthful memory/world counts and explicit Open/Play actions; installed mod rows
retain native multi-selection and authoritative filenames. Build detail has a
scrolling outer content region so forms/actions remain accessible at 1280×720.
Shared empty states are bounded to 220–260px rather than stretched canvases.
Download empties use the same compact scale. Native scrollbars remain hidden per
the existing user preference; wheel, touchpad and keyboard scrolling remain.

Project content uses `nexus_launcher/nexus_platform/project_content.py`: supported authored HTML is translated
into inert Markdown; scripts/styles/frames/forms are discarded. QTextDocument
never fetches URLs/files. Only bounded HTTPS cdn.modrinth.com PNG/JPEG/WebP/GIF
media passes a decode gate (4MiB, 4096px); failed images show a readable fallback.
Links open externally only after an explicit click and HTTPS URL validation.
Navigation invalidates queued/stale media. Code examples remain literal code.
This replaces the historical raw-HTML-as-text behavior described below.

New Build uses its original dialog/fields/signals/validation, recomposed by
`nexus_launcher/nexus_platform/dialog_presentation.py` into a titled, bounded scroll form and fixed footer.
Advanced options remain collapsible; loader/template popups use the existing
Qt Fusion presentation approach. Context menus keep all ten original actions,
with separators around destructive operations. Settings retain their original
controls and category search, with consistent sentence-case headings.

V17: wheel scrolling is shared across HTML routes and nested overflow regions
by `approved-ui/smooth-scroll.js` and native scroll areas by `nexus_launcher/nexus_platform/smooth_scroll.py`.
Precision touchpad deltas remain native; reduced motion bypasses easing. Modrinth
rows use distinct title/author, description, compact metadata and an install
action. A mod opens its own service-backed profile with Overview, Changes,
Gallery and compatible Versions, retaining search results on return. Native
Markdown disables raw HTML and implicit image/file loading; gallery media uses
bounded CDN-only requests. Empty, loading and network failures remain explicit.

V16: only My Packs embeds into the existing HTML workspace below its topbar.
The original sidebar and all other HTML routes remain present. PrototypeHost
positions the native library from the existing workspace bounds, follows sidebar
collapse, and animates its entrance for 180ms unless reduced motion is enabled.
The former full-window return button is absent on this route. Leaving the library
restores the existing HTML content without reloading the document.

V15 recovery: PrototypeHost applies the canonical `presentation_style.stylesheet`
to embedded service workspaces and their native dialogs. It refreshes the pack
library directly, without the hidden legacy window's navigation/fade effect.
Pack creation, persistent manifests and reopening the library are covered by
`test_embedded_library_creates_persistent_pack`.

V14 migration: pack/mod workflows embed the existing service workspace inside PrototypeHost, without opening the legacy navigation shell. Mod rows reserve 64px icons, activate a read-only project profile, and reuse existing installation authority. Native credential/settings/maintenance surfaces have not yet been retired; this is not full HTML parity.

`ui-polish.js/css` owns card/profile refinements and connects the existing sound synthesis to `UIPreferences`. First launch defaults sound on; explicit off survives restart in `%LOCALAPPDATA%/NexusDesignPreview/ui-preferences.json`. Only fixed same-origin `sound-on`/`sound-off` commands write that single boolean; no filesystem API, credential/config migration or arbitrary payload is exposed. Failed saves are announced; unreadable preferences do not silently re-enable sound. `banner-media.js` extends the existing owner-only layout editor with local PNG/JPEG/WebP ≤20MB and MP4/WebM ≤200MB (existing prototype media limits), decode validation, cancel/stale cleanup, silent looping, pause and fullscreen controls. Reduced-motion/hidden pages pause video. Banner media remains session-local and unpublished until verified creator/backend integration.

`server-layout.js` / `server-layout.css` own the shared server-page zones: plain left information column, independently themed main background, authors / central canvas / optional marked advertisement preview. Below 1600px the rails stack under the center, never squeeze or overlap it. Private packs suppress these public surfaces. Settings use per-project `backgroundSaved.desktopLayout` and the existing project snapshot mechanism; they remain session-local. Background images are validated PNG/JPEG/WebP ≤20MB, decoded before preview, without external scripts or ad delivery. No new advertising monetization or trust policy is introduced.

Navigation reuses WorldRail signals and RailButton status/selection. SidebarButton draws left-aligned labels; the settings square uses a vector gear. `nexus_launcher/nexus_platform/presentation_style.py` is the sole global Qt adapter for TOKENS: the old PlatformLauncher stylesheet is no longer appended. Home and world presentation use the approved Minecraft build asset, not legacy fantasy hero artwork. Creator-supplied remote media and world accents remain independently scoped. Hover brightens the row, focus has a visible outline, selected rows receive subdued blue fill. Native button keyboard semantics and accessible names remain intact. Collapse animates width over 220ms; reduced motion switches instantly; interrupted animations restart from current width.

The user's explicit hidden-scrollbar requirement overrides the skill's visible-scrollbar default. Scrolling itself must remain operable by wheel, trackpad and keyboard; never use clipping to remove overflow. Desktop privacy/auth and download authority remain old service-owned behavior, not cosmetic flags.

## Do's and Don'ts

V21 content keeps the same visual tokens. Sanitized authored Markdown is parsed
into CommonMark image/link/formatting tokens before inert Qt output; generated
markup never contains remote img/src or active authored HTML. Linked image
pending/success/failure states retain anchors; empty-alt images remain images.
Images in quotes/lists account for indentation when resizing. Multiple rejected
decorative images use one compact notice and descriptive alt text. External
image origins remain prohibited even if the author's gallery uses the CDN.

Modrinth media uses a single presentation-only verified CDN transport with the
bundled Mozilla CA roots (`packaging/requirements/requirements-media.txt`). Only `https://cdn.modrinth.com`
is accepted, including redirects. Images must decode as PNG/JPEG/WebP/GIF within
4 MiB and 4096 px; existing icon limits remain stricter. The in-memory LRU is
16 MiB / 64 validated URLs / five minutes, with no failed entries or disk cache.
Descriptions show compact loading/failure text, and loaded images resize with
the reading area. Gallery media retains featured/order and author captions.
No global TLS policy, provider behavior, shell layout or service authority changes.

- Keep labels readable and status truthful; no synthetic downloads/Official statistics.
- Retain core services and models, not old appearance. Unported capabilities remain explicitly listed in MIGRATION.md; a new stylesheet alone does not establish feature parity.
- Do not overwrite installed profiles or execute production release builders for a preview.
- Do not claim desktop, DPI or mobile verification from AST checks.

V22 scrolling uses one frame clock per web surface and a fresh Qt timeline on retargeting. Reverse input starts from the visible position; touchpad and keyboard input cancel queued wheel motion. Scrollbars are hidden on native and web surfaces without clipping their overflow.

V23 web scrolling delegates to Chromium ScrollAnimatorEnabled with no JS wheel interception or timers. Native paint/layout/timer events bypass the Python scroll filter before any ancestry traversal. Hidden chrome and reduced-motion preferences are retained.

V24 Modrinth discovery uses the existing native colors/type/controls. A grouped modal filter panel has draft selections and one Apply submission; active chips, server sorting and 20-result pagination remain outside it. Tags come from Modrinth, with loaders intersected with the existing installer's capabilities (Fabric, Forge, NeoForge). Only mod projects are offered. Per-instance query, filters and page offset survive reopening during the session. Broader discovery never changes instance metadata; known-incompatible result installs are disabled and the existing resolver remains authoritative.


## Modrinth catalogue filters (v25)

Filter editing uses an integrated, bounded drawer inside the catalogue. Version and loader are searchable multi-select popovers; categories are compact toggled chips with a searchable full list. Additional conditions collapse into one section. Apply commits the draft once; Cancel and Escape discard it. Sorting is an independent painted selector. Every popover stays inside the launcher window. Catalogue controls use the existing NEXUS tokens and custom painting, without native combo boxes, checkbox markers or dotted focus rectangles. Keyboard focus retains a subtle accent border. Active filter chips wrap and the entire row disappears when empty. Query and provider behavior are unchanged.


## Creator Academy — first Studio integration (v26)

Academy is part of NEXUS, accessed through the main navigation and directly inside Studio. Studio is its first taught product; the existing page-builder canvas, inspector and layers remain the renderer. A single adapter translates committed editor mutations into semantic events. The learning engine never references Qt widgets, DOM selectors or pixel positions. Progress and isolated practice documents have separate atomic files under .nexus-academy; production project/release documents and publishing authority remain with StudioService.

## Studio workspace (v27)

Creator uses one global header, a compact left add rail, a prominent percentage-based canvas and a contextual right inspector. Collapsible sections progressively reveal existing properties. Page settings require clearing selection. Layers and current-document media use a secondary collapsible bottom panel. The shared nexus_launcher/nexus_platform/theme_tokens.py palette remains canonical; Studio workspace.css scopes its presentation to this route. Authored choice disclosures replace native popup geometry while dispatching original field handlers. Academy cards stay inside the canvas region and target the real tools/properties. Hidden scrollbar chrome preserves overflow and keyboard operation. No timeline, publication permission or permanent media library is implied by the redesign.

Tutorial cards, highlights, minimized pills, help and course navigation use canonical browser tokens and the existing native NexusButton. Targets resolve semantic tool IDs, component IDs/types and inspector properties. Cards remain optional: skip/pause/exit/restart/resume are available, interactive Next waits for verified action, skipped practice cannot earn completion. Expert mode suppresses automatic guidance. RU/EN content is localized outside UI code; DE/KY are explicitly displayed as EN fallback until translations exist. No challenge-quality scoring or publishing simulation is presented. Phases 1–3 teach welcome, canvas, creation, movement, resize and layers; future asset/timeline/responsive lessons wait for production editor capabilities.


## Tester authentication
The tester startup screen uses the native presentation_style adapter and existing NexusLogin/RegistrationDialog. AuthState owns session lifecycle; account credentials and email never enter the web renderer. Reuse runtime tokens, Bahnschrift heading and Segoe UI fields. Loading, denied tester access, network failure and expired session provide direct recovery actions. Native TitleBar remains visible throughout authentication. No offline authentication is simulated.

After confirmed nickname completion, Continue closes the registration surface and opens the existing NexusLogin with that nickname prefilled and password focus. It never reuses a registration password or grants a tester role. Cancelling registration or leaving the nickname pending returns to the authentication gate. The deferred transition is owned by the host window so closing it cancels the transition. Successful login still requires server verification and the existing tester-access gate.

Owner update 2026-10-16: ordinary prerelease access is available to every server-authenticated NEXUS account regardless of email provider or the legacy tester flag. This supersedes the tester-only main-view gate above; email verification, credentials, session validation and device policy still apply. TESTER_BUILD remains a private-channel identity and keeps unfinished cloud/operator controls disabled. No admin/staff/hosting permissions are granted by ordinary admission, and public self-update remains disabled.


Portable authentication continuation (2026-10-26): the portable registration
surface now follows the same confirmed-profile-to-NexusLogin handoff as the
tester surface. Nickname prefill and password focus reuse NexusLogin; no new
visual tokens, renderer credentials or authentication authority are introduced.
System keyring failures use existing account-error feedback and unblock retry.
