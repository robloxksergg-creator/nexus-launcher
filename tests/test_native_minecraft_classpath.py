"""Classpath construction parity; paths are strings, never opened or loaded."""
import copy
import json
import ntpath
import posixpath
from types import SimpleNamespace

import pytest

from nexus_launcher import native_minecraft, native_transfer
from tests.test_native_minecraft_command import library


@pytest.fixture
def native():
    module = native_transfer._native
    if getattr(module, "MINECRAFT_CLASSPATH_API_VERSION", None) != 1:
        pytest.skip("Fresh native Minecraft classpath capability unavailable")
    return module


def sample(kind):
    lib = {"name": "org.example:alpha:1.2"}
    data = {"id": "synthetic", "libraries": [lib]}
    if kind == "empty": data["libraries"] = []
    elif kind == "jar": data["jar"] = "parent"
    elif kind == "classifier": lib["name"] += ":client:extra"
    elif kind == "extension": lib["name"] += "@zip"
    elif kind == "native-fallback": lib["synthetic_native"] = "natives-64"
    elif kind == "native-extension":
        lib["name"] += "@zip"; lib["synthetic_native"] = "natives-64"
    elif kind in {"native-path", "native-no-path", "absolute-native-path", "relative-native-path"}:
        lib["synthetic_native"] = "natives-64"
        path = {"path": "org/example/alpha/native.jar"}
        if kind == "native-no-path": path = {"size": 123}
        elif kind == "absolute-native-path": path = {"path": "/synthetic/native.jar"}
        elif kind == "relative-native-path": path = {"path": "../synthetic/native.jar"}
        lib["downloads"] = {"classifiers": {"natives-64": path}}
    elif kind == "duplicate": data["libraries"] += [copy.deepcopy(lib)]
    elif kind == "rule-blocked": lib["rules"] = [{"action": "allow", "os": {"name": "linux"}}]
    elif kind == "rule-allowed": lib["rules"] = [{"action": "allow", "os": {"name": "windows"}}]
    elif kind == "feature-rule": lib["rules"] = [{"action": "allow", "features": {"is_demo_user": True}}]
    elif kind == "unicode": lib["name"] = "org.пример:библиотека:1"
    return data


@pytest.mark.parametrize("kind", ["plain", "empty", "jar", "classifier", "extension", "native-fallback",
    "native-extension", "native-path", "native-no-path", "absolute-native-path", "relative-native-path",
    "duplicate", "rule-blocked", "rule-allowed", "feature-rule", "unicode"])
@pytest.mark.parametrize("path_module,root,separator", [(ntpath, "C:\\Synthetic Game", ";"), (posixpath, "/synthetic game", ":")])
def test_classpath_matches_80(library, native, monkeypatch, kind, path_module, root, separator):
    context = library.get_libraries.__globals__
    monkeypatch.setitem(context, "os", SimpleNamespace(path=path_module))
    monkeypatch.setitem(context, "get_classpath_separator", lambda: separator)
    monkeypatch.setitem(context, "get_natives", lambda item: item.get("synthetic_native", ""))
    monkeypatch.setattr(native_minecraft, "os", SimpleNamespace(path=path_module))
    # Adapter attributes and pinned function globals share the same controlled context.
    monkeypatch.setattr(library, "get_classpath_separator", context["get_classpath_separator"])
    monkeypatch.setattr(library, "get_natives", context["get_natives"])
    data = sample(kind); original = copy.deepcopy(data)
    expected = library.get_libraries(data, root)
    actual = native_minecraft._classpath(data, root, library, native)
    assert actual == expected
    assert data == original
    assert actual.endswith(path_module.join("versions", data.get("jar", data["id"]), data.get("jar", data["id"]) + ".jar"))


def test_missing_capability_uses_old_owner(library):
    data = sample("plain")
    assert native_minecraft._classpath(data, "synthetic", library, SimpleNamespace()) == library.get_libraries(data, "synthetic")


@pytest.mark.parametrize("version", [None, 0, 2])
def test_bad_capability_before_profile_access(version):
    with pytest.raises(ImportError, match="classpath API"):
        native_minecraft._classpath(None, None, None, SimpleNamespace(MINECRAFT_CLASSPATH_API_VERSION=version))


def test_native_failure_not_retried(library):
    calls = []
    def refused(*args): calls.append(args); raise ValueError("synthetic classpath refusal")
    with pytest.raises(ValueError, match="synthetic classpath refusal"):
        native_minecraft._classpath(sample("plain"), "synthetic", library,
            SimpleNamespace(MINECRAFT_CLASSPATH_API_VERSION=1, minecraft_classpath_entries=refused))
    assert len(calls) == 1


def test_rule_rejection_does_not_select_native(library, monkeypatch):
    def forbidden(*_): pytest.fail("Excluded library must not select natives")
    monkeypatch.setattr(library, "get_natives", forbidden)
    seen = []
    def planner(profile, selections): seen.append(selections); return [["versions", "synthetic", "synthetic.jar"]]
    assert native_minecraft._classpath(sample("rule-blocked"), "synthetic", library,
        SimpleNamespace(MINECRAFT_CLASSPATH_API_VERSION=1, minecraft_classpath_entries=planner)).endswith("synthetic.jar")
    assert seen == [[None]]


@pytest.mark.parametrize("data,selections", [
    ({"id": "x", "libraries": []}, [""]),
    ({"id": "x", "libraries": [{"name": "bad"}]}, [""]),
    ({"id": "x", "libraries": [{"name": "g:a:1@zip@jar"}]}, [""]),
    ({"id": "x", "libraries": [{"name": "g:a:1", "downloads": {}}]}, ["native"]),
    ({"id": "x", "libraries": [{"name": "g:a:1", "downloads": {"classifiers": {}}}]}, ["native"]),
    ({"id": "x", "libraries": [{"name": "g:a:1", "downloads": {"classifiers": {"native": {"path": None}}}}]}, ["native"]),
    ({"id": "x", "jar": None, "libraries": []}, []),
    ({"id": "x\0", "libraries": []}, []),
    ({"id": "x", "libraries": [{"name": "." * 251 + ":a:1"}]}, [""]),
])
def test_invalid_native_inputs_refuse(native, data, selections):
    with pytest.raises(ValueError, match="classpath input"):
        native.minecraft_classpath_entries(json.dumps(data), selections)


def test_native_budget_refuses(native):
    with pytest.raises(ValueError, match="classpath input"):
        native.minecraft_classpath_entries(" " * (8 * 1024 * 1024 + 1), [])
    with pytest.raises(ValueError, match="classpath input"):
        native.minecraft_classpath_entries('{"id":"x","libraries":[]}', [None] * 10_001)
