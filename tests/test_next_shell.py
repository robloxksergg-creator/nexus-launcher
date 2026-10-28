import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    import nexus_launcher.modern_main as modern_main
    import nexus_launcher.nexus_platform.window as platform_window
    from nexus_launcher.nexus_platform.next_shell import NexusLauncher

    monkeypatch.setattr(modern_main, "APP_DIR", tmp_path)
    monkeypatch.setattr(modern_main, "CONFIG_FILE", tmp_path / "launcher.json")
    monkeypatch.setattr(modern_main, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(platform_window, "APP_DIR", tmp_path)
    monkeypatch.setattr(platform_window, "CONFIG_FILE", tmp_path / "launcher.json")
    monkeypatch.setattr(modern_main, "detect_java_label", lambda *args: "Java: тест")
    monkeypatch.setattr(platform_window, "detect_java_label", lambda *args: "Java: тест")
    for method in ("_check_servers", "_restore_account_worker", "_refresh_build_access_worker"):
        monkeypatch.setattr(modern_main.Launcher, method, lambda self: None)
    monkeypatch.setattr(NexusLauncher, "_refresh_remote_content", lambda self: None)
    app = QApplication.instance() or QApplication([])
    # Qt's Windows offscreen plugin exposes no OS font families by default.
    # Register local test fonts explicitly; never download or bundle them.
    if not QFontDatabase.families():
        for filename in ("segoeui.ttf", "segoeuib.ttf", "georgia.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + filename)
    window = NexusLauncher()
    window.config["reducedMotion"] = True
    window.show()
    app.processEvents()
    yield app, window, tmp_path
    window.close()
    app.processEvents()


def test_navigation_reuses_original_pages(candidate):
    app, window, _ = candidate
    QTest.mouseClick(window.rail.section_buttons["library"], Qt.LeftButton)
    app.processEvents()
    assert window.pages.currentWidget() is window.instances_page
    QTest.mouseClick(window.rail.settings, Qt.LeftButton)
    app.processEvents()
    assert window.pages.currentWidget() is window.settings_scroll
    assert window.profile.parent() is window.rail
    assert window.rail.section_buttons["library"].accessibleName() == "Мои сборки"


@pytest.mark.parametrize("size", [(1280, 720), (2560, 1080)])
def test_settings_workspace_preserves_controls(candidate, size):
    app, window, _ = candidate
    window.resize(*size)
    window._settings()
    app.processEvents()
    workspace = window.settings_scroll
    assert workspace.width() > 900
    assert workspace.content.width() > workspace.width() / 2
    assert window.settings_page.panels.isVisible()
    workspace.search.setText("Java")
    app.processEvents()
    assert not window.settings_page.categories.item(2).isHidden()
    assert window.settings_page.categories.item(0).isHidden()
    workspace.search.clear()
    window.settings_page.categories.setCurrentRow(5)
    window.settings_page.reduced_motion.setChecked(False)
    app.processEvents()
    assert window.config["reducedMotion"] is False
    if os.environ.get("NEXUS_SETTINGS_CAPTURE") and size[0] == 2560:
        QTest.qWait(220)
        window.grab().save(os.environ["NEXUS_SETTINGS_CAPTURE"])


def test_capture_shell(candidate):
    app, window, _ = candidate
    window.resize(1366, 768)
    window.show_instances()
    app.processEvents()
    if os.environ.get("NEXUS_TEST_CAPTURE"):
        assert window.grab().save(os.environ["NEXUS_TEST_CAPTURE"])


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080), (2560, 1080), (3840, 2160)])
def test_presentation_preserves_prototype_proportions_on_wide_screens(candidate, size):
    app, window, _ = candidate
    window.resize(*size)
    window.show_catalog()
    QTest.qWait(220)
    app.processEvents()
    page = window.discover_page
    assert page.host.width() <= 1600
    assert page.host.width() <= page.viewport().width()
    assert page.hero.width() <= 1520
    assert page.hero.height() == (530 if page.viewport().width() >= 1400 else 440)
    assert not page.hero.mask().contains(page.hero.rect().topLeft())
    assert page.tabs.count() == 4
    if size == (2560, 1080) and os.environ.get("NEXUS_WIDE_CAPTURE"):
        assert window.grab().save(os.environ["NEXUS_WIDE_CAPTURE"])


