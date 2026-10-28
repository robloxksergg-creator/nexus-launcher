"""Owner-approved old IDs, dual catalog input and conflict preservation."""
import ast
import copy
import json
from pathlib import Path
import re

import pytest

from nexus_launcher.projects import (CatalogConflictError, DEFAULT_PROJECTS,
                                    ProjectCatalog, canonical_server_id)
from nexus_launcher.nexus_platform.config import canonical_world_preferences, remember_world
from nexus_launcher.nexus_platform.models import world_from_server


def entries(identifier="main"):
    return [{"id": "custom", "name": "Custom", "servers": [
        {"id": identifier, "name": "Custom main", "address": "localhost"}]}]


@pytest.mark.parametrize("key", ["projects", "nexus_launcher.projects"])
@pytest.mark.parametrize("identifier", ["main", "nexus_launcher.main"])
def test_both_formats_load_without_rewriting(key, identifier, tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"format": 2, key: entries(identifier)}), encoding="utf-8")
    before = path.read_bytes()
    projects = ProjectCatalog(path).load()
    assert projects[0].id == "custom" and projects[0].servers[0].id == "main"
    assert projects[0].servers[0].name == "Custom main"
    assert path.read_bytes() == before
    assert not path.with_suffix(".json.part").exists()


def test_equal_dual_keys_are_accepted_and_saved_canonically(tmp_path):
    path = tmp_path / "projects.json"; data = entries("nexus_launcher.main")
    path.write_text(json.dumps({"projects": data, "nexus_launcher.projects": data}), encoding="utf-8")
    catalog = ProjectCatalog(path); projects = catalog.load(); catalog.save(projects)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert set(result) == {"format", "projects"}
    assert result["projects"][0]["servers"][0]["id"] == "main"


@pytest.mark.parametrize("operation", ["load", "save"])
def test_conflicting_dual_keys_refuse_without_changes(operation, tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"projects": entries(), "nexus_launcher.projects": []}), encoding="utf-8")
    before = path.read_bytes(); catalog = ProjectCatalog(path)
    with pytest.raises(CatalogConflictError):
        catalog.load() if operation == "load" else catalog.save([])
    assert path.read_bytes() == before
    assert not path.with_suffix(".json.part").exists()


@pytest.mark.parametrize("value", [True, 99, "2"])
def test_unknown_format_is_not_replaced_by_defaults(value, tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"format": value, "projects": entries()}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(CatalogConflictError): ProjectCatalog(path).load()
    assert path.read_bytes() == before


@pytest.mark.parametrize("raw", [
    '{"projects":[],"projects":[]}',
    '{"projects":[{"id":"a","name":"A","servers":[{"id":"one","id":"two"}]}]}',
])
def test_duplicate_json_fields_refused(raw, tmp_path):
    path = tmp_path / "projects.json"; path.write_text(raw, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(CatalogConflictError): ProjectCatalog(path).load()
    with pytest.raises(CatalogConflictError): ProjectCatalog(path).save([])
    assert path.read_bytes() == before


def test_alias_collision_is_not_merged(tmp_path):
    data = entries(); data[0]["servers"].append({"id": "nexus_launcher.main", "name": "Other"})
    path = tmp_path / "projects.json"; path.write_text(json.dumps({"projects": data}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(CatalogConflictError): ProjectCatalog(path).load()
    assert path.read_bytes() == before


def test_unknown_fields_survive_explicit_save(tmp_path):
    data = entries("nexus_launcher.main")
    data[0]["futureProject"] = {"keep": [1, 2]}
    data[0]["servers"][0]["futureServer"] = {"keep": "value"}
    data[0]["servers"][0]["java_major"] = 21
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"format": 2, "nexus_launcher.projects": data, "futureRoot": [1, 2]}), encoding="utf-8")
    catalog = ProjectCatalog(path); projects = catalog.load(); catalog.save(projects)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["futureRoot"] == [1, 2]
    assert result["projects"][0]["futureProject"] == {"keep": [1, 2]}
    assert result["projects"][0]["servers"][0]["futureServer"] == {"keep": "value"}
    assert projects[0].servers[0].java_major == 21
    assert result["projects"][0]["servers"][0]["java_major"] == 21


def test_preferences_projection_retains_source_and_unknown_values():
    config = {"selectedWorld": "nexus_launcher.main", "pinnedWorlds": ["nexus_launcher.main", "main", "custom"],
              "recentWorlds": ["custom", "nexus_launcher.main"], "unknown": {"untouched": True}}
    before = copy.deepcopy(config)
    result = canonical_world_preferences(config)
    assert result["selectedWorld"] == "main"
    assert result["pinnedWorlds"] == ["main", "custom"]
    assert result["recentWorlds"] == ["custom", "main"]
    assert result["unknown"] == config["unknown"] and config == before
    remember_world(result, "nexus_launcher.main")
    assert result["recentWorlds"] == ["main", "custom"]


def test_official_world_projection_matches_unchanged_ui_grammar():
    server = DEFAULT_PROJECTS[0].servers[0]
    assert server.id == canonical_server_id("nexus_launcher.main") == "main"
    world = world_from_server(server, lambda name: name)
    assert world.id == "main" and world.title == "GEARMORPH"
    root = Path(__file__).resolve().parents[1]
    source = ast.parse((root / "nexus_launcher/nexus_platform/design_bridge.py").read_text(encoding="utf-8"))
    node = next(n for n in source.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "IDENTIFIER" for t in n.targets))
    expression = ast.literal_eval(node.value.args[0])
    assert re.fullmatch(expression, world.id)
    assert not re.fullmatch(expression, "../main")
    assert not re.fullmatch(expression, "nexus_launcher.main")
    # This is static boundary evidence, not a live Qt navigation test.
