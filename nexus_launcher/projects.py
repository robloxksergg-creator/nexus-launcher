from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class ServerProfile:
    id: str
    name: str
    address: str
    manifest_url: str = ""
    minecraft_version: str = "1.21.1"
    loader: str = "vanilla"
    loader_version: str = ""
    news_url: str = ""
    management_type: str = "local"
    working_directory: str = ""
    java_path: str = ""
    server_jar: str = "server.jar"
    min_memory_mb: int = 2048
    max_memory_mb: int = 4096
    additional_arguments: str = ""
    pack_id: str = ""
    local_pack_path: str = ""
    recommended_memory_mb: int = 4096
    artwork: str = ""
    panel_url: str = ""
    panel_server_id: str = ""
    credential_key: str = ""
    instance_id: str = ""
    visibility: str = "public"
    java_major: int = 0


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    servers: tuple[ServerProfile, ...] = field(default_factory=tuple)


DEFAULT_PROJECTS = [
    Project(
        "nexusmc",
        "NexusMC",
        (
            ServerProfile(
                "main",
                "GEARMORPH • NeoForge",
                "5.83.140.209:25698",
                "https://nexusmc-site.robloxksergg.workers.dev/api/launcher/modpacks/gearmorph",
                "1.21.1",
                "neoforge",
                "21.1.248",
                pack_id="nexus-main",
                recommended_memory_mb=6016,
                artwork="gearmorph-world-art.png",
                management_type="pterodactyl",
                panel_url="https://mgr.bisquit.host",
                panel_server_id="0d2ad2ea",
                credential_key="nexusmc/main/bisquit",
                instance_id="gearmorph",
                visibility="internal",
            ),

        ),
    )
]



class CatalogConflictError(ValueError):
    """Ambiguous catalog data must never be replaced by defaults or merged."""


def canonical_server_id(identifier: str) -> str:
    return "main" if identifier == "nexus_launcher.main" else identifier



def _read_catalog(path: Path) -> dict:
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CatalogConflictError("Повторяющееся поле JSON. Файл не изменён.")
            result[key] = value
        return result
    source = path.read_text(encoding="utf-8")
    from nexus_launcher.native_transfer import _native
    if _native is not None and hasattr(_native, "CATALOG_API_VERSION"):
        if _native.CATALOG_API_VERSION != 1:
            raise ImportError("Incompatible NEXUS catalog API")
        try:
            source = _native.catalog_preflight_json(source)
        except ValueError as error:
            raise CatalogConflictError("Каталог не прошёл native-проверку. Файл не изменён.") from error
    return json.loads(source, object_pairs_hook=unique_fields)


