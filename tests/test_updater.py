import hashlib
import io
import json
import zipfile
from unittest.mock import patch

import pytest
from nexus_launcher.updater import ModpackUpdater, OptionalMod, PackFile, PackRelease, _safe_member, fetch_manifest


class Reply(io.BytesIO):
    def __init__(self, value):
        raw = json.dumps(value).encode() if isinstance(value, dict) else value
        super().__init__(raw)
        self.headers = {"Content-Length": str(len(raw))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_safe_member_rejects_traversal():
    with pytest.raises(ValueError):
        _safe_member("../evil.exe")
    assert _safe_member("mods/example.jar").as_posix() == "mods/example.jar"
    assert _safe_member("saves/world.dat") is None


def test_apply_update_and_delete_with_state(tmp_path):
    game = tmp_path / "game"
    (game / "mods").mkdir(parents=True)
    (game / "mods" / "old.jar").write_bytes(b"old")
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("mods/new.jar", b"new")
        output.writestr(".nexusbot-delete.txt", "mods/old.jar\n")
        output.writestr("saves/forbidden.dat", b"no")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    release = PackRelease("2.0", "https://example.test/pack.zip", digest)
    updater = ModpackUpdater(game)
    updater.apply(archive, release)
    assert (game / "mods" / "new.jar").read_bytes() == b"new"
    assert not (game / "mods" / "old.jar").exists()
    assert not (game / "saves" / "forbidden.dat").exists()
    assert updater.installed_version == "2.0"


def test_audit_preserves_extra_mod_and_reports_drift(tmp_path):
    game = tmp_path / "game"
    (game / "mods").mkdir(parents=True)
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("mods/required.jar", b"required")
    release = PackRelease("3.0", "https://example.test/pack.zip", hashlib.sha256(archive.read_bytes()).hexdigest())
    updater = ModpackUpdater(game)
    updater.apply(archive, release)
    (game / "mods" / "extra.jar").write_bytes(b"extra")
    (game / "mods" / "required.jar").write_bytes(b"changed")
    result = updater.audit_managed_files()
    assert result["changed"] == ["mods/required.jar"]
    assert result["extras"] == ["mods/extra.jar"]
    assert (game / "mods" / "extra.jar").read_bytes() == b"extra"


def test_reads_file_manifest_and_runtime_versions():
    content = b"mod-v1"
    payload = {
        "pack": "gearmorph",
        "version": "2.0",
        "minecraft": "1.21.1",
        "loader": "neoforge",
        "loaderVersion": "21.1.248",
        "visibility": "internal",
        "files": [
            {
                "id": "example",
                "name": "Example",
                "version": "1",
                "path": "mods/example.jar",
                "url": "https://nexusmc.flux-productions.com/mod.jar",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "required": True,
                "type": "mod",
            }
        ],
    }
    with patch("nexus_launcher.updater.open_https", return_value=Reply(payload)):
        release = fetch_manifest("https://example.test/manifest.json")
    assert release.minecraft == "1.21.1"
    assert release.loader == "neoforge"
    assert release.loader_version == "21.1.248"
    assert release.files[0].path == "mods/example.jar"


def test_file_manifest_updates_removes_owned_and_preserves_user_file(tmp_path):
    game = tmp_path / "game"
    (game / "mods").mkdir(parents=True)
    (game / "mods" / "old.jar").write_bytes(b"old")
    (game / "mods" / "personal.jar").write_bytes(b"personal")
    state = game / ".nexus-launcher"
    state.mkdir()
    (state / "pack.json").write_text(
        json.dumps({"managed_files": {"mods/old.jar": hashlib.sha256(b"old").hexdigest()}})
    )
    new = b"new-version"
    entry = PackFile(
        "new",
        "New mod",
        "2",
        "mods/new.jar",
        "https://nexusmc.flux-productions.com/new.jar",
        len(new),
        hashlib.sha256(new).hexdigest(),
        True,
        "mod",
    )
    release = PackRelease(
        "2", "", "", pack="gearmorph", minecraft="1.21.1", loader="neoforge", loader_version="21.1.248", files=(entry,)
    )
    with patch("nexus_launcher.updater.open_https", return_value=Reply(new)):
        ModpackUpdater(game)._sync_files(release)
    assert (game / "mods" / "new.jar").read_bytes() == new
    assert not (game / "mods" / "old.jar").exists()
    assert (game / "mods" / "personal.jar").read_bytes() == b"personal"


def test_file_manifest_rejects_non_https_and_bad_path():
    base = {
        "version": "1",
        "files": [
            {
                "id": "x",
                "name": "x",
                "version": "1",
                "path": "../x.jar",
                "url": "http://bad.test/x",
                "size": 1,
                "sha256": "0" * 64,
                "type": "mod",
            }
        ],
    }
    with patch("nexus_launcher.updater.open_https", return_value=Reply(base)), pytest.raises(ValueError):
        fetch_manifest("https://example.test/manifest")


def test_manifest_rejects_duplicate_paths_and_untrusted_hosts():
    item = {
        "id": "x",
        "name": "x",
        "version": "1",
        "path": "mods/x.jar",
        "url": "https://malicious.invalid/x",
        "size": 1,
        "sha256": "0" * 64,
        "type": "mod",
    }
    with (
        patch("nexus_launcher.updater.open_https", return_value=Reply({"version": "1", "files": [item]})),
        pytest.raises(ValueError, match="Недоверенный"),
    ):
        fetch_manifest("https://nexusmc.flux-productions.com/manifest")
    item["url"] = "https://nexusmc.flux-productions.com/x"
    with (
        patch("nexus_launcher.updater.open_https", return_value=Reply({"version": "1", "files": [item, item]})),
        pytest.raises(ValueError, match="Повторяющийся"),
    ):
        fetch_manifest("https://nexusmc.flux-productions.com/manifest")


def test_optional_and_preserve_files_are_not_overwritten(tmp_path):
    game = tmp_path / "game"
    (game / "config").mkdir(parents=True)
    (game / "config" / "options.txt").write_bytes(b"player")
    preserved = PackFile(
        "p",
        "options",
        "",
        "config/options.txt",
        "https://nexusmc.flux-productions.com/options",
        8,
        hashlib.sha256(b"official").hexdigest(),
        False,
        "config",
        "preserve",
    )
    optional = PackFile(
        "o",
        "optional",
        "",
        "mods/optional.jar",
        "https://nexusmc.flux-productions.com/optional",
        3,
        hashlib.sha256(b"opt").hexdigest(),
        False,
        "mod",
        "optional",
    )
    release = PackRelease("2", "", "", files=(preserved, optional))
    ModpackUpdater(game)._sync_files(release)
    assert (game / "config" / "options.txt").read_bytes() == b"player"
    assert not (game / "mods" / "optional.jar").exists()


def test_required_file_transition_to_preserve_keeps_player_settings(tmp_path):
    game = tmp_path / "game"
    target = game / "config" / "voicechat" / "voicechat-client.properties"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"microphone=Player Device\nmuted=false\n")
    state = game / ".nexus-launcher"
    state.mkdir()
    (state / "pack.json").write_text(
        json.dumps({"managed_files": {"config/voicechat/voicechat-client.properties": "old-pack-hash"}})
    )
    entry = PackFile(
        "voicechat-client",
        "voicechat-client.properties",
        "",
        "config/voicechat/voicechat-client.properties",
        "https://nexusmc.flux-productions.com/voicechat-client.properties",
        8,
        hashlib.sha256(b"official").hexdigest(),
        False,
        "config",
        "preserve",
    )
    ModpackUpdater(game)._sync_files(PackRelease("next", "", "", files=(entry,)))
    assert target.read_bytes() == b"microphone=Player Device\nmuted=false\n"
    saved = json.loads((state / "pack.json").read_text())
    assert "config/voicechat/voicechat-client.properties" not in saved["managed_files"]


