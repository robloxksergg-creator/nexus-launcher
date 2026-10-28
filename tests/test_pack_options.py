import json

from nexus_launcher.pack_options import DEFAULT_SHADER, ensure_visual_defaults


def test_visual_defaults_preserve_options_and_enable_available_packs(tmp_path):
    (tmp_path / "resourcepacks").mkdir()
    (tmp_path / "shaderpacks").mkdir()
    (tmp_path / "resourcepacks" / "FreshAnimations_v1.10.4.zip").write_bytes(b"pack")
    (tmp_path / "shaderpacks" / DEFAULT_SHADER).write_bytes(b"shader")
    (tmp_path / "options.txt").write_text("lang:ru_ru\nfov:0.0\n", encoding="utf-8")

    ensure_visual_defaults(tmp_path)

    values = dict(line.split(":", 1) for line in (tmp_path / "options.txt").read_text(encoding="utf-8").splitlines())
    assert values["lang"] == "ru_ru"
    assert "file/FreshAnimations_v1.10.4.zip" in json.loads(values["resourcePacks"])
    assert "shaderPack" not in values
    assert json.loads(values["resourcePacks"]) == ["vanilla", "mod_resources", "file/FreshAnimations_v1.10.4.zip"]


def test_migration_removes_only_forced_addons_and_keeps_order(tmp_path):
    path = tmp_path / "options.txt"
    packs = [
        "vanilla",
        "mod_resources",
        "file/FreshAnimations_v1.10.4.zip",
        "file/FA+Details-v2.2.1.zip",
        "file/My Pack.zip",
    ]
    path.write_text(
        "resourcePacks:"
        + json.dumps(packs)
        + '\nincompatibleResourcePacks:["file/My Pack.zip"]\nshaderPack:custom.zip\n',
        encoding="utf-8",
    )
    ensure_visual_defaults(tmp_path)
    values = dict(line.split(":", 1) for line in path.read_text().splitlines())
    assert json.loads(values["resourcePacks"]) == [p for p in packs if "FA+Details" not in p]
    assert values["incompatibleResourcePacks"] == '["file/My Pack.zip"]'
    assert values["shaderPack"] == "custom.zip"
    assert (tmp_path / ".nexus-launcher/options-before-visual-migration.txt").is_file()


def test_player_can_disable_base_and_reenable_addons_after_migration(tmp_path):
    ensure_visual_defaults(tmp_path)
    path = tmp_path / "options.txt"
    chosen = 'resourcePacks:["vanilla","file/FA+Details-v2.2.1.zip","file/My Pack.zip"]\n'
    path.write_text(chosen, encoding="utf-8")
    ensure_visual_defaults(tmp_path)
    assert path.read_text(encoding="utf-8") == chosen


def test_existing_empty_selection_stays_empty(tmp_path):
    path = tmp_path / "options.txt"
    path.write_text("resourcePacks:[]\n", encoding="utf-8")
    ensure_visual_defaults(tmp_path)
    assert path.read_text() == "resourcePacks:[]\n"


def test_invalid_selection_is_not_overwritten(tmp_path):
    path = tmp_path / "options.txt"
    path.write_text("resourcePacks:invalid\n", encoding="utf-8")
    ensure_visual_defaults(tmp_path)
    assert path.read_text() == "resourcePacks:invalid\n"
