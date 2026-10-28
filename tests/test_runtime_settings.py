from types import SimpleNamespace

import pytest
from nexus_launcher.runtime_settings import required_java, validate_java, validate_storage


@pytest.mark.parametrize(
    "version,expected", [("1.21.1", 21), ("1.20.5", 21), ("1.20.4", 17), ("1.18", 17), ("1.17.1", 16), ("1.16.5", 8)]
)
def test_pack_java_requirements(version, expected):
    assert required_java(version) == expected
    assert required_java(version, 25) == 25


def test_java_probe_and_javaw(tmp_path, monkeypatch):
    java = tmp_path / "java.exe"
    java.touch()
    output = SimpleNamespace(returncode=0, stderr='os.arch = amd64\nopenjdk version "21.0.11"', stdout="")
    monkeypatch.setattr("nexus_launcher.runtime_settings.subprocess.run", lambda *a, **k: output)
    assert validate_java(str(tmp_path / "javaw.exe"), 21) == str(java)
    with pytest.raises(ValueError, match="Java 17"):
        validate_java(str(java), 17)
    output.stderr = 'os.arch = x86\njava version "21.0.11"'
    with pytest.raises(ValueError, match="64"):
        validate_java(str(java), 21)
    java.unlink()
    with pytest.raises(ValueError, match="не найдена"):
        validate_java(str(java))


def test_storage_checks_without_touching_existing_data(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "save").write_bytes(b"keep")
    selected = tmp_path / "new"
    assert validate_storage(str(selected)) == selected
    assert (selected / "instances").is_dir()
    assert (selected / "user-instances").is_dir()
    assert not list(selected.glob("nexus-write-check-*"))
    assert (old / "save").read_bytes() == b"keep"


def test_storage_write_denied(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("fixture denied")

    monkeypatch.setattr("nexus_launcher.runtime_settings.tempfile.mkstemp", denied)
    with pytest.raises(PermissionError):
        validate_storage(str(tmp_path))