def test_download_retries_after_hash_failure(tmp_path):
    good = b"good"
    entry = PackFile(
        "x",
        "x.jar",
        "",
        "mods/x.jar",
        "https://nexusmc.flux-productions.com/x",
        len(good),
        hashlib.sha256(good).hexdigest(),
    )
    release = PackRelease("2", "", "", files=(entry,))
    with patch("nexus_launcher.updater.open_https", side_effect=[Reply(b"bad!"), Reply(good)]):
        ModpackUpdater(tmp_path)._sync_files(release)
    assert (tmp_path / "mods" / "x.jar").read_bytes() == good


def test_interrupted_update_is_rolled_back_on_next_start(tmp_path):
    state = tmp_path / ".nexus-launcher"
    backup = state / "backup-files" / "mods" / "x.jar"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"old")
    target = tmp_path / "mods" / "x.jar"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"partial")
    (state / "pack.json").write_text(json.dumps({"managed_files": {"mods/x.jar": hashlib.sha256(b"old").hexdigest()}}))
    (state / "update-transaction.json").write_text(json.dumps({"changed": ["mods/x.jar"], "removed": []}))
    ModpackUpdater(tmp_path)
    assert target.read_bytes() == b"old"
    assert not (state / "update-transaction.json").exists()


def _optional_release(data=b"dh-v1", version="1"):
    entry = PackFile(
        "distant_horizons",
        "Distant Horizons",
        version,
        "mods/DistantHorizons.jar",
        "https://nexusmc.flux-productions.com/dh.jar",
        len(data),
        hashlib.sha256(data).hexdigest(),
        False,
        "mod",
        "optional",
    )
    mod = OptionalMod("distant_horizons", "Distant Horizons", "LOD", "graphics", files=(entry.path,))
    return PackRelease(version, "", "", files=(entry,), optional_mods=(mod,))


