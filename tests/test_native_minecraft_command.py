"""Command-vector parity with pinned 8.0 definitions; no Java/install/network."""
import ast
import copy
import __future__
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest

from nexus_launcher import native_minecraft, native_transfer

FIXTURE = Path(__file__).parent / "fixtures/minecraft-launcher-lib-8.0"


def _definitions(path, selected, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and (selected is None or node.name in selected)]
    if selected is not None: assert {node.name for node in nodes} == set(selected)
    # Module imports, decorators and installer/network/process entrypoints are absent.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec",
                 flags=__future__.annotations.compiler_flag), namespace)


@pytest.fixture
def library(monkeypatch):
    record = json.loads((FIXTURE / "source.json").read_text(encoding="utf-8"))
    for name, expected in record["fixture_files"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == expected
    context = {"os": os, "json": json, "copy": copy, "re": re,
               "platform": SimpleNamespace(system=lambda: "Windows", architecture=lambda: ("64bit", "")),
               "get_os_version": lambda: "10.0", "get_natives": lambda _: "",
               "get_executable_path": lambda *_: None, "get_library_version": lambda: "8.0",
               "VersionNotFound": type("VersionNotFound", (Exception,), {}), "__name__": "pinned_mcl_reference"}
    _definitions(FIXTURE / "_helper.py", {"get_classpath_separator", "get_library_path", "parse_rule_list",
                 "parse_single_rule", "inherit_json", "_get_lib_name_without_version"}, context)
    _definitions(FIXTURE / "command.py", None, context)
    module = ModuleType("minecraft_launcher_lib")
    module.command = SimpleNamespace(**{key: value for key, value in context.items() if not key.startswith("__")})
    module.install = SimpleNamespace(install_jvm_runtime=lambda *_, **__: None)
    monkeypatch.setitem(sys.modules, "minecraft_launcher_lib", module)
    name = "nexus_launcher.launcher_core"
    previous = sys.modules.pop(name, None)
    package = importlib.import_module("nexus_launcher")
    previous_attr = getattr(package, "launcher_core", None)
    try:
        yield module.command
    finally:
        sys.modules.pop(name, None)
        if previous is not None: sys.modules[name] = previous
        if previous_attr is None:
            if hasattr(package, "launcher_core"): delattr(package, "launcher_core")
        else: package.launcher_core = previous_attr


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(native_transfer, "_native", None)
    elif getattr(native_transfer._native, "MINECRAFT_COMMAND_API_VERSION", None) != 1:
        pytest.skip("Fresh native Minecraft command capability unavailable")


def profile(root, kind="modern"):
    data = {"id": "synthetic", "type": "release", "mainClass": "SyntheticMain", "assets": "synthetic-assets",
            "libraries": [{"name": "com.example:alpha:1.0"}],
            "arguments": {"jvm": ["-Djava.library.path=${natives_directory}", "-cp", "${classpath}",
                                  "-Dlauncher=${launcher_name}/${launcher_version}"],
                          "game": ["--username", "${auth_player_name}", "--uuid", "${auth_uuid}",
                                   "--accessToken", "${auth_access_token}", "--assetsDir", "${assets_root}",
                                   {"rules": [{"action": "allow", "features": {"has_custom_resolution": True}}],
                                    "value": ["--width", "${resolution_width}", "--height", "${resolution_height}"]},
                                   {"compatibilityRules": [{"action": "allow", "os": {"name": "linux"}}],
                                    "value": "never-on-windows"}]},
            "logging": {"client": {"file": {"id": "client.xml"}, "argument": "-Dlog.config=${path}"}}}
    if kind == "legacy":
        data.pop("arguments")
        data["minecraftArguments"] = "--username ${auth_player_name}  --uuid ${auth_uuid} --session ${auth_session}"
    elif kind == "fallback": data["arguments"].pop("jvm")
    elif kind == "empty-jvm": data["arguments"]["jvm"] = []
    elif kind == "runtime": data["javaVersion"] = {"component": "synthetic-runtime"}
    elif kind == "inherited":
        parent = copy.deepcopy(data); parent["id"] = "parent"
        parent_dir = root / "versions/parent"; parent_dir.mkdir(parents=True)
        (parent_dir / "parent.json").write_text(json.dumps(parent), encoding="utf-8")
        data = {"id": "synthetic", "inheritsFrom": "parent", "type": "release", "mainClass": "SyntheticChild",
                "libraries": [{"name": "com.example:alpha:2.0"}], "arguments": {"game": ["--child"]}}
    directory = root / "versions/synthetic"; directory.mkdir(parents=True, exist_ok=True)
    (directory / "synthetic.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def options(mode):
    if mode == "defaults": return {}
    result = {"username": "Synthetic_User", "uuid": "0" * 32, "token": "synthetic-access",
              "executablePath": "synthetic-java", "jvmArguments": ["-Xms1024M", "-Xmx2048M", "-Dliteral=${auth_uuid}"],
              "launcherName": "NEXUS", "launcherVersion": "synthetic-version", "enableLoggingConfig": True,
              "customResolution": True, "resolutionWidth": "1280", "resolutionHeight": "720", "demo": True,
              "server": "synthetic.example", "port": "25565", "disableMultiplayer": True, "disableChat": True}
    if mode == "cascade":
        result["launcherName"] = "${auth_uuid}"
        result["server"] = "${auth_uuid}"
    return result


@pytest.mark.parametrize("kind", ["modern", "legacy", "fallback", "empty-jvm", "runtime", "inherited"])
@pytest.mark.parametrize("mode", ["defaults", "nexus", "cascade"])
def test_vector_matches_pinned_reference(backend, library, tmp_path, kind, mode):
    profile(tmp_path, kind)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    supplied = options(mode); original = copy.deepcopy(supplied)
    expected = library.get_minecraft_command("synthetic", str(tmp_path), supplied)
    actual = native_minecraft.get_minecraft_command("synthetic", str(tmp_path), supplied)
    assert actual == expected
    assert supplied == original and {p: p.read_bytes() for p in before} == before
    assert "never-on-windows" not in actual


def test_real_launcher_preserves_ticket_order_and_command_vector(backend, library, tmp_path, monkeypatch):
    profile(tmp_path)
    core = importlib.import_module("nexus_launcher.launcher_core")
    events = []; calls = []; logs = []
    launcher = core.MinecraftLauncher(tmp_path, log=logs.append)
    monkeypatch.setattr(launcher, "_java", lambda **_: "synthetic-java")
    monkeypatch.setattr(launcher, "install", lambda _: events.append("installed"))
    def ticket():
        assert events == ["installed"]
        events.append("ticket"); return "a" * 64
    def spawn(command, **kwargs):
        assert events == ["installed", "ticket"]
        calls.append((command, kwargs["env"]))
        return SimpleNamespace()
    monkeypatch.setattr(core.subprocess, "Popen", spawn)
    child = launcher.launch("synthetic", "Synthetic_User", 2048, loader="vanilla", java_required_major=21, ticket_supplier=ticket)
    try:
        assert len(calls) == 1 and calls[0][0][0] == "synthetic-java"
        assert calls[0][1]["NEXUS_GAME_TICKET"] == "a" * 64
        assert "--accessToken" in calls[0][0]
        assert not any("a" * 64 in message for message in logs)
    finally: child._nexus_log_handle.close()


@pytest.mark.parametrize("version", [None, 99])
def test_bad_version_does_not_read_profile_or_fallback(library, tmp_path, monkeypatch, version):
    def forbidden(*_, **__): raise AssertionError("No compatibility fallback")
    monkeypatch.setattr(library, "get_minecraft_command", forbidden)
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(MINECRAFT_COMMAND_API_VERSION=version))
    with pytest.raises(ImportError): native_minecraft.get_minecraft_command("missing", tmp_path, {})


def test_native_error_is_not_retried(library, tmp_path, monkeypatch):
    profile(tmp_path); failure = ValueError("synthetic native command failure")
    def fail(_): raise failure
    def forbidden(*_, **__): raise AssertionError("No compatibility fallback")
    monkeypatch.setattr(library, "get_minecraft_command", forbidden)
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(
        MINECRAFT_COMMAND_API_VERSION=1, minecraft_compose_command=fail))
    with pytest.raises(ValueError) as caught: native_minecraft.get_minecraft_command("synthetic", tmp_path, {})
    assert caught.value is failure


