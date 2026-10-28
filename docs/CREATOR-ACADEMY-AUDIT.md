# NEXUS Creator Academy architecture audit

Current production route: ui2 launcher → DesignHost._action/_embed → services.studio_page (StudioPage). StudioService owns project documents, capabilities, validation and local submissions. StudioPage has Qt forms for project/release, presentation/assets, package contents and reviewer operations; its preview is a read-only WorldPage. Publishing authority is deliberately absent locally.

The working visual page builder lives in assets/approved-ui/index.html: studioDraft/studioSaved, renderStudio/renderCanvas/renderInspector, semantic item IDs, geometry percentages, grouping, layers, safe action choices and local Blob assets. Its inspector is generated through inspectorField. Pointer capture implements grid-snapped dragging. There is no shared component registry or event bus; snapshots are in memory. Timeline, responsive constraints and challenge scoring are not existing production capabilities.

The v25 shell does not expose this page builder. We will reuse its canvas/inspector/layer implementation inside a Studio workspace, with an isolated practice document. A single adapter observes committed renderStudio changes and emits semantic events; no lesson conditions enter renderer components. Learning state is separate from project and practice document state. Asset URLs require persistent handling before asset lessons; those lessons are outside phases 1–3.

Existing design owners: nexus_launcher/nexus_platform/theme_tokens.py, nexus_launcher/nexus_platform/presentation_style.py, catalog_controls.NexusButton and ui2 browser tokens. Existing safety owners: ResourcePolicy and loopback AssetServer; no external tutorial scripts, automatic publishing or uploads. Learning content uses localization keys with RU/EN catalogues and fallbacks for future DE/KY support.

Phase 1: schema/registry, explicit runner states, pluggable semantic/state/property validators, hints, atomic progress, version migration, editor abstraction. Phase 2: integrated Studio entry, Academy launcher entry, reusable instruction/highlight/help/minimized UI, pause/exit/resume and independent learning settings. Phase 3: welcome/canvas/components/move/resize/layers lessons against real reused canvas. Later phases extend courses, challenge scoring, assets, typography, responsive tools and timeline only as their editor capabilities become available.


## Phase evidence

Phase 1 files: learning/schema.py, nexus_launcher/nexus_platform/learning/validation.py, nexus_launcher/nexus_platform/learning/progress.py, nexus_launcher/nexus_platform/learning/engine.py, nexus_launcher/nexus_platform/content.py. Sixteen engine tests, Ruff and Pyright passed. The engine has no UI dependency; version migration uses stable step IDs, invalidates stale validation and retains stored progress.

Phase 2 files: learning/studio.py, academy/editor-adapter.js, academy/learning.css; StudioPage and DesignHost route wiring. Real canvas integration tests passed, including wrong-action feedback, actual property changes, independent progress/document files, application recreation and restored validation. Native Windows visual checks cover 1280×800, 1366×768, 900×650 and 640×480. Academy elements use existing tokens and custom presentation, with no tutorial OS dialogs.

Phase 3 files: academy/lessons.json and strings.json. Seven initial lessons include welcome, canvas, first component, move, resize, layers and a complete first-page practice path. Full real-action first-page completion, document save and resumed lesson tested. Existing editor publication capability stays false. New assets, custom typography, animation, responsive tools, universal course browsing and challenge scoring remain later phases, rather than simulated features. DE/KY locale keys use explicit EN fallback; RU/EN content is translated.

Current canvas adapter restores the existing prototype toolset in Studio for isolated practice pages. It does not replace StudioService or automatically apply layouts to published/real project presentations. Runtime-picked Blob assets are not a persistent asset library; their durable import pipeline belongs to the asset phase. No network analytics were added.

## Final v26 acceptance

Engine and real Studio integration: 19 tests passed, including minimized action observation. Focused regression run: 72 passed, 1 skipped. Full suite: 533 passed, 5 skipped, one pre-existing Windows long-path failure in tests/test_windows_pinning.py::test_handle_replace_unicode_and_long_path (WinError 206, nexus_launcher/safe_paths.py:233). Ruff, JavaScript syntax and learning/filter Pyright checks passed with zero errors.

Source and frozen portable smoke checks validate real component creation, minimize/restore, persisted validation, independent document/progress storage and absent publication authority; JavaScript errors are empty. Packaged visual capture was inspected after compositor paint: D:/nexus2/academy-audit-v26/packaged-visual-smoke.png. Responsive source screenshots and reports are in the same directory. The separate QA package does not share production data.

Production portable v26 was launched and responds. Both existing Minecraft 1.21.1 instances (Fabric and NeoForge) were retained; SHA256 checks confirm all six original data files are unchanged after launch. Backups: D:/nexus2/backups/v25-data-before-academy-v26 and source-before-academy-v26. Production executable: D:/nexus2/deliverables-v26/NEXUS-2.0-Portable-v26/NEXUS-2.0-Portable-v26.exe.

Phases 1–3 are complete. Future courses can register declarative lessons and validators against another editor adapter without changing the learning engine. Asset lessons require durable imports first; advanced layout, timeline and scored challenges require their corresponding editor capabilities before course implementation.