def test_optional_off_is_not_installed_and_repair_does_not_restore(tmp_path):
    updater = ModpackUpdater(tmp_path)
    release = _optional_release()
    updater._sync_files(release)
    assert updater.optional_selections() == {"distant_horizons": False}
    assert not (tmp_path / "mods" / "DistantHorizons.jar").exists()
    updater._sync_files(release, force=True)
    assert not (tmp_path / "mods" / "DistantHorizons.jar").exists()


def test_optional_on_installs_persists_and_disable_moves_to_cache(tmp_path):
    updater = ModpackUpdater(tmp_path)
    release = _optional_release()
    updater._sync_files(release)
    updater.set_optional_enabled("distant_horizons", True)
    with patch("nexus_launcher.updater.open_https", return_value=Reply(b"dh-v1")):
        updater._sync_files(release)
    target = tmp_path / "mods" / "DistantHorizons.jar"
    assert target.read_bytes() == b"dh-v1"
    assert ModpackUpdater(tmp_path).optional_selections()["distant_horizons"] is True
    updater.set_optional_enabled("distant_horizons", False)
    updater._sync_files(release)
    assert not target.exists()
    assert (tmp_path / ".nexus-launcher" / "optional-cache" / target.name).exists()


def test_optional_selection_is_per_build_and_update_replaces_old(tmp_path):
    first, second = ModpackUpdater(tmp_path / "one"), ModpackUpdater(tmp_path / "two")
    first._sync_files(_optional_release())
    second._sync_files(_optional_release())
    first.set_optional_enabled("distant_horizons", True)
    assert second.optional_selections()["distant_horizons"] is False
    with patch("nexus_launcher.updater.open_https", return_value=Reply(b"dh-v1")):
        first._sync_files(_optional_release())
    with patch("nexus_launcher.updater.open_https", return_value=Reply(b"dh-v2")):
        first._sync_files(_optional_release(b"dh-v2", "2"))
    assert (tmp_path / "one" / "mods" / "DistantHorizons.jar").read_bytes() == b"dh-v2"


def test_optional_conflict_and_dependency_validation(tmp_path):
    updater = ModpackUpdater(tmp_path)
    state = updater.state_dir
    state.mkdir(parents=True)
    (state / "pack.json").write_text(
        json.dumps(
            {
                "optional_catalog": [
                    {"id": "a", "dependencies": ["b"], "conflicts": []},
                    {"id": "b", "dependencies": [], "conflicts": ["c"]},
                    {"id": "c", "dependencies": [], "conflicts": []},
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="Сначала"):
        updater.set_optional_enabled("a", True)
    updater.set_optional_enabled("b", True)
    updater.set_optional_enabled("a", True)
    updater.set_optional_enabled("c", True)
    updater.set_optional_enabled("b", False)
    with pytest.raises(ValueError, match="Несовместимо"):
        updater.set_optional_enabled("b", True)
