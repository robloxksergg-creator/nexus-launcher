# NEXUS migration ledger

## Baseline

Current user decision: the new prototype exclusively owns visual direction; old launcher owns working services only. SettingsWorkspace now reparents existing category/panel controls into the prototype's full workspace with local category/value search. No settings schema, launch handler, account contract or protected manifest changes. Full prototype parity remains pending; this change is one migrated workflow, not completion of the whole launcher.

Source copied from `E:/nexus-work/work/rc-1.0.0-rc.1-source` on 2026-10-03. Includes 1.0.0 release identity, original Python modules, assets and platform package. Original directories, installed user data and production untouched. No global runtime/library upgrade.

## Slices

| Slice | Status | Evidence / remaining work |
| --- | --- | --- |
| Isolated baseline | Ready | Separate launcher-next; offline disposable preview |
| Native shell | Implemented, partial verification | Labels, collapse, footer profile/settings, cube, original service wiring |
| Settings geometry | Implemented, partial verification | Removed 900px minimum; bounded scroll |
| Pack collection | Implemented, partial verification | Compact responsive cards, local search, detail/back routing; original instance workspace and services retained |
| Modrinth mod catalogue | Implemented, partial verification | Context-locked version/loader, category/side/sort, paging, stale-safe reads; existing resolver/installer preserved; live Sodium install smoke passed |
| Website-linked registration | Implemented, live email acceptance pending | Shared existing NEXUS endpoints; email code + device binding; existing sign-in/session client unchanged |
| Manifest trust/version + atomic mod install | Pending | P1 audit findings; must precede production use |
| Pack detail/world catalogue/profile/editor migration | Pending | Existing detail pages retained; collection and mod catalogue migrated |
| Real device/DPI/Minecraft QA | Partial | 1.21.1 isolated demo runtime passed; full install/auth and other version matrix remain pending |

## Preview

Run `E:/nexus-work/.build-venv-py312/Scripts/python.exe -m preview_next` from this directory. It creates disposable APPDATA and disables automatic account/server polling and self-update. Explicit Modrinth searches/installs, registration and sign-in use live services. Accounts created are real website accounts; manual sign-in saves a session in the existing OS keyring and uses the persistent launcher device identity. Any draft instances created here disappear when preview exits normally. Do not import valuable personal saves. Minecraft/Microsoft authentication is not validated by this preview.

## Rollback

Installed launcher is unchanged. Close candidate and continue using old executable. Candidate is not an update and has not been published. Retain legacy service/UI code until each replacement workflow passes its complete regression matrix.
# Approved presentation replacement — 2026-10-04

User rejected the mixed old/new EXE. Native adapters now replace home, world presentation and account popup, and replace the global stylesheet. Exact Gearmorph Minecraft artwork is copied from the approved prototype's local asset owner. Account footer opens a full route, with real account login/register/refresh/logout and website editing. Separate Saved Worlds stores bookmarks in launcher config without installing files. The duplicate inner pack library is hidden (model retained); pack identity and Play move above content tabs.

This is **not complete prototype feature parity**. Still pending: full pack creation/avatar four-step wizard, all eight content categories and header docking, rich native profile editor/integrations/visibility, creator analytics, split catalogue panes, grid/layer page studio and all designer tools. Existing advanced pack/runtime/backup operations remain available through their service-backed tabs. Unconnected author/news/media sources are labeled unavailable, not fabricated. Core manifest/account/install modules remain under the byte-identity guard. No production release or updater change.

# Wide-screen correction and pack content — 2026-10-04

Following user screenshot at 2560×1080, restore prototype container max-width 1600 and centered alignment, home Hero 530px on wide workspaces, real rounded clipping and four world presentation tabs. Previously unrestricted width + 440px height severely cropped the artwork; this was implementation drift, not an approved redesign. Personal pack content now separates Mods / Resource Packs / Worlds / Data Packs / Shaders from a collapsed maintenance group. File listing is read-only; original configuration and backup handlers stay intact. Remote installs for non-mod content, wizard/avatar, profile editor and page studio remain pending.

