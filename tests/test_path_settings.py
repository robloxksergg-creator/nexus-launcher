from types import SimpleNamespace

from nexus_launcher.modern_main import Launcher, SettingsDialog
from PySide6.QtWidgets import QApplication, QDialog


def test_path_settings_round_trip(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    java = tmp_path / "Java 21" / "java.exe"
    java.parent.mkdir()
    java.write_bytes(b"fixture, never executed")
    monkeypatch.setattr("nexus_launcher.modern_main.validate_java", lambda value: value)
    config = {"java_path": str(java), "install_root": str(tmp_path / "packs")}
    dialog = SettingsDialog(None, config)
    assert dialog.values()["java_path"] == str(java)
    assert dialog.values()["install_root"] == str(tmp_path / "packs")
    dialog.accept()
    assert dialog.result() == QDialog.Accepted
    dialog.close()
    assert app is not None


def test_path_settings_reject_relative_directory(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(None, {"install_root": "relative/packs"})
    warnings = []
    monkeypatch.setattr("nexus_launcher.modern_main.QMessageBox.warning", lambda *args: warnings.append(args))
    dialog.accept()
    assert dialog.result() == QDialog.Rejected
    assert warnings
    dialog.close()
    assert app is not None


def test_custom_root_routes_official_pack_without_moving_old_root(tmp_path):
    owner = SimpleNamespace(
        _storage_root=tmp_path / "chosen",
        current_server=SimpleNamespace(instance_id="gear", id="nexus_launcher.main"),
    )
    assert Launcher._instance_dir(owner) == tmp_path / "chosen/instances/gear"
    assert not (tmp_path / "chosen").exists()


def test_paths_persist_in_config(tmp_path, monkeypatch):
    from nexus_launcher.modern_main import load_config

    monkeypatch.setattr("nexus_launcher.modern_main.APP_DIR", tmp_path)
    monkeypatch.setattr("nexus_launcher.modern_main.CONFIG_FILE", tmp_path / "launcher.json")
    config = {"java_path": str(tmp_path / "java.exe"), "install_root": str(tmp_path / "packs")}
    Launcher._save_config(SimpleNamespace(config=config))
    assert load_config() == config
