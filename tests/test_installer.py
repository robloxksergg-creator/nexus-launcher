import hashlib

import pytest
from nexus_launcher.installer_main import install_payload


@pytest.mark.parametrize("upgrade", [False, True])
def test_clean_install_and_upgrade_preserve_0923_data(tmp_path, upgrade):
    payload = tmp_path / "payload.exe"
    payload.write_bytes(b"fixture, not executable")
    target = tmp_path / "install"
    target.mkdir()
    data = target / "launcher.json"
    data.write_text('{"java_path":"C:/Java/bin/java.exe","install_root":"D:/packs","memory":4096}')
    saved = data.read_bytes()
    if upgrade:
        (target / "NexusLauncher.exe").write_bytes(b"old fixture")
    result = install_payload(payload, target, hashlib.sha256(payload.read_bytes()).hexdigest())
    assert result.read_bytes() == payload.read_bytes()
    assert data.read_bytes() == saved
    if upgrade:
        assert next(target.glob("nexus-setup-*/previous.exe")).read_bytes() == b"old fixture"


def test_corrupt_installer_keeps_original(tmp_path):
    payload = tmp_path / "payload.exe"
    payload.write_bytes(b"wrong")
    target = tmp_path / "NexusLauncher.exe"
    target.write_bytes(b"original")
    with pytest.raises(ValueError):
        install_payload(payload, tmp_path, "0" * 64)
    assert target.read_bytes() == b"original"
