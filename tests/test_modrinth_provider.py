from nexus_launcher.modrinth_provider import ModrinthProvider

import pytest


def test_exact_dependency_requires_compatible_loader_and_game(monkeypatch):
    provider = ModrinthProvider()
    monkeypatch.setattr(provider, "versions", lambda *_: [{"id": "root", "project_id": "root",
        "dependencies": [{"dependency_type": "required", "project_id": "dep", "version_id": "exact"}]}])
    monkeypatch.setattr(provider, "version", lambda *_: {"id": "exact", "project_id": "dep",
        "loaders": ["neoforge"], "game_versions": ["1.21.1"]})
    with pytest.raises(Exception, match="Несовместимая зависимость"):
        provider.resolve("root", "1.21.1", "fabric")


def test_dependency_resolver_orders_required_dependency_first(monkeypatch):
    provider = ModrinthProvider()
    versions = {
        "root": [
            {
                "id": "v-root",
                "project_id": "root",
                "files": [],
                "dependencies": [{"dependency_type": "required", "project_id": "dep"}],
            }
        ],
        "dep": [{"id": "v-dep", "project_id": "dep", "files": [], "dependencies": []}],
    }
    monkeypatch.setattr(provider, "versions", lambda project, *_: versions[project])
    result = provider.resolve("root", "1.21.1", "fabric")
    assert [item["project_id"] for item in result] == ["dep", "root"]
    assert result[0]["required_by"] == ["root"]
