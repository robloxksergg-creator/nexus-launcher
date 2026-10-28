"""Existing launch policy parity; no Java/game is downloaded or executed."""
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from nexus_launcher import native_transfer
from nexus_launcher import process_utils as policy


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(native_transfer, "_native", None)
    elif getattr(native_transfer._native, "LAUNCH_POLICY_API_VERSION", None) != 1:
        pytest.skip("Fresh native launch policy unavailable")


@pytest.mark.parametrize("name,expected", [
    ("abc", True), ("A_0", True), ("0123456789ABCDEF", True),
    ("", False), ("ab", False), ("0123456789ABCDEFG", False),
    ("abc\n", False), ("a-b", False), ("имя", False), ("ＡＢＣ", False),
])
def test_username_boundaries(backend, name, expected):
    assert policy.launch_username_valid(name) is expected


def test_environment_values_never_cross_policy(backend):
    class Source(dict):
        def __getitem__(self, key):
            assert key in {"Path", "wındır"}
            return super().__getitem__(key)
    source = Source(Path="bin", wındır="windows", PRIVATE_SECRET="unread",
                    JAVA_TOOL_OPTIONS="unread", NEXUS_GAME_TICKET="unread")
    assert policy.game_environment(source, "new-synthetic-ticket") == {
        "Path": "bin", "wındır": "windows", "NEXUS_GAME_TICKET": "new-synthetic-ticket"}
    assert "NEXUS_GAME_TICKET" not in policy.game_environment(source)


def test_environment_full_allowlist_and_input_preserved(backend):
    source = {key: "synthetic" for key in policy.GAME_ENVIRONMENT_KEYS}
    source.update(JDK_JAVA_OPTIONS="never", _JAVA_OPTIONS="never", PYTHONPATH="never")
    before = dict(source)
    result = policy.game_environment(source)
    assert set(result) == policy.GAME_ENVIRONMENT_KEYS
    assert source == before


@pytest.mark.parametrize("command,expected", [
    ([], []),
    (["java", "Main"], ["java", "Main"]),
    (["java", "--accessToken", "secret", "--clientId", "id"],
     ["java", "--accessToken", "<access-token>", "--clientId", "<access-token>"]),
    (["-Dnexus.gameTicket=synthetic", "--accessToken"],
     ["-Dnexus.gameTicket=<redacted>", "--accessToken"]),
    (["java", "--width", "1280", "--accessToken=legacy-form"],
     ["java", "--width", "1280", "--accessToken=legacy-form"]),
])
def test_exact_existing_redaction_contract(backend, command, expected):
    original = list(command)
    assert policy.redact_launch_command(command) == expected
    assert command == original


@pytest.fixture
def launcher_module(monkeypatch):
    # Isolate the missing external installer dependency. This is not library parity.
    stub = ModuleType("minecraft_launcher_lib")
    stub.install = SimpleNamespace(install_jvm_runtime=lambda *_, **__: None)
    stub.command = SimpleNamespace(get_minecraft_command=lambda *_: [])
    monkeypatch.setitem(sys.modules, "minecraft_launcher_lib", stub)
    name = "nexus_launcher.launcher_core"
    previous = sys.modules.pop(name, None)
    package = importlib.import_module("nexus_launcher")
    previous_attr = getattr(package, "launcher_core", None)
    module = importlib.import_module(name)
    try:
        yield module
    finally:
        sys.modules.pop(name, None)
        if previous is not None: sys.modules[name] = previous
        if previous_attr is None:
            if hasattr(package, "launcher_core"): delattr(package, "launcher_core")
        else: package.launcher_core = previous_attr


def test_real_launcher_wiring_with_synthetic_installer_and_process(backend, launcher_module, tmp_path, monkeypatch):
    module = launcher_module
    logs = []; calls = []
    launcher = module.MinecraftLauncher(tmp_path, log=logs.append)
    monkeypatch.setattr(launcher, "_java", lambda **_: "synthetic-java")
    monkeypatch.setattr(launcher, "install", lambda _: None)
    command = ["synthetic-java", "-Dnexus.gameTicket=synthetic-ticket", "--accessToken", "synthetic-access", "Main"]
    monkeypatch.setattr("nexus_launcher.native_minecraft.get_minecraft_command", lambda *_: list(command))
    monkeypatch.setattr(module.os, "environ", {"Path": "bin", "PRIVATE_SECRET": "never", "JAVA_TOOL_OPTIONS": "never"})
    def process(arguments, **kwargs):
        calls.append((list(arguments), kwargs["env"]))
        return SimpleNamespace()
    monkeypatch.setattr(module.subprocess, "Popen", process)
    instance = launcher.launch("1.21.1", "Synthetic_User", 2048, loader="vanilla", ticket_supplier=lambda: "a" * 64)
    try:
        assert calls == [(command, {"Path": "bin", "NEXUS_GAME_TICKET": "a" * 64})]
        message = next(line for line in logs if line.startswith("Команда Java:"))
        assert "synthetic-ticket" not in message and "synthetic-access" not in message
        assert "<redacted>" in message and "<access-token>" in message
        assert module.valid_username("Synthetic_User")
    finally:
        instance._nexus_log_handle.close()


@pytest.mark.parametrize("version", [99, None])
def test_bad_version_is_not_ignored(monkeypatch, version):
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(LAUNCH_POLICY_API_VERSION=version))
    with pytest.raises(ImportError): policy.game_environment({"PATH": "bin"})
    with pytest.raises(ImportError): policy.launch_username_valid("abc")
    with pytest.raises(ImportError): policy.redact_launch_command(["java"])


def test_native_failure_does_not_read_values_or_retry(monkeypatch):
    class Source(dict):
        def __getitem__(self, key): raise AssertionError("No value read after policy error")
    failure = ValueError("synthetic native policy failure")
    def fail(*_): raise failure
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(
        LAUNCH_POLICY_API_VERSION=1, launch_environment_mask=fail))
    with pytest.raises(ValueError) as caught:
        policy.game_environment(Source(PATH="bin"))
    assert caught.value is failure


@pytest.mark.parametrize("mask", [[], [1], [True, False]])
def test_invalid_native_mask_refused_before_values(monkeypatch, mask):
    class Source(dict):
        def __getitem__(self, key): raise AssertionError("No value read after invalid policy")
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(
        LAUNCH_POLICY_API_VERSION=1, launch_environment_mask=lambda _: mask))
    with pytest.raises(ValueError): policy.game_environment(Source(PATH="bin"))
