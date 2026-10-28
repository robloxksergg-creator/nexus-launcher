from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass

from nexus_launcher.resource_limits import MAX_FILE_BYTES, copy_limited, ensure_space, read_limited
from nexus_launcher.safe_paths import checked_path
from nexus_launcher.secure_http import open_https, origin
from nexus_launcher.user_instances import InstalledMod, InstanceService, safe_filename

API = "https://api.modrinth.com/v2"


class ProviderError(RuntimeError):
    pass


@dataclass
class ModSearchResult:
    project_id: str
    title: str
    description: str
    icon_url: str
    downloads: int


class ModrinthProvider:
    def __init__(self, user_agent: str = "NEXUS-Launcher/0.10 (contact@nexusmc.flux-productions.com)"):
        self.user_agent = user_agent

    def _get(self, path: str, params: dict | None = None):
        query = urllib.parse.urlencode(params or {})
        url = f"{API}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with open_https(request, timeout=25, allowed_hosts={"api.modrinth.com"}) as response:
                return json.loads(read_limited(response))
        except Exception as error:
            raise ProviderError(f"Modrinth недоступен: {error}") from error

    def search(self, query: str, minecraft_version: str, loader: str, limit: int = 20) -> list[ModSearchResult]:
        facets = [["project_type:mod"], [f"versions:{minecraft_version}"]]
        if loader != "vanilla":
            facets.append([f"categories:{loader}"])
        payload = self._get("/search", {"query": query, "limit": min(max(limit, 1), 100), "facets": json.dumps(facets)})
        return [
            ModSearchResult(
                hit["project_id"],
                hit["title"],
                hit.get("description", ""),
                hit.get("icon_url") or "",
                int(hit.get("downloads", 0)),
            )
            for hit in payload.get("hits", [])
        ]

    def versions(self, project_id: str, minecraft_version: str, loader: str) -> list[dict]:
        return self._get(
            f"/project/{urllib.parse.quote(project_id)}/version",
            {
                "game_versions": json.dumps([minecraft_version]),
                "loaders": json.dumps([loader]),
            },
        )

    def version(self, version_id: str) -> dict:
        return self._get(f"/version/{urllib.parse.quote(version_id)}")

    def resolve(self, project_id: str, minecraft_version: str, loader: str) -> list[dict]:
        resolved, visiting = {}, set()

        def visit(project: str, exact_version: str = "", required_by: str = ""):
            versions = (
                [self.version(exact_version)] if exact_version else self.versions(project, minecraft_version, loader)
            )
            if not versions:
                raise ProviderError(f"Нет совместимой версии мода {project} для {minecraft_version}/{loader}")
            item = versions[0]
            if ("loaders" in item and loader not in item["loaders"]) or ("game_versions" in item and minecraft_version not in item["game_versions"]):
                raise ProviderError(f"Несовместимая зависимость {project}: требуется {minecraft_version}/{loader}")
            if exact_version and (not item.get("loaders") or not item.get("game_versions")):
                raise ProviderError(f"Не удалось проверить совместимость зависимости {project}")
            key = item["id"]
            if key in resolved:
                if required_by:
                    resolved[key].setdefault("required_by", []).append(required_by)
                return
            if key in visiting:
                return
            visiting.add(key)
            item["required_by"] = [required_by] if required_by else []
            for dependency in item.get("dependencies", []):
                if dependency.get("dependency_type") != "required":
                    continue
                dep_project = dependency.get("project_id")
                dep_version = dependency.get("version_id") or ""
                if dep_project or dep_version:
                    visit(
                        dep_project or self.version(dep_version)["project_id"],
                        dep_version,
                        item.get("project_id", project),
                    )
            visiting.remove(key)
            resolved[key] = item

        visit(project_id)
        return list(resolved.values())


