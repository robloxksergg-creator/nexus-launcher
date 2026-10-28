# NEXUS 2.0: audit before implementation

2026-10-08. Local working copy D:/nexus2/launcher-next has no .git; status,
branch and log commands return “not a git repository”. No branch invented.
Source copied to ../backups/source-before-ui2-20261008. Engine hashes saved
in ../protected-engine-before.json. Portable user data is separate and retained.

## Architecture

Python / PySide6 6.8.3; Qt WebEngine presentation plus native service workspaces.
No package.json or React routing. PyInstaller packaging/specs/NexusPortable.spec bundles assets.
Entry portable_main → preview_prototype → NexusLauncher services + PrototypeHost.
InstanceService owns manifests/files; PlatformLauncher/CoreLauncher owns launch,
Java, accounts, progress and updater. The browser is off-record, restricted to
whitelisted loopback assets, with no Python objects or filesystem bridge.
Old approved-ui HTML contains extensive session-only mock state. New UI must
consume a sanitized view model and route validated commands to existing owners.

## Functionality matrix (implementation contract)

| Screen/state | Current functionality | Current component | New presentation | Preservation owner |
|---|---|---|---|---|
| Home | Select official world, open library | Prototype discovery / NexusOverview | Cinematic continue hero, actual library, discovery | PlatformLauncher.select_server |
| Builds | Create/import/filter/open | PackLibraryPage / InstanceService | Landscape artwork cards, primary create, honest empty | Same InstanceService and handlers |
| Build detail | Launch, metadata, context menu | InstancePage / PackLibraryPage | Artwork hero, clear content navigation | Existing launch_requested and context |
| Installed mods | Toggle/remove/JAR/install/updates | InstancePage.mods | Compact status rows, search and existing actions | Original selection and handlers |
| Mod discovery/detail | Search/filters/paging/install/dependencies | ModCatalog | Rich list and separate dark project page | CatalogProvider + existing install resolver |
| Resource packs | List/open folder | PackLibraryPage.content_lists | Collection rows and explanatory empty | Existing read-only enumeration and folder handler |
| Local worlds | List/open saves | PackLibraryPage.content_lists | Landscape previews where available | Existing instance path and saves |
| Datapacks | Per-world listing/open saves | PackLibraryPage.content_lists | Clearly scoped collection, no global-install pretence | Existing saves/*/datapacks listing |
| Shaders | List/open folder | PackLibraryPage.content_lists | Collection rows with folder action | Same folder handler |
| Saved worlds | Local save/unsave, open | SavedWorlds / savedWorlds config | Gallery of actual saved IDs | Existing save/config contract |
| Server catalogue | Search/select/pin | WorldsCatalogue / world_views | Discovery artwork, truthful status | Existing world/server models |
| Server detail | Select/play/save/manage | NexusWorldPage / PlatformLauncher | World hero, version, real access, details | Existing selection/play/menu authority |
| Profile | Sign in/out/refresh/skin/site | NexusProfile / NexusAccountClient | Personal space with actual nick/skin/library | Existing account workers; no credentials in JS |
| Settings | Game/Java/storage/network/appearance/advanced | SettingsWorkspace / SettingsPage | Integrated grouped workspace | Original controls/signals/config validation |
| Downloads/update | Progress/speed/error/retry/logs | DownloadsPage | Integrated progress and recovery workspace | Existing updater events and retry |
| Logs/files/backups | Browse/copy/export/restore/delete | LogsPage / InstancePage | Utility navigation, quieter structured controls | Original confirmations and transactions |
| Dialogs | Create/import/login/register/confirm | Native QDialog owners | Shared typography/buttons/focus | Original validation and modal semantics |
| Empty | Explain missing library/content | Native labels / prototype | Visual, explanation, next real action | Shared state components |
| Loading | Search/project/media/progress | ModCatalog / DownloadsPage | Reserved geometry, skeleton/phase text | Request tokens/timeouts retained |
| Errors | Network/install/auth failure/retry | Existing worker bridges/dialogs | Readable explanation, details and retry | Existing error channels retained |

## Direction and foundation

Signature: a large Minecraft landscape with bottom-left world identity and one
clear play/install action, inside quiet compact NEXUS navigation. Artwork carries
the atmosphere; utility controls stay calm. Display: Bahnschrift with Cyrillic
Segoe UI fallback; body Segoe UI; metadata Consolas where it is actual technical
data. Near-black, cool slate, restrained ice-blue primary, semantic statuses.
One canonical Python token owner generates browser CSS and native QSS adapters.
Reusable artwork, state, button, navigation, hero and collection primitives.

## Drift resolved by this authorized redesign

| Earlier rule | Evidence | Resolution |
|---|---|---|
| Preserve exact prototype | Session mock settings/profile and duplicated routes | Retain legacy preview as reference; portable uses new real-data presentation |
| Sidebar disappears completely | Collapsed routes lose context | Compact icon rail, same routes and smooth width transition |
| 13px body / letter fallback N | Small text and blank library covers | Central type scale and seeded landscape fallback |
| Native maintenance hides tabs | Extra click before files/settings/backups | Single consistent build navigation |
| Different palettes in Web/Qt | Independent handwritten styles | Generated web token adapter from theme_tokens |

Production infrastructure, signing and core services are outside the redesign.
Missing authors/news/online counts/IDs are never synthesized as real data.
