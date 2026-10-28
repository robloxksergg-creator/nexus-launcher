# Studio UX migration — v27

## Architecture and migration

The retained page builder owns studioDraft/studioSaved, percentage geometry, selectedID, multiSelection, file validation, grouping, layer order and safe actions. renderCanvas/renderStudio/renderInspector remain the mutation/render boundaries. Academy's independent engine observes committed semantic events through editor-adapter.js. There was no undo/redo history or durable asset library to preserve.

The migration layers a Studio presentation adapter over these existing boundaries, without replacing state. Phases: (1) audit owners; (2) top bar/left add rail/canvas/inspector shell; (3) contextual collapsible properties and page settings; (4) dedicated layers and applicable element actions/context menu; (5) bottom resource view; (6) existing Academy targets and instructions; (7) keyboard, responsive and visual checks.

## Components and ownership

assets/studio/workspace.js owns shell, component picker, contextual disclosure, authored choice controls, layers/resource view and element context actions. workspace.css adapts existing browser tokens. nexus_launcher/nexus_platform/prototype_host.py loads these only for the Creator route. learning/studio.py receives the existing Back action from the single browser header. Academy remains optional; Studio actions do not require a running lesson.

Existing create, updateItem, geometry clamping, grouping/ungrouping, upload type/size limits, safe HTTPS/actions, canvas drag/resize, save, preview and independent progress remain owners. Quick Text/Image/Button/Shape entries are presets of existing components. No publication authority is added. Locked objects cannot be deleted with the new shortcuts/context actions.

Properties appear only for the selected type. Position belongs to the inspector, not a permanent tool category. Page background/settings appear when selection is cleared. Layers are separate from properties; details/context actions provide non-drag, keyboard-accessible operations. Ctrl+D duplicates within existing element/link limits; Delete and arrows respect locking and text-input/IME focus. Native select popups in the touched inspector are replaced by keyboard-operable disclosures that invoke the original select change handler.

## Files

Added: assets/studio/workspace.js, assets/studio/workspace.css, tests/test_studio_redesign.py, nexus_launcher/studio_visual_qa.py, this audit and packaging/specs/NexusPortableStudio.spec.
Updated: nexus_launcher/nexus_platform/prototype_host.py, nexus_launcher/nexus_platform/learning/studio.py, assets/academy/editor-adapter.js, assets/academy/strings.json, DESIGN.md, UX-CONTRACT.md.
Removed: no source files. Legacy category UI is hidden only in Creator; the original reference page builder remains available.

## Limits and next work

Resources are an honest view of media used in the current document; Blob uploads remain session-local as before. Fonts/video asset libraries, timeline, new responsive overrides and arbitrary NEXUS data components are not simulated. Compact view constrains the existing canvas width, not a new responsive layout engine. Undo/redo was absent and remains future work. Practice documents remain independent from production project publication.

Next recommended phase: durable resource imports and project presentation integration, before new media courses or publication workflows.

## Acceptance evidence

24 focused engine/Academy/Studio/AssetServer tests passed. New actual-WebEngine workflow verifies component search/no-results, PNG upload through the original file-input path, type-specific inspector, grouping/ungrouping, locked geometry, order, hide/show, save and preview. Full suite: 520 passed, 17 skipped, 3 failures: two device-binding tests require the absent sibling website_NexusMC/db/auth.ts; the unchanged Windows long-path test reports WinError 206. No editor test failed. Complete output: D:/nexus2/studio-tests-v27.log.

Ruff passed for the configured presentation modules and changed Python/test modules. Node syntax checks passed for both adapters. Learning and existing presentation/filter Pyright projects passed with zero errors, using configured Qt dependency paths. The bare manifest Pyright command first reported missing PySide6 imports; configured extraPaths resolve them. PyInstaller v27 succeeded; bundled workspace.js matches source SHA256.

Real Windows screenshots were inspected at 1280×800, 1366×768, 900×650, 640×480, plus the picker, selected text inspector and packaged launcher. D:/nexus2/studio-audit-v27 contains images and geometry/script reports. Frozen smoke passed real action validation, minimize/restore and separate persistence; JavaScript errors are empty. Static premium audit still reports 16 actionless-button findings in unchanged ui2 HTML/template files: those use delegated handlers in launcher.js, which the literal scanner does not infer. This is not a clean static-audit result; its output is retained at D:/nexus2/studio-premium-v27.json.

Production v27 launched after graceful v26 close. Both Minecraft instances and all seven original data files, including Academy progress, were copied with matching SHA256. Backup: D:/nexus2/backups/v26-data-before-studio-v27. QA data is archived separately; no test practice files were transferred to user data. Executable: D:/nexus2/deliverables-v27/NEXUS-2.0-Portable-v27/NEXUS-2.0-Portable-v27.exe.
