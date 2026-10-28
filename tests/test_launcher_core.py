import json
from concurrent.futures import ThreadPoolExecutor

import nexus_launcher.launcher_core as launcher_core
import pytest
from nexus_launcher.launcher_core import MinecraftLauncher, java_major, offline_uuid, valid_username


def test_username_validation():
    assert valid_username("Player_123")
    assert not valid_username("ab")
    assert not valid_username("игрок")


def test_bad_resolution_is_rejected_before_java_or_install(tmp_path, monkeypatch):
    core = MinecraftLauncher(tmp_path)
    monkeypatch.setattr(core, "_java", lambda **_: pytest.fail("Java started for invalid resolution"))
    with pytest.raises(ValueError, match="разрешение"):
        core.launch("1.21.1", "Player", 4096, resolution_width=1920, resolution_height=0)


def test_offline_uuid_is_stable():
    assert offline_uuid("Notch") == "b50ad385-829d-3141-a216-7e7d7539ba7f"


def test_java_major_reads_modern_java_version(monkeypatch):
    class Result:
        returncode = 0
        stderr = 'openjdk version "21.0.11" 2026-04-21 LTS'
        stdout = ""

    monkeypatch.setattr("nexus_launcher.launcher_core.subprocess.run", lambda *args, **kwargs: Result())
    assert java_major("java") == 21


def test_profile_merge_appends_arguments(tmp_path):
    launcher = MinecraftLauncher(tmp_path)
    base = {
        "libraries": [{"name": "base"}],
        "arguments": {"jvm": ["-Dbase=1"], "game": ["--base"]},
        "mainClass": "Base",
    }
    child = {
        "libraries": [{"name": "child"}],
        "arguments": {"jvm": ["-Dchild=1"], "game": ["--child"]},
        "mainClass": "Child",
    }
    merged = launcher._merge_profile(base, child)
    assert merged["mainClass"] == "Child"
    assert merged["arguments"]["jvm"] == ["-Dbase=1", "-Dchild=1"]


def test_existing_fabric_profile_is_used_without_network_install(tmp_path, monkeypatch):
    launcher = MinecraftLauncher(tmp_path)
    installed = "fabric-loader-0.19.3-1.21.1"
    profile = tmp_path / "versions" / installed / f"{installed}.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}", encoding="utf-8")

    class Loader:
        def get_installed_version(self, minecraft_version, loader_version):
            assert (minecraft_version, loader_version) == ("1.21.1", "0.19.3")
            return installed

        def install(self, *_args, **_kwargs):
            raise AssertionError("Fabric installer must not access the network")

    monkeypatch.setattr("nexus_launcher.launcher_core.minecraft_launcher_lib.mod_loader.get_mod_loader", lambda _name: Loader())
    assert launcher.ensure_fabric("1.21.1", "0.19.3") == installed


def test_install_repairs_game_but_skips_mojang_java(tmp_path, monkeypatch):
    launcher = MinecraftLauncher(tmp_path)
    monkeypatch.setattr(launcher, "_java", lambda **_: "verified-java-21")
    profile = tmp_path / "versions/1.21.1/1.21.1.json"
    profile.parent.mkdir(parents=True)
    data = {
        "id": "1.21.1",
        "libraries": [],
        "javaVersion": {"component": "java-runtime-delta"},
        "downloads": {"client": {"url": "https://example.invalid/client.jar", "sha1": "abc"}},
    }
    profile.write_text(json.dumps(data), encoding="utf-8")
    calls = []
    install = launcher_core.minecraft_launcher_lib.install
    monkeypatch.setattr(install, "install_libraries", lambda *a, **k: calls.append("libraries"))
    monkeypatch.setattr(install, "install_assets", lambda *a, **k: calls.append("assets"))
    monkeypatch.setattr(install, "download_file", lambda *a, **k: calls.append("client"))
    monkeypatch.setattr(
        launcher_core, "_install_bundled_java", lambda *a, **k: pytest.fail("Mojang JVM network access")
    )
    assert launcher.install("1.21.1") == data
    assert calls == ["libraries", "assets", "client"]
    assert json.loads(profile.read_text(encoding="utf-8")) == data
    assert not launcher_core._external_java.get()


def test_no_valid_java_does_not_begin_install(tmp_path, monkeypatch):
    launcher = MinecraftLauncher(tmp_path)

    def missing():
        raise RuntimeError("Java 21 required")

    monkeypatch.setattr(launcher, "_java", missing)
    monkeypatch.setattr(
        launcher_core.minecraft_launcher_lib.install,
        "install_minecraft_version",
        lambda *a, **k: pytest.fail("Installation started without Java"),
    )
    with pytest.raises(RuntimeError, match="Java 21"):
        launcher.install("1.21.1")
    assert not launcher_core._external_java.get()


def test_loader_context_is_nested_thread_local_and_restored_on_failure(tmp_path, monkeypatch):
    launcher = MinecraftLauncher(tmp_path)
    monkeypatch.setattr(launcher, "_java", lambda **_: "verified-java-21")
    calls = []
    monkeypatch.setattr(launcher_core, "_install_bundled_java", lambda *a, **k: calls.append("other-thread"))

    class Loader:
        def install(self):
            launcher_core.minecraft_launcher_lib.install.install_jvm_runtime("ignored", "ignored")
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(
                    launcher_core.minecraft_launcher_lib.install.install_jvm_runtime, "normal", "normal"
                ).result()
            raise ValueError("loader failure")

    with pytest.raises(ValueError, match="loader failure"):
        launcher._install_loader(Loader())
    assert calls == ["other-thread"]
    assert not launcher_core._external_java.get()