def test_pack_content_and_maintenance_share_consistent_navigation(candidate):
    app, window, _ = candidate
    instance = window.instance_service.create("Тест категорий", "1.21.1", "vanilla")
    page = window.instances_page
    page.refresh(instance.id)
    window._navigate("library", "NEXUS / МОИ СБОРКИ")
    app.processEvents()
    assert [page.detail.tabText(index) for index in range(page.detail.count())] == ["Обзор", "Моды", "Ресурс-паки", "Миры", "Дата-паки", "Шейдеры", "Настройки", "Файлы и копии"]
    assert all(listing.count() == 0 for listing, _ in page.content_lists.values())
    assert [page.advanced_tabs.tabText(index) for index in range(page.advanced_tabs.count())] == ["Файлы", "Логи", "Резервные копии"]


@pytest.mark.parametrize("size", [(1280, 720), (1366, 768), (1920, 1080)])
def test_approved_routes_and_profile_have_no_footer_popup(candidate, size):
    app, window, _ = candidate
    window.resize(*size)
    window.show_catalog()
    app.processEvents()
    assert window.pages.currentWidget() is window.discover_page
    assert window.discover_page.art.has_image()
    assert "Georgia" not in window.styleSheet()
    assert window.status_bar.isHidden()
    if os.environ.get("NEXUS_OVERVIEW_CAPTURE") and size == (1366, 768):
        assert window.grab().save(os.environ["NEXUS_OVERVIEW_CAPTURE"])
    QTest.mouseClick(window.profile, Qt.LeftButton)
    app.processEvents()
    assert window.pages.currentWidget() is window.profile_page
    assert not hasattr(window, "_profile_popup")
    assert window.profile_page.login.isVisible()
    assert window.profile_page.register.isVisible()
    assert window.profile_page.viewport().rect().contains(window.profile_page.login.mapTo(window.profile_page.viewport(), window.profile_page.login.rect().center()))
    if os.environ.get("NEXUS_PROFILE_CAPTURE") and size == (1366, 768):
        assert window.grab().save(os.environ["NEXUS_PROFILE_CAPTURE"])


def test_save_world_is_local_and_independent_from_installation(candidate):
    app, window, _ = candidate
    server = window.world_views[0].server
    window.resize(1366, 768)
    window.show_server(server)
    app.processEvents()
    assert window.pages.currentWidget() is window.world_page
    assert window.world_page.media.poster.has_image()
    before = window.instance_service.list()
    QTest.mouseClick(window.world_page.save, Qt.LeftButton)
    assert server.id in window.config["savedWorlds"]
    assert window.instance_service.list() == before
    QTest.mouseClick(window.rail.section_buttons["saved"], Qt.LeftButton)
    app.processEvents()
    assert window.pages.currentWidget() is window.saved_worlds
    assert window.saved_worlds.entries.count() == 1
    window.show_server(server)
    app.processEvents()
    if os.environ.get("NEXUS_WORLD_CAPTURE"):
        assert window.grab().save(os.environ["NEXUS_WORLD_CAPTURE"])
    QTest.mouseClick(window.world_page.save, Qt.LeftButton)
    assert server.id not in window.config["savedWorlds"]


@pytest.mark.parametrize("size", [(1280, 720), (1366, 768), (1920, 1080)])
def test_world_content_never_exceeds_its_scroll_viewport(candidate, size):
    from PySide6.QtWidgets import QScrollArea
    app, window, _ = candidate
    window.resize(*size)
    window.show_server(window.world_views[0].server)
    app.processEvents()
    surface = window.world_page.findChild(QScrollArea)
    assert surface.widget().width() <= surface.viewport().width()
    assert window.world_page.play.isVisible()
    assert window.world_page.play.width() >= 180
    assert window.world_page.info.isVisible() == (window.world_page.width() >= 1000)


