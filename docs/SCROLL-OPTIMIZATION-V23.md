# Scroll optimization — v23

The v22 QApplication filter traversed widget ancestry even for paint, timer and layout events. V23 rejects these events immediately. A 50,000-call microbenchmark with a 12-level widget fixture measured 599.40 ms before versus 164.41 ms after (3.65x faster). This measures filter overhead only, not screen FPS.

The browser adapter no longer intercepts wheel events, reads computed styles/layout on input, writes scrollTop each tick, or runs a 16 ms script timer. Chromium ScrollAnimatorEnabled handles scrolling; precision trackpad input follows the platform. The reduced-motion setting disables that animator. ShowScrollBars=False and CSS hide chrome without clipping overflow.

Validation: 23 native/presentation/host tests passed on Windows; JavaScript check verifies no input interception, animation clock or forced layout; Ruff passed. Packaged Windows smoke loaded with no script errors and passed all content checks. All 56 protected engine files are unchanged. Both existing builds and all six data files were backed up and transferred with SHA256 equality.

Executable: D:/nexus2/deliverables-v23/NEXUS-2.0-Portable-v23/NEXUS-2.0-Portable-v23.exe
Backup: D:/nexus2/backups/v22-data-before-scroll-v23-20261008

Hardware-specific perceived smoothness still needs observation with the user's mouse and display. This pass removes measured filter overhead and script scrolling work; it does not claim a measured end-to-end FPS improvement.
