# MODRINTH FILTER AUDIT — v24

## A. Before

`nexus_launcher/nexus_platform/mod_catalog.py` used three inline dropdowns: one hardcoded category, client/server side and sorting. Changing any option immediately submitted search. Version/loader were permanently taken from the current instance. Query changes invalidated old responses, pagination used offset/20, and opening a project preserved results. State lived in widget values, with no Apply draft or active chips.

`nexus_launcher/nexus_platform/catalog_provider.py` constructed mod + instance version + loader/category facets directly and optionally used deprecated `client_side`/`server_side`. Its bounded HTTPS transport, five-minute/64-response cache, generation checks and existing installer are retained.

[Before screenshot](D:/nexus2/filter-audit-v24/before-filters.png)

## B. Root cause

The widget model only represented one category and two approximate sides. It had no tag catalogue, independent state, OR multi-selection, or draft/apply boundary. Adding dropdowns would preserve those limits.

## C. After

```text
FilterPanel (draft, cancel / Escape)
    -> ModrinthFilterState (immutable applied snapshot)
    -> ModrinthQueryBuilder (AND / OR facets, index, query, offset)
    -> CatalogProvider (existing verified API transport/cache)
    -> Modrinth Search API
```

The persistent search header has one Filter button, removable active chips, Reset All, a separate sort control and result count/range. The modal dialog groups searchable checkbox lists for versions/loaders/categories; environment and extra flags are separate. No new colors, fonts, radii or page chrome were introduced. Native Fusion popup ownership remains consistent with the launcher.

Draft changes send no search requests. Apply submits one snapshot, chip removal/sort immediately submit one new search, and pagination keeps filters/query. A query change resets offset but preserves filters. Reopening the same instance restores its query/filter/page during the running session; other instances receive their own defaults. Closing/reopening the dialog discards unsubmitted changes. Enter applies; Escape cancels or closes a popup. Space and arrows work in lists; Ctrl+A does not toggle the checked filters.

## D. Supported filters

- Project type: **mod only**. The existing installer does not support installing modpacks/resource packs/shaders through this workspace, so those choices are not exposed.
- Minecraft versions: official `/tag/game_version`; 918 real values at verification, searchable and multi-select.
- Loaders: official `/tag/loader`, intersected with existing `user_instances.VALID_LOADERS` capabilities: Fabric, Forge, NeoForge. Quilt and server-plugin loaders are intentionally not offered because this launcher cannot create/install those instances.
- Categories: official `/tag/category`, restricted to mod categories; 19 real values at verification, searchable and multi-select, with Clear and selected-value summaries.
- Environment: all ten values documented by Modrinth, including Client + Server, client/server-only and optional counterparts, singleplayer and dedicated server.
- Open source: real `open_source:true`; unchecked means no restriction.
- Non-archived: real `disclosure_types != archived`.
- Sort: relevance, downloads, follows, newest, updated — sent to the server.

Reset restores mod + current instance version/loader, any environment, no categories/open-source/archive restriction, and relevance. It keeps the query. Up to 64 selected values per group prevents invalid/unbounded facets. Editing filters never edits instance files. Known-incompatible result installs are disabled; broader discovery shows actual matched project version/loader metadata. The unchanged resolver still verifies precise version/file compatibility.

## E. Facet mapping

