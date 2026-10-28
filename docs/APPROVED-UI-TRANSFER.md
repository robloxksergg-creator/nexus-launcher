# Exact approved UI transfer

Current status: nexus_launcher/preview_prototype.py and the v4 build now open PrototypeHost with the entire approved source. nexus_launcher/preview_next.py remains the native rollback preview. The paragraphs below describing source-copy-only status are the historical first step, not the current v4 entry point. Full service parity is still pending and is documented in PROJECT-AUDIT-2026-10-04.md.

User explicitly requests the complete prototype code, not a native reconstruction.

Canonical source: ../NEXUS-Design-Review/launcher-stage-1/index.html.
Bundled byte-identical copy: assets/approved-ui/index.html.
SHA256: 6A8DC003E790CF2ABBAA2B961E57790004846A226A995437693B1D9CFAA3DA83.

The existing assets packaging includes this whole file: HTML, CSS, scripts, animations, UI sound implementation and editor code are retained together. tests/test_approved_ui.py checks byte identity and packaging inclusion. This establishes source transfer only, not runtime or feature parity.

The native preview entry point still opens NexusLauncher. It has NOT been switched to this HTML. No new EXE is represented as the completed migration.

Remaining integration must use an isolated renderer and an explicitly enumerated, validated service bridge. Never expose arbitrary filesystem access, Python evaluation, shell execution, raw tokens or manifest replacement to page JavaScript. Remote navigation must not inherit bridge privileges. Account and installation authority stay in existing Python services. The prototype's temporary simulated pack/install/profile handlers must be replaced by service calls before claiming functional parity; preserving all source does not make simulated features real.

Protected Minecraft/Microsoft manifest modules remain unchanged. Existing native preview is retained as rollback until renderer assets, navigation, all service-backed workflows and trust-boundary tests pass.
