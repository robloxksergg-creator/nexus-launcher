import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QLabel

from nexus_launcher.nexus_platform.config import migrate_private_config
from nexus_launcher.nexus_platform.content import RemoteWorldContent
from nexus_launcher.nexus_platform.models import WorldPresentation, WorldTheme
from nexus_launcher.nexus_platform.pages import DownloadsPage
from nexus_launcher.nexus_platform.widgets import HeroMedia
from nexus_launcher.nexus_platform.window import PlatformLauncher
from nexus_launcher.instance_ui import InstancePage
from nexus_launcher.user_instances import InstanceService


@pytest.fixture(autouse=True)
def isolated_workers(monkeypatch, tmp_path):
    import nexus_launcher.modern_main as modern_main
    import nexus_launcher.nexus_platform.window as platform_window
    for module in (modern_main, platform_window):
        monkeypatch.setattr(module, "APP_DIR", tmp_path)
        monkeypatch.setattr(module, "CONFIG_FILE", tmp_path / "launcher.json")
    monkeypatch.setattr(modern_main, "PROJECTS_FILE", tmp_path / "projects.json")
    # Entrypoints migrate configuration before constructing this shell. Tests
    # construct it directly, so exercise the same initialization contract.
    migrate_private_config(tmp_path / "launcher.json", ["nexus_launcher.main"])
    monkeypatch.setattr(PlatformLauncher, "_check_servers", lambda self: None)
    monkeypatch.setattr(PlatformLauncher, "_restore_account_worker", lambda self: None)
    monkeypatch.setattr(PlatformLauncher, "_refresh_build_access_worker", lambda self: None)


def test_config_migration_preserves_legacy_keys_and_creates_backup(tmp_path):
    path = tmp_path / "launcher.json"
    path.write_text(json.dumps({"memory": 6144, "java_path": "C:/Java/java.exe"}), encoding="utf-8")
    migrated = migrate_private_config(path, ["nexus_launcher.main", "building"])
    assert migrated["memory"] == 6144
    assert migrated["java_path"] == "C:/Java/java.exe"
    assert migrated["configVersion"] == 2
    assert migrated["pinnedWorlds"] == ["nexus_launcher.main", "building"]
    assert migrated["videoBackgrounds"] is True
    assert migrated["developer"]["showPerformanceOverlay"] is False
    assert list(tmp_path.glob("launcher.v1.*.backup.json"))


def test_video_release_discards_media_source(tmp_path):
    app = QApplication.instance() or QApplication([])
    poster = tmp_path / "poster.png"
    poster.write_bytes(b"not decoded in this lifecycle test")
    video = tmp_path / "hero.mp4"
    video.write_bytes(b"fixture")
    hero = HeroMedia()
    hero.set_presentation(WorldPresentation(type="video", video=str(video), poster=str(poster)), autoplay=False)
    assert not hero.player.source().isEmpty()
    hero.release()
    assert hero.player.source() == QUrl()
    hero.close()
    assert app is not None


def test_private_shell_routes_without_extra_windows():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    window.show()
    app.processEvents()
    assert window.pages.currentWidget() is window.discover_page
    window.show_server(window.current_server)
    assert window.pages.currentWidget() is window.world_page
    window.show_instances()
    assert window.pages.currentWidget() is window.instances_page
    assert len([widget for widget in app.topLevelWidgets() if widget.isVisible()]) == 1
    window.close()


def test_closed_world_remains_browsable_and_storage_lookup_is_side_effect_free():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    selected = window.current_server
    tile = window.catalogue_page.tiles[selected.id]
    tile.set_access("CLOSED", False)
    assert tile.isEnabled()
    other = window.world_views[-1].server
    assert window._instance_dir_for(other)
    assert window.current_server is selected
    window.close()
    assert app is not None