def test_native_refusal_prevents_ticket_and_spawn(library, tmp_path, monkeypatch):
    if getattr(native_transfer._native, "MINECRAFT_COMMAND_API_VERSION", None) != 1:
        pytest.skip("Fresh native Minecraft command capability unavailable")
    data = profile(tmp_path); data["mainClass"] = "Invalid\0Class"
    (tmp_path / "versions/synthetic/synthetic.json").write_text(json.dumps(data), encoding="utf-8")
    core = importlib.import_module("nexus_launcher.launcher_core")
    launcher = core.MinecraftLauncher(tmp_path, log=lambda _: None)
    monkeypatch.setattr(launcher, "_java", lambda **_: "synthetic-java")
    monkeypatch.setattr(launcher, "install", lambda _: None)
    def forbidden(*_, **__): raise AssertionError("No ticket/process after native error")
    monkeypatch.setattr(core.subprocess, "Popen", forbidden)
    with pytest.raises(ValueError): launcher.launch("synthetic", "Synthetic_User", 2048, loader="vanilla", java_required_major=21, ticket_supplier=forbidden)
    assert not (tmp_path / ".nexus-launcher/logs").exists()


def _plan():
    return dict(executable="java", user_jvm=[], metadata_jvm=[], fallback_jvm=["unused"],
                main_class="Main", game=[], replacements=[], game_extras=[], tail=[], logging=None)


