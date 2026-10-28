import pytest

from nexus_launcher.nexus_platform.config import migrate_private_config


@pytest.mark.parametrize("payload", ['{broken', '[]', '{"configVersion":true}', '{"configVersion":0}', '{"configVersion":"two"}'])
def test_invalid_config_is_not_overwritten(tmp_path, payload):
    path = tmp_path / "launcher.json"
    path.write_text(payload, encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        migrate_private_config(path, ["nexus_launcher.main"])
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