def test_remote_world_content_validates_caches_and_falls_back(tmp_path, monkeypatch):
    feed = "https://content.nexus.test/worlds.json"
    service = RemoteWorldContent(feed, tmp_path / "worlds.json", {"nexus_launcher.main"})
    payload = {"worlds": [{
        "id": "nexus_launcher.main",
        "name": "GEARMORPH",
        "status": "online",
        "players": 14,
        "maxPlayers": 20,
        "presentation": {
            "type": "video",
            "video": "https://content.nexus.test/gearmorph.mp4",
            "poster": "https://content.nexus.test/gearmorph.webp",
        },
        "theme": {"accent": "#48a9ff", "textMode": "light", "overlayStrength": 0.8},
    }]}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(payload).encode()

    monkeypatch.setattr("nexus_launcher.nexus_platform.content.open_https", lambda *_args, **_kwargs: Response())
    fetched = service.fetch()
    assert fetched["nexus_launcher.main"]["players"] == 14
    assert service.load_cache() == fetched
    with pytest.raises(ValueError):
        service.validate({"worlds": [{
            "id": "nexus_launcher.main",
            "status": "offline",
            "presentation": {"type": "image", "image": "https://evil.test/art.webp"},
        }]})


def test_mouse_focus_is_not_styled_as_focus_visible_but_keyboard_focus_is():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    button = window.rail.section_buttons["settings"]
    window._focus_visible_tracker.eventFilter(button, QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason))
    assert button.property("focusVisible") is False
    window._focus_visible_tracker.eventFilter(button, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
    assert button.property("focusVisible") is True
    window._focus_visible_tracker.eventFilter(button, QEvent(QEvent.MouseButtonPress))
    assert button.property("focusVisible") is False
    window.close()
    assert app is not None


def test_world_rail_selection_follows_route_not_focus():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    world_id = window.current_server.id
    assert window.rail.section_buttons["home"].property("dataActive") is True
    assert window.rail.buttons[world_id].property("dataActive") is False
    window.show_server(window.current_server)
    assert window.rail.selectedWorldId == world_id
    assert window.rail.buttons[world_id].property("ariaCurrent") == "page"
    window._settings()
    assert window.rail.selectedWorldId == ""
    assert window.rail.buttons[world_id].property("dataActive") is False
    assert window.rail.section_buttons["settings"].property("dataActive") is True
    window.close()
    assert app is not None


def test_world_rail_indicators_are_independent_from_selection():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    world_id = window.current_server.id
    button = window.rail.buttons[world_id]
    window.rail.set_status(world_id, "online", 4, 20)
    window.rail.set_update_available(world_id, True)
    window.rail.set_download_progress(world_id, 64, 100)
    assert button.status_dot.isVisibleTo(button)
    assert button.status_dot.property("state") == "online"
    assert button.update_badge.isVisibleTo(button)
    assert button.progress_badge.text() == "64"
    assert "Онлайн · 4/20" in button.tooltip_text
    assert "Доступно обновление" in button.tooltip_text
    assert button.property("dataActive") is False
    window.close()
    assert app is not None


def test_discover_compact_cards_do_not_repeat_world_in_new_section():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    featured_id = window.world_views[0].id
    assert len(window.discover_page.tiles.get(featured_id, [])) <= 1
    for tiles in window.discover_page.tiles.values():
        assert len(tiles) == 1
        assert tiles[0].height() == 116
        descriptions = tiles[0].findChildren(QLabel, "muted")
        assert descriptions and not descriptions[0].isVisible()
    window.close()
    assert app is not None


def test_catalogue_category_chips_are_state_driven_and_filter_tiles():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    page = window.catalogue_page
    page._select_category("TECH")
    assert page.category_chips["TECH"].property("dataActive") is True
    assert page.category_chips["ВСЕ"].property("dataActive") is False
    for world in page.worlds:
        assert page.tiles[world.id].isHidden() is (world.category != "TECH")
    window.close()
    assert app is not None


def test_settings_panels_use_real_config_values_and_emit_appearance_changes():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    page = window.settings_page
    assert page.categories.count() == 10
    assert page.categories.item(9).text() == "Дополнительно"
    game_text = "\n".join(label.text() for label in page.game_values.findChildren(QLabel, "settingLine"))
    assert "Оперативная память" in game_text
    assert str(int(window.config.get("memory", 4096)) // 1024) in game_text
    changes = []
    page.settings_changed.connect(changes.append)
    page.reduced_motion.setChecked(not page.reduced_motion.isChecked())
    assert changes and "reducedMotion" in changes[-1]
    window.close()
    assert app is not None


def test_video_manual_pause_survives_automatic_resume(tmp_path):
    app = QApplication.instance() or QApplication([])
    video = tmp_path / "hero.mp4"
    video.write_bytes(b"fixture")
    poster = tmp_path / "poster.png"
    poster.write_bytes(b"fixture")
    hero = HeroMedia()
    hero.set_presentation(WorldPresentation(type="video", video=str(video), poster=str(poster)), autoplay=True)
    hero.pause(by_user=True)
    hero.resume(automatic=True)
    assert hero.user_paused is True
    hero.resume(automatic=False)
    assert hero.user_paused is False
    hero.close()
    assert app is not None


def test_world_theme_rejects_invalid_remote_accent_foreground():
    theme = WorldTheme(accent="#123456", accent_foreground="javascript:bad").validate()
    assert theme.accent == "#123456"
    assert theme.accent_foreground == "#06111d"


@pytest.mark.parametrize("width,height", [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440)])
def test_primary_pages_have_usable_geometry_at_supported_sizes(width, height):
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    window.resize(width, height)
    window.show()
    for action in (
        window.show_catalog,
        lambda: window._navigate("worlds", "NEXUS / МИРЫ"),
        window._settings,
    ):
        action()
        app.processEvents()
        page = window.pages.currentWidget()
        assert page.width() > 900
        assert page.height() > 580
    window.show_catalog()
    app.processEvents()
    for tiles in window.discover_page.tiles.values():
        for tile in tiles:
            if tile.compact:
                assert tile.title_label.fontMetrics().horizontalAdvance(tile.title_label.text()) <= tile.title_label.width()
    window.close()


def test_downloads_switch_between_purpose_built_empty_and_real_progress():
    app = QApplication.instance() or QApplication([])
    page = DownloadsPage()
    assert page.states.currentWidget() is page.empty
    page.update_progress("GEARMORPH", 42 * 1024 * 1024, 100 * 1024 * 1024, "Скачивание модов")
    assert page.states.currentWidget() is page.active
    assert page.percent.text() == "42%"
    assert "42.0 МБ" in page.bytes.text()
    page.update_progress("", 0, 0)
    assert page.states.currentWidget() is page.empty
    page.close()
    assert app is not None


def test_library_uses_onboarding_without_builds_and_workspace_after_creation(tmp_path):
    app = QApplication.instance() or QApplication([])
    service = InstanceService(tmp_path / "instances")
    page = InstancePage(service)
    assert page.page_state.currentWidget() is page.empty_state
    assert page.launch_button.isHidden()
    instance = service.create("Моя сборка", "1.21.1", "vanilla")
    page.refresh(instance.id)
    assert page.page_state.currentWidget() is page.workspace
    assert not page.launch_button.isHidden()
    assert page.current.id == instance.id
    assert [page.detail.tabText(index) for index in range(page.detail.count())] == ["Обзор", "Моды", "Modrinth", "Файлы", "Настройки", "Логи", "Резервные копии"]
    page.close()
    assert app is not None


def test_worlds_catalogue_reflows_without_oversized_cards():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    page = window.catalogue_page
    window.resize(1280, 720)
    window.show()
    window._navigate("worlds", "NEXUS / МИРЫ")
    app.processEvents()
    assert page._columns == 2
    window.resize(1920, 1080)
    app.processEvents()
    assert page._columns == 3
    assert page.grid_host.maximumWidth() == 1680
    window.close()
    assert app is not None


def test_download_progress_opens_downloads_once_and_survives_navigation():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    window.show_server(window.current_server)
    window._set_status("Скачивание файлов…")
    window._progress(25, 100)
    assert window.pages.currentWidget() is window.downloads_page
    assert window.downloads_page.states.currentWidget() is window.downloads_page.active
    window.show_catalog()
    assert window.downloads_page.percent.text() == "25%"
    window.close()
    assert app is not None


def test_production_titlebar_contains_no_performance_overlay():
    app = QApplication.instance() or QApplication([])
    window = PlatformLauncher()
    texts = " ".join(label.text().upper() for label in window.title_bar.findChildren(QLabel))
    assert "FPS" not in texts and "CPU" not in texts and " LAT " not in f" {texts} "
    assert window.config["developer"]["showPerformanceOverlay"] is False
    window.close()
    assert app is not None
