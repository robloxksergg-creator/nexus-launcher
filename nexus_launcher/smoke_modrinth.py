"""Opt-in live install smoke test; writes only inside a disposable instance root."""
import hashlib
import json
from pathlib import Path
import tempfile

from nexus_launcher.modrinth_provider import ModInstaller
from nexus_launcher.user_instances import InstanceService
from nexus_launcher.nexus_platform.catalog_provider import CatalogProvider


def main():
    provider = CatalogProvider()
    response = provider.search_page("sodium", "1.21.1", "fabric")
    project = next(hit for hit in response["hits"] if hit["title"] == "Sodium")
    with tempfile.TemporaryDirectory(prefix="nexus-modrinth-smoke-") as temporary:
        service = InstanceService(Path(temporary))
        instance = service.create("Modrinth smoke", "1.21.1", "fabric", "0.19.3")
        installed = ModInstaller(service, provider).install(instance.id, project["project_id"])
        root = service.path_for(instance.id)
        verified = all(hashlib.sha512((root / "mods" / mod.filename).read_bytes()).hexdigest() == mod.sha512
                       for mod in installed)
        print(json.dumps({"query_total": response["total_hits"], "installed": len(installed),
                          "sha512_verified": verified, "instance_registered_mods": len(service.load(instance.id).installed_mods),
                          "scope": "disposable Fabric 1.21.1 instance; no personal files"}))
        assert installed and verified


if __name__ == "__main__":
    main()
