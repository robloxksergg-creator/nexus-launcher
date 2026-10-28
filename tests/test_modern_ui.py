import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from nexus_launcher.modern_main import Launcher
from nexus_launcher.nexus_account import NexusProfile
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea


@pytest.fixture(autouse=True)
def isolated_ui_workers(monkeypatch):
    # These are geometry/control tests, not network/account integration tests.
    monkeypatch.setattr(Launcher, "_check_servers", lambda self: None)
    monkeypatch.setattr(Launcher, "_restore_account_worker", lambda self: None)
    monkeypatch.setattr(Launcher, "_refresh_build_access_worker", lambda self: None)


def test_server_selection_updates_details():
    _app = QApplication.instance() or QApplication([])
    window = Launcher()
    assert window.current_server is not None
    assert window.details_title.text() == window.current_server.name
    assert window.details_version.text() == window.current_server.minecraft_version
    assert not window.catalog_play.isEnabled()  # No authenticated account.
    window.close()


def test_responsive_sizes_have_no_horizontal_catalog_scrollbar():
    app = QApplication.instance() or QApplication([])
    window = Launcher()
    for width, height in ((980, 650), (1200, 760), (1280, 720), (1366, 768), (1600, 900), (1920, 1080)):
        window.resize(width, height)
        window.show()
        app.processEvents()
        assert window.width() == width
        catalog_scroll = window.catalog.findChild(QScrollArea)
        assert catalog_scroll.horizontalScrollBar().maximum() == 0
    window.close()


def test_maximize_control_toggles_window_state():
    app = QApplication.instance() or QApplication([])
    window = Launcher()
    window.show()
    app.processEvents()
    maximize = window.maximize_button
    QTest.mouseClick(maximize, Qt.LeftButton)
    app.processEvents()
    assert window.isMaximized()
    assert maximize.toolTip() == "Восстановить"
    QTest.mouseClick(maximize, Qt.LeftButton)
    app.processEvents()
    assert not window.isMaximized()
    assert maximize.toolTip() == "Развернуть"
    window.close()


def test_play_button_becomes_stop_after_launch():
    _app = QApplication.instance() or QApplication([])
    window = Launcher()
    window._launched(1234)
    assert window.catalog_play.isEnabled()
    assert "ОСТАНОВИТЬ" in window.catalog_play.text()
    window.close()


def test_user_stop_does_not_show_crash_dialog(monkeypatch):
    _app = QApplication.instance() or QApplication([])
    window = Launcher()
    window.stop_requested = True
    monkeypatch.setattr(
        "nexus_launcher.modern_main.QMessageBox.critical",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no crash dialog expected")),
    )
    window._game_exited(1)
    assert window.status.text() == "Minecraft остановлен пользователем"
    window.close()


def test_nexus_skin_is_first_local_loader(tmp_path):
    _app = QApplication.instance() or QApplication([])
    window = Launcher()
    window.account_profile = NexusProfile("Builder", "builder@nexus.test", skin_png=b"png")
    window._sync_skin_for_instance(tmp_path)
    config = json.loads((tmp_path / "CustomSkinLoader" / "CustomSkinLoader.json").read_text(encoding="utf-8"))
    assert config["loadlist"][0]["name"] == "NEXUS LocalSkin"
    assert (tmp_path / "CustomSkinLoader" / "LocalSkin" / "skins" / "Builder.png").read_bytes() == b"png"
    assert config["forceDisableCache"] is True
    window.close()
