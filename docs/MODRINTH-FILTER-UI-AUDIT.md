# Modrinth filter presentation — v25

Implemented a catalogue-integrated filter drawer with compact searchable multi-selectors, category chips and a full searchable category popover, collapsed additional conditions, independent painted sorting, and wrapping removable active chips. Empty active-filter rows disappear. Native combo box/checkbox painting and dotted focus outlines are absent; keyboard focus uses the existing accent border. Controls retain accessible names and keyboard actions.

FilterState, query builder, provider and installer contracts remain unchanged. All four protected filter/business modules and all 56 protected engine files match their pre-change hashes.

Validation: 49 existing catalogue/design-host checks passed before final presentation refinements; 46 focused catalogue checks passed including two new integrated-panel/layout regressions; final filter suite: 39 passed. Real Modrinth Windows acceptance passed at 1280×720, 1366×768, 1920×1080, 2560×1440, including actual verified Sodium installation into an isolated test instance. Ruff passed. Existing Pyright project reports zero errors. Frozen portable smoke loaded successfully with zero JavaScript errors and all content/filter checks true.

Evidence: D:/nexus2/filter-audit-v25 contains integrated-window, selector, category, sorting and expanded-conditions screenshots plus live-ui-results.json and frozen-report.json.

Portable: D:/nexus2/deliverables-v25/NEXUS-2.0-Portable-v25/NEXUS-2.0-Portable-v25.exe. Launched and responding. Both existing user instances retained; six data files verified before and after launch. Backup: D:/nexus2/backups/v24-data-before-filter-ui-v25.

Full suite: 514 passed, 5 skipped, 1 pre-existing failure in tests/test_windows_pinning.py::test_handle_replace_unicode_and_long_path (WinError 206, protected nexus_launcher/safe_paths.py:233; same failure recorded before v25). No filter/catalogue regressions. Full evidence: D:/nexus2/filter-acceptance-v25.log and filter-acceptance-v25.xml.
