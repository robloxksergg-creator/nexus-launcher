# Scroll correction — v22

Native wheel bursts now retarget with a fresh Qt timeline. Reversing wheel input starts at the current visible position instead of the queued destination. Precision touchpad and keyboard input cancel queued wheel animation.

Web scrolling now uses one 16 ms scheduler, instead of racing a frame callback against a timer. Stale callbacks and external position changes stop the old motion. This also operates when WebEngine frame callbacks are suspended by native panels. Nested scroll areas remain scrollable.

Both axes of native scroll areas use ScrollBarAlwaysOff; web surfaces hide scrollbar chrome without hiding overflow or reserving a gutter. Existing layout, palette and page animations are retained.

Validation: 52 focused Qt/presentation/Markdown tests passed; deterministic JavaScript burst/reversal/touchpad/keyboard/external-position tests passed; Ruff passed. Packaged Windows smoke loaded with zero script errors and all five content checks passed. 56 protected engine files remain unchanged. Six user data files were backed up and copied with matching SHA256 hashes, including both existing builds.

Executable: D:/nexus2/deliverables-v22/NEXUS-2.0-Portable-v22/NEXUS-2.0-Portable-v22.exe
Data backup: D:/nexus2/backups/v21-data-before-scroll-v22-20261008
Source backup: D:/nexus2/backups/source-before-scroll-v22

Automated checks cover scroll position behavior; subjective smoothness under the user’s particular mouse/refresh rate remains a manual observation.