[Official Modrinth search documentation](https://docs.modrinth.com/api/operations/searchprojects/) defines OR within each inner array and AND between arrays; loaders share the categories facet. The catalogue adapter now uses `environment`, not deprecated side fields.

```json
[
  ["project_type:mod"],
  ["versions:1.21.1", "versions:1.21.4"],
  ["categories:fabric"],
  ["categories:optimization", "categories:adventure"],
  ["environment:client_and_server"],
  ["open_source:true"],
  ["disclosure_types != archived"]
]
```

`query=sodium`, `index=downloads`, `offset=20`, `limit=20` are independent of facets. JSON/URL assembly stays outside widgets. Existing read-only search_page callers keep their signature; legacy side arguments are translated into real environment OR groups.

Actual requests/responses: [filter-live-v24.json](D:/nexus2/filter-live-v24.json).

| Live search | Projects |
|---|---:|
| Mod type only | 76 958 |
| Minecraft 1.21.1 | 31 931 |
| Fabric | 46 792 |
| Optimization | 3 556 |
| Client + Server | 42 053 |
| sodium | 107 |
| sodium + Fabric + 1.21.1 + Optimization | 28 |
| Open source | 43 290 |
| Exclude archived | 73 476 |

These are observed API counts, not pinned UI constants. Version/category/loader/environment and archive facets were checked against returned hits.

## F. Tests and real installation

- Latest focused catalogue/filter/host/provider suite: **51 passed**. Includes defaults, supported/invalid project types, versions/loaders/categories/environment, reset, chips/removal, all sorting indices, query/pagination, exact facets, AND/OR, empty filters, immutable snapshots, cancellation/stale response rejection, no request storm, per-instance restoration, incompatibility guards, keyboard and metadata failure/retry state.
- Latest dedicated model/panel suite: **37 passed**.
- Full project suite: **510 passed, 5 skipped, 1 failed**. The failure is the pre-existing `test_windows_pinning` long-file-name case, WinError 206 at protected `nexus_launcher/safe_paths.py:233`. Five platform/privilege/opt-in skips remain explicit. Two later keyboard/failure tests and final keyboard handler were covered by the subsequent focused suite; full-suite totals therefore differ from the final focused collection.
- Opt-in real API + Windows UI + installation: **1 passed**. Sodium (`AANobbMI`, `sodium-fabric-0.8.13+mc1.21.1.jar`) was installed through the actual Install signal into a temporary QA instance, using the unchanged resolver/installer and SHA-512/file transactions. No Minecraft launch or real user instance mutation occurred.
- This isolated Python runtime initially failed CDN issuer validation with its default CA store. The live installation test uses the trusted Mozilla CA file via `SSL_CERT_FILE` **for the test only**. TLS verification was not disabled; protected TLS/provider/download code was not changed. This result does not establish that every machine's default certificate store is healthy.
- Pyright: **0 errors / 0 warnings** across configured presentation modules plus new catalogue modules.
- Ruff and DESIGN.md lint: **passed**.
- Strict static UI audit still reports the **same 15 baseline** delegated HTML-button findings; none were added. This is not claimed as a green static audit. Runtime command/action tests remain passing.
- Final packaged Windows smoke: loaded, no script errors, all content checks and filter draft/one-Apply/environment/category checks passed. Its screenshot/data use explicitly labelled offline fixtures, not the live-tag screenshots below.

Logs: [focused](D:/nexus2/filter-focused-final-v24.log), [full](D:/nexus2/filter-acceptance-v24.log), [live UI](D:/nexus2/filter-live-ui-v24.log), [typecheck](D:/nexus2/filter-typecheck-v24.log), [frozen smoke](D:/nexus2/frozen-filters-v24.json).

## G. Screenshots

Real Modrinth data was loaded in the actual Windows Qt launcher, rather than fabricated cards.

[After filter panel — 1280×720](D:/nexus2/filter-audit-v24/filters-1280x720.png)

[After catalogue — 1280×720](D:/nexus2/filter-audit-v24/results-1280x720.png)

[After catalogue — 1366×768](D:/nexus2/filter-audit-v24/results-1366x768.png)

[After catalogue — 1920×1080](D:/nexus2/filter-audit-v24/results-1920x1080.png)

[After catalogue — 2560×1440](D:/nexus2/filter-audit-v24/results-2560x1440.png)

## H. Responsive verification

All four requested logical window sizes were exercised. The dialog measured 850×602 and each list column 263–264 px, fitting the smallest window. Results retained a usable viewport (>250 px), footer actions stayed inside the workspace, and the persistent sidebar remained visible. Active chip overflow stays inside its own scrollable strip and cannot stretch the workspace.

Geometry/install record: [live-ui-results.json](D:/nexus2/filter-audit-v24/live-ui-results.json).

## I. Safety, delivery and limitations

All 56 protected engine files match their prior SHA-256 values. Installer, dependency resolution, compatibility authority, SHA-512, filesystem transactions, launcher engine, updater/signing/release manifests, Identity/Website/backend/Cloudflare and production infrastructure were not changed. Existing page layout and v23 scrolling behavior are retained; one scoped Qt enum spelling was modernized in the presentation bridge for type validation.

Both existing builds and six data files were backed up/copied with identical SHA-256 values. Post-launch verification found no changes to those six files.

Executable: [NEXUS v24](D:/nexus2/deliverables-v24/NEXUS-2.0-Portable-v24/NEXUS-2.0-Portable-v24.exe)

SHA-256: `5D4AE8E10DBF860ADF2ED50460C8B73CE9570354083063CE47FC479E15D4F730`

Data backup: `D:/nexus2/backups/v23-data-before-filters-v24-20261008`

Source backup: `D:/nexus2/backups/source-before-filters-v24`

Filters/query/page state is preserved for the running session, not newly persisted to user configuration. Tag retrieval is lazy, asynchronous and cached; on failure the dialog retains selected real-instance values, reports the problem and offers retry. Cancelling a queued search cancels its future; an already-running bounded HTTP request can finish, but its stale generation cannot replace current results. Version/loader search can be broadened without changing the target instance; precise installer compatibility remains independently enforced. Other project types, unsupported instance loaders, arbitrary extra disclosure filters and production TLS changes are outside this scoped redesign.