@pytest.fixture
def native():
    if getattr(native_transfer._native, "MINECRAFT_COMMAND_API_VERSION", None) != 1:
        pytest.skip("Fresh native Minecraft command capability unavailable")
    return native_transfer._native


def test_strict_plan_fields_and_types(native):
    plan = _plan(); plan.pop("tail")
    with pytest.raises(ValueError): native.minecraft_compose_command(plan)
    plan = _plan(); plan["unknown"] = []
    with pytest.raises(ValueError): native.minecraft_compose_command(plan)
    plan = _plan(); plan["user_jvm"] = [123]
    with pytest.raises(TypeError): native.minecraft_compose_command(plan)


def test_expansion_budget_error_contains_no_supplied_value(native):
    plan = _plan(); plan["game"] = ["${x}" * 1024]
    plan["replacements"] = [("${x}", "synthetic-secret" * 200)]
    with pytest.raises(ValueError) as caught: native.minecraft_compose_command(plan)
    assert "synthetic-secret" not in str(caught.value)


def test_ordered_expansion_keeps_raw_fields_literal(native):
    plan = _plan(); plan.update(user_jvm=["${x}"], metadata_jvm=["${x}"], game=["${x}"],
        replacements=[("${x}", "${y}"), ("${y}", "done")], game_extras=["${x}"],
        tail=["${x}"], logging="-Dlog=${x}")
    assert native.minecraft_compose_command(plan) == ["java", "${x}", "done", "-Dlog=${x}", "Main", "done", "${x}", "${x}"]


@pytest.mark.parametrize("change", ["empty", "nul", "count"])
def test_invalid_input_refused(native, change):
    plan = _plan()
    if change == "empty": plan["executable"] = ""
    elif change == "nul": plan["main_class"] = "Bad\0Class"
    else: plan["game"] = ["x"] * 10001
    with pytest.raises(ValueError): native.minecraft_compose_command(plan)


def test_different_dependency_version_refused_before_profile_read(library, tmp_path, monkeypatch):
    monkeypatch.setattr(library, "get_library_version", lambda: "8.1")
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(MINECRAFT_COMMAND_API_VERSION=1))
    with pytest.raises(ImportError): native_minecraft.get_minecraft_command("missing", tmp_path, {})