def _catalog_items(payload: dict) -> list:
    if not isinstance(payload, dict):
        raise CatalogConflictError("Каталог должен содержать JSON-объект. Файл не изменён.")
    if "format" in payload and (type(payload["format"]) is not int or payload["format"] not in (1, 2)):
        raise CatalogConflictError("Неподдерживаемая версия каталога. Файл не изменён.")
    if "projects" in payload and "nexus_launcher.projects" in payload:
        def exact(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if exact(payload["projects"]) != exact(payload["nexus_launcher.projects"]):
            raise CatalogConflictError("Два формата каталога конфликтуют. Файл не изменён.")
    items = payload.get("projects", payload.get("nexus_launcher.projects", []))
    if not isinstance(items, list):
        raise CatalogConflictError("Некорректный список проектов. Файл не изменён.")
    project_ids = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CatalogConflictError("Некорректная идентичность проекта. Файл не изменён.")
        if item["id"] in project_ids:
            raise CatalogConflictError("Повторяющийся ID проекта. Файл не изменён.")
        project_ids.add(item["id"])
        servers = item.get("servers")
        servers = [item] if servers is None else servers
        if not isinstance(servers, (list, tuple)):
            raise CatalogConflictError("Некорректный список серверов. Файл не изменён.")
        server_ids = set()
        for index, server in enumerate(servers):
            if not isinstance(server, dict):
                raise CatalogConflictError("Некорректный сервер. Файл не изменён.")
            identifier = server.get("id", f"server-{index + 1}")
            if not isinstance(identifier, str):
                raise CatalogConflictError("ID сервера должен быть строкой. Файл не изменён.")
            identifier = canonical_server_id(identifier)
            if identifier in server_ids:
                raise CatalogConflictError("Конфликт ID сервера. Файл не изменён.")
            server_ids.add(identifier)
    return items


class ProjectCatalog:
    def __init__(self, path: Path):
        self.path = path

    def _parse_server(self, item: dict, fallback_id: str) -> ServerProfile:
        # Поддержка старого формата: один сервер находился прямо в проекте.
        return ServerProfile(
            id=canonical_server_id(str(item.get("id", fallback_id))),
            name=str(item.get("name", fallback_id)),
            address=str(item.get("address", item.get("server", ""))),
            manifest_url=str(item.get("manifest_url", "")),
            minecraft_version=str(item.get("minecraft_version", "1.21.1")),
            loader=str(item.get("loader", "vanilla")).lower(),
            loader_version=str(item.get("loader_version", "")),
            news_url=str(item.get("news_url", "")),
            management_type=str(item.get("management_type", item.get("management", {}).get("type", "local"))),
            working_directory=str(
                item.get("working_directory", item.get("management", {}).get("working_directory", ""))
            ),
            java_path=str(item.get("java_path", item.get("management", {}).get("java_path", ""))),
            server_jar=str(item.get("server_jar", item.get("management", {}).get("server_jar", "server.jar"))),
            min_memory_mb=int(item.get("min_memory_mb", item.get("management", {}).get("min_memory_mb", 2048))),
            max_memory_mb=int(item.get("max_memory_mb", item.get("management", {}).get("max_memory_mb", 4096))),
            additional_arguments=str(
                item.get("additional_arguments", item.get("management", {}).get("additional_arguments", ""))
            ),
            pack_id=str(item.get("pack_id", "")),
            local_pack_path=str(item.get("local_pack_path", "")),
            recommended_memory_mb=int(item.get("recommended_memory_mb", 4096)),
            artwork=str(item.get("artwork", "")),
            panel_url=str(item.get("panel_url", "")),
            panel_server_id=str(item.get("panel_server_id", "")),
            credential_key=str(item.get("credential_key", "")),
            instance_id=str(item.get("instance_id", "")),
            visibility=str(item.get("visibility", "public")),
            java_major=int(item.get("java_major", 0)),
        )

    def load(self) -> list[Project]:
        if not self.path.exists():
            self.save(DEFAULT_PROJECTS)
        try:
            payload = _read_catalog(self.path)
            projects = []
            for item in _catalog_items(payload):
                raw_servers = item.get("servers")
                if raw_servers is None:
                    raw_servers = [item]
                servers = tuple(
                    self._parse_server(server, f"server-{index + 1}") for index, server in enumerate(raw_servers)
                )
                if servers:
                    projects.append(Project(str(item["id"]), str(item["name"]), servers))
        except CatalogConflictError:
            raise
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            projects = []
        projects = projects or list(DEFAULT_PROJECTS)
        projects, changed = self._add_missing_default_servers(projects)
        projects, synced = self._sync_official_servers(projects)
        changed = changed or synced
        if changed:
            self.save(projects)
        return projects

    def _add_missing_default_servers(self, projects: list[Project]) -> tuple[list[Project], bool]:
        """Добавляет новые официальные профили, не изменяя пользовательские серверы."""
        defaults = {project.id: project for project in DEFAULT_PROJECTS}
        result: list[Project] = []
        changed = False
        for project in projects:
            default = defaults.get(project.id)
            existing_ids = {server.id for server in project.servers}
            missing = tuple(server for server in default.servers if server.id not in existing_ids) if default else ()
            if missing:
                project = Project(project.id, project.name, project.servers + missing)
                changed = True
            result.append(project)
        return result, changed

    def _sync_official_servers(self, projects: list[Project]) -> tuple[list[Project], bool]:
        """Refresh official network endpoints while preserving local/user fields."""
        defaults = {(project.id, server.id): server for project in DEFAULT_PROJECTS for server in project.servers}
        result: list[Project] = []
        changed = False
        for project in projects:
            servers = []
            for server in project.servers:
                retired_packs = {"building": "nexus-builder", "pinewood": "nexus-pinewood",
                                 "elderfall": "nexus-elderfall", "tech": "nexus-tech"}
                if (project.id == "nexusmc" and server.id in retired_packs
                        and server.pack_id == retired_packs[server.id]):
                    # Retire bundled catalog entries only. Installed instances,
                    # saves and unrelated user server definitions are untouched.
                    changed = True
                    continue
                default = defaults.get((project.id, server.id))
                if default:
                    updated = replace(
                        server,
                        name=default.name,
                        address=default.address,
                        manifest_url=default.manifest_url,
                        minecraft_version=default.minecraft_version,
                        loader=default.loader,
                        loader_version=default.loader_version,
                        pack_id=default.pack_id,
                        local_pack_path=default.local_pack_path,
                        recommended_memory_mb=default.recommended_memory_mb,
                        artwork=default.artwork,
                        management_type=default.management_type,
                        panel_url=default.panel_url,
                        panel_server_id=default.panel_server_id,
                        credential_key=default.credential_key,
                        instance_id=default.instance_id,
                        visibility=default.visibility,
                    )
                    changed = changed or updated != server
                    server = updated
                servers.append(server)
            result.append(Project(project.id, project.name, tuple(servers)))
        return result, changed

    def save(self, projects: list[Project]) -> None:
        # Validate both the caller's identities and any existing dual-format data
        # before creating a temporary file. Unknown stored fields are retained.
        incoming = [asdict(project) for project in projects]
        for project in incoming:
            for server in project["servers"]:
                server["id"] = canonical_server_id(server["id"])
        _catalog_items({"projects": incoming})
        existing = _read_catalog(self.path) if self.path.exists() else {}
        old_items = _catalog_items(existing)
        old_projects = {item["id"]: item for item in old_items}
        merged = []
        for project in incoming:
            old = old_projects.get(project["id"], {})
            old_servers = old.get("servers")
            old_servers = [old] if old_servers is None and old else old_servers or []
            server_fields = {
                canonical_server_id(str(server.get("id", f"server-{index + 1}"))): server
                for index, server in enumerate(old_servers)
            }
            servers = [{**server_fields.get(server["id"], {}), **server} for server in project["servers"]]
            merged.append({**old, **project, "servers": servers})
        payload = {**existing, "format": 2, "projects": merged}
        payload.pop("nexus_launcher.projects", None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.part")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