class ModInstaller:
    def __init__(self, instances: InstanceService, provider: ModrinthProvider | None = None):
        self.instances = instances
        self.provider = provider or ModrinthProvider()

    @staticmethod
    def _primary_file(version: dict) -> dict:
        files = version.get("files", [])
        if not files:
            raise ProviderError("Версия мода не содержит файла")
        return next((item for item in files if item.get("primary")), files[0])

    def install(self, instance_id: str, project_id: str, progress=lambda *_: None, *, resolved_versions=None, safety_backup=True) -> list[InstalledMod]:
        instance = self.instances.load(instance_id)
        versions = resolved_versions if resolved_versions is not None else self.provider.resolve(project_id, instance.minecraft_version, instance.loader)
        for version in versions:
            if ("loaders" in version and instance.loader not in version["loaders"]) or ("game_versions" in version and instance.minecraft_version not in version["game_versions"]):
                raise ProviderError("Сборка изменилась: повторите выбор совместимой версии")
        from nexus_launcher.instance_backups import BackupService
        if safety_backup:
            BackupService(self.instances).create(instance_id, label="before-mod-install")
        root = self.instances.path_for(instance_id)
        installed = []
        for index, version in enumerate(versions, 1):
            file = self._primary_file(version)
            filename = safe_filename(file["filename"])
            expected = file.get("hashes", {}).get("sha512", "")
            if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{128}", expected):
                raise ProviderError("Обязательный SHA-512 отсутствует или некорректен")
            if origin(file["url"])[1] != "cdn.modrinth.com":
                raise ProviderError("Недоверенный источник файла Modrinth")
            checked_path(root, "mods/" + filename)
            expected_size = file.get("size", 0)
            if type(expected_size) is not int or not 0 <= expected_size <= MAX_FILE_BYTES:
                raise ProviderError("Invalid mod file size")
            ensure_space(root, expected_size or MAX_FILE_BYTES)
            request = urllib.request.Request(file["url"], headers={"User-Agent": self.provider.user_agent})
            fd, temporary = tempfile.mkstemp(prefix=filename, suffix=".part", dir=root / ".nexus/cache/downloads")
            digest = hashlib.sha512()
            try:
                with (
                    os.fdopen(fd, "wb") as output,
                    open_https(request, timeout=60, allowed_hosts={"cdn.modrinth.com"}) as response,
                ):
                    received = copy_limited(response, output, expected_size or MAX_FILE_BYTES, digest)
                if not received or expected_size and received != expected_size:
                    raise ProviderError("Mod file size mismatch")
                if digest.hexdigest().lower() != expected.lower():
                    raise ProviderError(f"SHA-512 не совпал для {filename}")
                os.replace(temporary, checked_path(root, "mods/" + filename))
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            mod = InstalledMod(
                version["project_id"],
                version["id"],
                version.get("name") or filename,
                filename,
                digest.hexdigest(),
                True,
                version.get("required_by", []),
            )
            previous = next((old for old in instance.installed_mods if old.project_id == mod.project_id), None)
            if previous and previous.filename != filename:
                for directory in ("mods", "disabled_mods"):
                    old_file = root / directory / safe_filename(previous.filename)
                    if old_file.is_file():
                        old_file.unlink()
            instance.installed_mods = [old for old in instance.installed_mods if old.project_id != mod.project_id]
            instance.installed_mods.append(mod)
            installed.append(mod)
            progress(index, len(versions))
        self.instances.save(instance)
        self.instances.audit(instance_id, "modrinth_install", {"nexus_launcher.projects": [mod.project_id for mod in installed]})
        return installed

    def available_updates(self, instance_id: str) -> list[tuple[InstalledMod, dict]]:
        instance = self.instances.load(instance_id)
        updates = []
        for mod in instance.installed_mods:
            if mod.project_id.startswith("local:"):
                continue
            versions = self.provider.versions(mod.project_id, instance.minecraft_version, instance.loader)
            if versions and versions[0]["id"] != mod.version_id:
                updates.append((mod, versions[0]))
        return updates

    def update_all(self, instance_id: str, progress=lambda *_: None) -> list[InstalledMod]:
        updates = self.available_updates(instance_id)
        if updates:
            from nexus_launcher.instance_backups import BackupService
            BackupService(self.instances).create(instance_id, label="before-mod-update")
        completed = []
        for index, (mod, _version) in enumerate(updates, 1):
            completed.extend(self.install(instance_id, mod.project_id, safety_backup=False))
            progress(index, len(updates))
        return completed
