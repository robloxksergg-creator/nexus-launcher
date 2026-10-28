"""Pinned 8.0 rule semantics; synthetic contexts, no native OS/game launches."""
import copy
import json
import re
from types import SimpleNamespace

import pytest

from nexus_launcher import native_minecraft, native_transfer
from tests.test_native_minecraft_command import library


@pytest.fixture
def native():
    module = native_transfer._native
    if getattr(module, "MINECRAFT_RULES_API_VERSION", None) != 1:
        pytest.skip("Fresh native Minecraft rules capability unavailable")
    return module


CASES = [[], [{"action": "allow"}], [{"action": "disallow"}],
    [{"action": "allow"}, {"action": "disallow"}],
    [{"action": "disallow"}, {"action": "allow"}],
    *([{"action": "allow", "os": {"name": name}}] for name in ("windows", "linux", "osx", "future")),
    *([{"action": "disallow", "os": {"name": name}}] for name in ("windows", "linux", "osx")),
    *([{"action": "allow", "os": {"arch": arch}}] for arch in ("x86", "x86_64", "future")),
    *([{"action": "allow", "os": {"version": pattern}}] for pattern in (r"10\..*", r"^99", r"(?<=1)0")),
    [{"action": "allow", "os": {"name": "future", "version": r"10\.0", "arch": "x86"}}],
    *([{"action": "allow", "features": {key: False}}] for key in (
        "has_custom_resolution", "is_demo_user", "has_quick_plays_support",
        "is_quick_play_singleplayer", "is_quick_play_multiplayer", "is_quick_play_realms")),
    [{"action": "allow", "features": {"future": True}}],
    [{"action": "disallow", "features": {"is_demo_user": True}}],
    [{"action": "allow", "features": {"is_demo_user": True, "has_custom_resolution": False}}],
]
OPTIONS = [{}, {"customResolution": True, "demo": True, "quickPlayPath": "", "quickPlaySingleplayer": "",
               "quickPlayMultiplayer": "", "quickPlayRealms": ""},
           {"customResolution": False, "demo": True, "quickPlayPath": None, "quickPlayRealms": "synthetic"}]


def context(library, monkeypatch, system="Windows", arch="64bit"):
    host = SimpleNamespace(system=lambda: system, architecture=lambda: (arch, ""))
    monkeypatch.setattr(native_minecraft, "platform", host)
    monkeypatch.setitem(library.parse_rule_list.__globals__, "platform", host)


@pytest.mark.parametrize("rules", CASES)
@pytest.mark.parametrize("options", OPTIONS)
@pytest.mark.parametrize("system,arch", [("Windows", "64bit"), ("Windows", "32bit"), ("Linux", "64bit"), ("Darwin", "64bit")])
def test_rules_match_pinned_80(library, native, monkeypatch, rules, options, system, arch):
    context(library, monkeypatch, system, arch)
    original = copy.deepcopy((rules, options))
    expected = library.parse_rule_list(copy.deepcopy(rules), copy.deepcopy(options))
    assert native_minecraft._rule_list(rules, options, library, native) is expected
    assert (rules, options) == original


@pytest.mark.parametrize("os_fields", [{"name": "linux", "version": "["}, {"version": "[", "name": "linux"}])
def test_regex_error_order_preserved(library, native, monkeypatch, os_fields):
    context(library, monkeypatch)
    rules = [{"action": "allow", "os": os_fields}]
    if next(iter(os_fields)) == "name":
        assert native_minecraft._rule_list(rules, {}, library, native) is False
    else:
        with pytest.raises(re.error): native_minecraft._rule_list(rules, {}, library, native)


def test_architecture_and_regex_only_when_reached(native):
    def forbidden(*_): pytest.fail("Unreached host predicate invoked")
    assert native.minecraft_rules_evaluate('[]', "Windows", [False] * 6, forbidden, forbidden) is True
    rules = '[{"action":"allow","os":{"name":"linux","arch":"x86","version":"["}}]'
    assert native.minecraft_rules_evaluate(rules, "Windows", [False] * 6, forbidden, forbidden) is False
    rules = '[{"action":"allow","os":{"arch":"x86_64"}}]'
    assert native.minecraft_rules_evaluate(rules, "Windows", [False] * 6, forbidden, forbidden) is True


def test_host_exception_retained(native):
    failure = RuntimeError("synthetic host failure")
    def fail(*_): raise failure
    with pytest.raises(RuntimeError) as caught:
        native.minecraft_rules_evaluate('[{"action":"allow","os":{"arch":"x86"}}]', "Windows", [False] * 6, fail, fail)
    assert caught.value is failure


@pytest.mark.parametrize("rules", ["null", "{}", '[{}]', '[{"action":"future"}]',
    '[{"action":"allow","os":[]}]', '[{"action":"allow","features":null}]',
    '[{"action":"allow","os":{"name":1}}]'])
def test_invalid_input_refuses(native, rules):
    with pytest.raises(ValueError, match="rule input"):
        native.minecraft_rules_evaluate(rules, "Windows", [False] * 6, lambda: False, lambda _: False)


def test_limits_and_feature_vector(native):
    for rules in [" " * (1024 * 1024 + 1), json.dumps([{"action": "allow"}] * 1025)]:
        with pytest.raises(ValueError, match="rule input"):
            native.minecraft_rules_evaluate(rules, "Windows", [False] * 6, lambda: False, lambda _: False)
    with pytest.raises(ValueError, match="feature vector"):
        native.minecraft_rules_evaluate('[]', "Windows", [], lambda: False, lambda _: False)


def test_later_invalid_rule_not_evaluated(native):
    assert native.minecraft_rules_evaluate('[{"action":"disallow"},null]', "Windows", [False] * 6, lambda: False, lambda _: False) is False


def test_old_extension_uses_old_owner(library):
    assert native_minecraft._rule_list([{"action": "allow"}], {}, library, SimpleNamespace()) is True


@pytest.mark.parametrize("version", [None, 0, 2])
def test_incompatible_api_before_context_access(version):
    with pytest.raises(ImportError, match="rules API"):
        native_minecraft._rule_list(None, None, None, SimpleNamespace(MINECRAFT_RULES_API_VERSION=version))


def test_selected_failure_not_retried(library):
    calls = []
    def fail(*args): calls.append(args); raise ValueError("synthetic rules refusal")
    with pytest.raises(ValueError, match="synthetic rules refusal"):
        native_minecraft._rule_list([], {}, library,
            SimpleNamespace(MINECRAFT_RULES_API_VERSION=1, minecraft_rules_evaluate=fail))
    assert len(calls) == 1


def test_argument_rule_names_and_library_empty_features(library, monkeypatch):
    calls = []
    def evaluate(rules, system, flags, arch, version):
        calls.append((json.loads(rules), flags)); return not flags[1]
    native = SimpleNamespace(MINECRAFT_RULES_API_VERSION=1, MINECRAFT_CLASSPATH_API_VERSION=1,
        minecraft_rules_evaluate=evaluate,
        minecraft_classpath_entries=lambda data, choices: [["versions", "x", "x.jar"]])
    assert native_minecraft._arguments([{"compatibilityRules": [{"action": "allow"}], "value": "first"},
        {"rules": [{"action": "allow"}], "value": ["second"]}], {}, library, native) == ["first", "second"]
    data = {"id": "x", "libraries": [{"name": "g:a:1", "rules": [{"action": "allow"}]}]}
    native_minecraft._classpath(data, "synthetic", library, native)
    assert len(calls) == 3 and all(flags == [False] * 6 for _, flags in calls)
