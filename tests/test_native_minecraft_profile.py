"""One-level inheritance parity; synthetic profiles, no Java/install/network."""
import copy
import json
from types import SimpleNamespace

import pytest

from nexus_launcher import native_minecraft, native_transfer
from tests.test_native_minecraft_command import library  # pinned, hash-checked reference fixture


def samples(kind):
    parent = {"id": "base", "libraries": [{"name": "g:a:1"}, {"name": "g:b:1"}],
              "arguments": {"game": ["parent"], "jvm": ["-Dparent"]},
              "items": ["parent"], "metadata": {"scalar": "parent", "list": ["parent"]}}
    child = {"id": "child", "inheritsFrom": "base", "libraries": [{"name": "g:a:2"}],
             "arguments": {"game": ["child"]}, "items": ["child"],
             "metadata": {"scalar": "ignored", "list": ["child"]}}
    if kind == "no-child-libraries": child.pop("libraries")
    elif kind == "empty-libraries": child["libraries"] = []
    elif kind == "duplicate-parent": parent["libraries"] += [{"name": "g:b:2"}]
    elif kind == "classifier": child["libraries"] = [{"name": "g:a:2:native"}]
    elif kind == "extension": child["libraries"] = [{"name": "g:a:2@zip"}]
    elif kind == "empty-lists": child["items"] = []; child["arguments"]["game"] = []
    elif kind == "opaque":
        child["unknown"] = {"number": 10**100, "float": -0.0, "unicode": "Тест", "nested": [None, True]}
    elif kind == "replace-root-type": child["items"] = {"value": "child"}
    elif kind == "nested-scalars": child["metadata"] = {"scalar": "ignored", "new": {"v": 1}}
    elif kind == "parent-inherits": parent["inheritsFrom"] = "grandparent-not-read"
    elif kind == "preserve-unknown": parent["unknown"] = {"huge": 10**100, "text": "kept"}
    return child, parent


@pytest.fixture
def native():
    module = native_transfer._native
    if getattr(module, "MINECRAFT_PROFILE_API_VERSION", None) != 1:
        pytest.skip("Fresh native Minecraft profile capability unavailable")
    return module


def write_parent(tmp_path, parent):
    folder = tmp_path / "versions/base"
    folder.mkdir(parents=True)
    target = folder / "base.json"
    target.write_text(json.dumps(parent), encoding="utf-8")
    return target


@pytest.mark.parametrize("kind", ["normal", "no-child-libraries", "empty-libraries", "duplicate-parent",
    "classifier", "extension", "empty-lists", "opaque", "replace-root-type", "nested-scalars",
    "parent-inherits", "preserve-unknown"])
def test_inheritance_matches_80(tmp_path, library, native, kind):
    child, parent = samples(kind)
    target = write_parent(tmp_path, parent)
    original = copy.deepcopy(child); before = target.read_bytes()
    expected = library.inherit_json(copy.deepcopy(child), str(tmp_path))
    result = native_minecraft._inherit_profile(child, str(tmp_path), library, native)
    assert result == expected
    assert child == original and target.read_bytes() == before
    assert [item["name"] for item in result["libraries"]] == [item["name"] for item in expected["libraries"]]
    if kind == "opaque":
        assert result["unknown"]["number"] == 10**100
        assert json.dumps(result["unknown"]) == json.dumps(expected["unknown"])


def test_missing_capability_uses_existing_owner(tmp_path, library):
    child, parent = samples("normal"); write_parent(tmp_path, parent)
    expected = library.inherit_json(copy.deepcopy(child), str(tmp_path))
    assert native_minecraft._inherit_profile(copy.deepcopy(child), str(tmp_path), library, SimpleNamespace()) == expected


@pytest.mark.parametrize("version", [0, 2, None])
def test_incompatible_capability_refuses_before_read(tmp_path, version):
    with pytest.raises(ImportError, match="profile API"):
        native_minecraft._inherit_profile({"inheritsFrom": "absent"}, str(tmp_path), None,
            SimpleNamespace(MINECRAFT_PROFILE_API_VERSION=version))


def test_selected_error_never_falls_back(tmp_path):
    child, parent = samples("normal"); target = write_parent(tmp_path, parent); before = target.read_bytes()
    def refused(*_): raise ValueError("synthetic native refusal")
    def fallback(*_): pytest.fail("selected native error must not retry")
    with pytest.raises(ValueError, match="synthetic native refusal"):
        native_minecraft._inherit_profile(child, str(tmp_path), SimpleNamespace(inherit_json=fallback),
            SimpleNamespace(MINECRAFT_PROFILE_API_VERSION=1, minecraft_inherit_profile=refused))
    assert target.read_bytes() == before


@pytest.mark.parametrize("child,parent", [
    ("null", '{"libraries":[]}'), ('{}', '{"libraries":[]}'),
    ('{"inheritsFrom":1}', '{"libraries":[]}'),
    ('{"inheritsFrom":"base","libraries":null}', '{"libraries":[]}'),
    ('{"inheritsFrom":"base"}', '{}'),
    ('{"inheritsFrom":"base","arguments":{"missing":[]}}', '{"libraries":[],"arguments":{}}'),
    ('{"inheritsFrom":"base","libraries":[{"name":1}]}', '{"libraries":[]}'),
])
def test_native_invalid_shapes_refuse(native, child, parent):
    with pytest.raises(ValueError, match="inheritance input"):
        native.minecraft_inherit_profile(child, parent)


def test_native_input_budget_refuses(native):
    with pytest.raises(ValueError, match="inheritance input"):
        native.minecraft_inherit_profile(" " * (8 * 1024 * 1024 + 1), '{}')


def test_native_library_budget_refuses(native):
    child = json.dumps({"inheritsFrom": "base", "libraries": [{"name": "g:a:1"}] * 10_001})
    with pytest.raises(ValueError, match="inheritance input"):
        native.minecraft_inherit_profile(child, '{"libraries":[]}')