def test_sign_in_reveal_and_logged_out_profile_state(candidate, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QLineEdit
    from nexus_launcher.nexus_platform.next_shell import NexusLogin
    app, window, _ = candidate
    dialog = NexusLogin(window)
    dialog.show()
    app.processEvents()
    assert dialog.password.echoMode() == QLineEdit.Password
    QTest.mouseClick(dialog.reveal, Qt.LeftButton)
    assert dialog.password.echoMode() == QLineEdit.Normal
    dialog.reject()
    window.account_profile = SimpleNamespace(minecraft_nick="TestPlayer")
    window.profile_page.sync()
    assert window.profile_page.name.text() == "TestPlayer"
    assert window.profile_page.login.isHidden()
    monkeypatch.setattr(window.account_client, "logout", lambda: None)
    window._logout_account()
    assert window.account_profile is None
    assert not window.profile_page.login.isHidden()
    assert window.registration_button.isVisible()
    assert window.profile.text() == "NEXUS профиль"


def test_pack_cards_open_detail_and_filter_without_writing_manifests(candidate):
    app, window, _ = candidate
    instance = window.instance_service.create("Тестовая сборка", "1.21.1", "vanilla")
    page = window.instances_page
    window.show_instances()
    app.processEvents()
    assert page.library_stack.currentWidget() is page.library
    assert not page.page_state.isVisible()
    assert page.pack_cards.count() == 1
    if os.environ.get("NEXUS_PACK_CAPTURE"):
        window.resize(1366, 768)
        app.processEvents()
        assert window.grab().save(os.environ["NEXUS_PACK_CAPTURE"])
    page._open_card(page.pack_cards.item(0))
    assert page.current.id == instance.id
    assert page.library_stack.currentWidget() is page.detail_surface
    app.processEvents()
    assert page.page_state.isVisible()
    page.show_library()
    page.pack_search.setText("не существует")
    assert page.pack_cards.item(0).isHidden()
    assert "Ничего не найдено" in page.library_status.text()
    page.pack_search.clear()
    assert not page.pack_cards.item(0).isHidden()
    page.refresh(instance.id)
    assert page.library_stack.currentWidget() is page.detail_surface


def test_collapsed_navigation_can_always_be_restored(candidate):
    app, window, _ = candidate
    QTest.mouseClick(window.navigation_toggle, Qt.LeftButton)
    app.processEvents()
    assert window.rail.isHidden()
    assert window.navigation_toggle.isVisible()
    QTest.mouseClick(window.navigation_toggle, Qt.LeftButton)
    app.processEvents()
    assert not window.rail.isHidden()
    assert window.rail.maximumWidth() == 258
    assert window.rail.width() == 258


@pytest.mark.parametrize("size", [(1280, 720), (1366, 768), (1920, 1080)])
def test_sidebar_buttons_and_settings_remain_in_window(candidate, size):
    app, window, _ = candidate
    window.resize(*size)
    window._settings()
    app.processEvents()
    assert window.rail.geometry().right() < window.width()
    assert window.settings_scroll.width() > 600
    assert window.rail.settings.isVisible()
    for button in window.title_bar.findChildren(QPushButton):
        assert button.geometry().right() < window.title_bar.width()


def test_state_writes_are_isolated(candidate):
    _, window, root = candidate
    window._save_config()
    assert (root / "launcher.json").is_file()
    assert window.instance_service.root == root / "user-instances"


def test_unpinned_world_can_be_shown_without_rebuilding_sidebar(candidate):
    _, window, _ = candidate
    identifier = next(iter(window.rail.buttons))
    if identifier not in window.config.get("pinnedWorlds", []):
        window._toggle_pin(identifier)
    window._toggle_pin(identifier)
    assert window.rail.buttons[identifier].isHidden()
    window._toggle_pin(identifier)
    assert not window.rail.buttons[identifier].isHidden()
