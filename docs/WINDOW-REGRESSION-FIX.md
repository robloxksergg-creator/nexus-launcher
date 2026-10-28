# Native window regression — v30

Scope: native launcher window only. No CSS, Studio, canvas, Academy, or editor changes.

The v29 change replaced Qt/Windows restore behavior with immediate setGeometry after showNormal and another resize 80ms later. Removed these competing geometry writes and the saved rectangle/state guard. Maximize/restore now exclusively uses showMaximized/showNormal; minimize remains showMinimized and close remains close. Vector button painting and double-click isolation remain.

Evidence: supplied screenshot shows content/chrome at a smaller size with black unused area. A real Windows DesignHost regression test measured a maximized 2560x1032 native window, a 2560x996 QWebEngineView, but a 1200x684 Chromium viewport at 250ms. At 1500ms the original implementation converged. Thus transient renderer lag was reproduced; the exact persistent screenshot state was not independently reproduced, and that initial failure alone does not prove the timer caused persistent renderer lag. Removing manual geometry writes isolates the risky v29 change and restores native state ownership rather than adding renderer CSS workarounds.

No 1014x570 constants were introduced or removed. Existing host startup size 1366x768, minimum 1000x640, unrestricted maximum, frameless resizable Qt window remain. Startup uses native showMaximized. Available work area is respected, fullscreen remains separate. No forced centering or monitor-resolution constants.

Changed: nexus_launcher/nexus_platform/window_chrome.py; tests/test_design_host.py (native vs embedded renderer viewport regression); packaging/specs/NexusPortableWindowRegression.spec (v30 artifact). Existing chrome tests cover changed restored geometry, minimize, keyboard controls, double-click and close. Existing renderer checks cover 1280x720, 1366x768, 1920x1080, 2560x1440. New test checks five native maximize/restore cycles and page viewport after compositor settlement. 13 tests passed on real Windows backend; Ruff passed; configured Pyright 0 errors/warnings. PyInstaller build succeeded.

Manual mouse edge-drag/taskbar interaction was not performed; native control integration is exercised through actual Qt controls and Windows backend tests. Packaged smoke and preserved-data verification are recorded in D:/nexus2/window-regression-audit-v30.
