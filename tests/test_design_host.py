"""Real renderer/workspace checks for the new presentation boundary."""
import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEnginePage

from tests.test_next_shell import candidate  # noqa: F401


def js(app, page, source):
    result = []
    page.runJavaScript(source, lambda value: result.append(value))
    deadline = time.monotonic() + 5
    while not result and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert result, "Renderer did not respond"
    return result[0]


def wait(app, condition):
    deadline = time.monotonic() + 8
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition()


def test_ui2_real_state_routes_geometry_and_actions(candidate, monkeypatch):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, _ = candidate
    instance = services.instance_service.create("Тестовая сборка — длинное название", "1.21.1", "fabric")
    host = DesignHost(services)
    services.hide()
    host.resize(1366, 768)
    host.show()
    loaded = []
    host.view.loadFinished.connect(loaded.append)
    try:
        wait(app, lambda: bool(loaded))
        wait(app, lambda: bool(host._builds))
        host._sync_state(True)
        QTest.qWait(500)
        assert js(app, host.page, "document.body.innerText.includes('Тестовая сборка')")
        assert js(app, host.page, "document.body.innerText.includes('Миры ждут')")
        captures = os.environ.get("NEXUS_UI2_CAPTURE_DIR")
        if captures:
            Path(captures).mkdir(parents=True, exist_ok=True)
        for route in ("home", "catalog", "saved", "profile", "server", "library", "settings", "downloads"):
            js(app, host.page, f"window.NexusUI.navigate({json.dumps(route)},'nexus_launcher.main')")
            QTest.qWait(500)
            assert not js(app, host.page, "Array.from(document.querySelectorAll('button:not(:disabled)')).filter(b=>!b.dataset.route&&!b.dataset.action&&!b.dataset.filter&&!b.onclick&&b.id!=='clear-search').map(b=>b.id||b.textContent).join(',')")
            if route in {"library", "settings", "downloads"}:
                wait(app, lambda: host._library_active and host.library_overlay.isVisible())
                assert host.library_overlay.x() > 190
                assert host.library_overlay.y() >= 64
            if captures:
                host.grab().save(str(Path(captures) / f"{route}-1366.png"))
        if captures:
            downloads = services.downloads_page
            downloads.update_progress("Проверка интерфейса", 42 * 1024 * 1024, 100 * 1024 * 1024, "Скачивание файлов")
            QTest.qWait(150)
            assert downloads.percent.text() == "42%"
            host.grab().save(str(Path(captures) / "downloads-progress-fixture.png"))
            downloads.show_failure("network unavailable")
            QTest.qWait(150)
            assert downloads.states.currentWidget() is downloads.failure
            host.grab().save(str(Path(captures) / "downloads-error-fixture.png"))
            downloads.update_progress("", 0, 0)
        js(app, host.page, "window.NexusUI.navigate('home')")
        QTest.qWait(200)
        assert not host._library_active
        for width, height in ((1280, 720), (1366, 768), (1920, 1080), (2560, 1440)):
            host.resize(width, height)
            QTest.qWait(200)
            dimensions = json.loads(js(app, host.page, "JSON.stringify({width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,hero:document.querySelector('.hero').getBoundingClientRect().width})"))
            assert not dimensions["overflow"]
            assert dimensions["hero"] > 600
            if captures:
                host.grab().save(str(Path(captures) / f"home-{width}.png"))
        host._action("open-build", instance.id)
        QTest.qWait(300)
        page = services.instances_page
        assert page.current.id == instance.id
        assert page.library_stack.currentWidget() is page.detail_surface
        if captures:
            host.resize(1366, 768)
            QTest.qWait(200)
            host.grab().save(str(Path(captures) / "build-detail-1366.png"))
            for index in range(page.detail.count()):
                page.detail.setCurrentIndex(index)
                QTest.qWait(120)
                host.grab().save(str(Path(captures) / f"build-section-{index}-1366.png"))
            page.detail.setCurrentIndex(0)
            page.detail_scroll.verticalScrollBar().setValue(0)
        launches = []
        monkeypatch.setattr(page, "_launch", lambda: launches.append(page.current.id))
        host._action("play-build", instance.id)
        assert launches == [instance.id]
        host._action("open-build", "missing")
        assert page.current.id == instance.id
        js(app, host.page, "document.querySelector('.navigation-toggle').click()")
        QTest.qWait(300)
        assert 65 <= host.library_overlay.x() <= 75
        host._action("fullscreen", "")
        QTest.qWait(100)
        assert host.isFullScreen()
        host.showNormal()
        assert not host.page.script_errors
    finally:
        host.close()


def test_ui2_mod_catalog_states_project_page_and_popup(candidate, monkeypatch):  # noqa: F811
    from PySide6.QtCore import Qt
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, _ = candidate
    instance = services.instance_service.create("Проверка каталога", "1.21.1", "fabric")
    catalog = services.instances_page.mod_catalog
    hits = [{"project_id": "fixture-project", "title": "Тестовый проект", "description": "Данные только для проверки интерфейса", "author": "Тестовый автор", "downloads": 42}]
    monkeypatch.setattr(catalog.provider, "search_page", lambda *args, **kwargs: {"hits": hits, "total_hits": 1})
    monkeypatch.setattr(catalog.provider, "project", lambda *args, **kwargs: {"title": "Тестовый проект", "description": "Описание для проверки форматирования, не реальные данные каталога.", "body": "<center><h1>Заголовок</h1></center>\n\n<p>Описание <strong>мода</strong>. Сохраняются абзацы, заголовки и списки.</p><h2>Возможности</h2><ul><li>Первый пункт</li><li>Второй пункт</li></ul>\n\n## Совместимость\n\nПроверь версию Minecraft и загрузчик перед установкой.\n\n<script>не исполняется</script>", "game_versions": ["1.21.1"], "loaders": ["fabric"], "license": {"name": "MIT"}})
    monkeypatch.setattr(catalog.provider, "versions", lambda *args, **kwargs: [{"name": "Проверочная версия", "version_number": "fixture", "date_published": "2026-10-08", "loaders": ["fabric"], "game_versions": ["1.21.1"], "changelog": "## Изменения\n\n**Проверка** оформления журнала изменений."}])
    host = DesignHost(services)
    host.resize(1366, 768)
    host.show()
    try:
        wait(app, lambda: bool(js(app, host.page, "!!window.NexusUI")))
        host._action("open-build", instance.id)
        services.instances_page.open_mod_catalog()
        wait(app, lambda: catalog.results.count() == 1)
        wait(app, lambda: host.library_overlay.isVisible())
        QTest.qWait(300)
        captures = os.environ.get("NEXUS_UI2_CAPTURE_DIR")
        if captures:
            host.grab().save(str(Path(captures) / "mod-results-fixture.png"))
        host.raise_()
        host.activateWindow()
        catalog.sort.setFocus(Qt.TabFocusReason)
        QTest.qWait(100)
        catalog.sort.showPopup()
        app.processEvents()
        assert catalog.sort.view().isVisible()
        catalog.sort.hidePopup()
        catalog._open_project(catalog.results.item(0))
        wait(app, lambda: "Описание" in catalog.detail.toPlainText())
        assert catalog.profile_page.isVisible()
        assert "<script>" not in catalog.detail.toPlainText()
        assert "не исполняется" not in catalog.detail.toPlainText()
        if captures:
            host.grab().save(str(Path(captures) / "mod-project-fixture.png"))
            for tab in range(1, catalog.project_tabs.count()):
                catalog.project_tabs.setCurrentIndex(tab)
                QTest.qWait(80)
                host.grab().save(str(Path(captures) / f"mod-project-tab-{tab}.png"))
        catalog._close_project()
        catalog._received(catalog.generation, {}, "network unavailable")
        assert catalog.catalog_state.isVisible()
        assert "недоступен" in catalog.catalog_state.title.text()
        if captures:
            host.grab().save(str(Path(captures) / "mod-error-fixture.png"))
        catalog._received(catalog.generation, {"hits": []}, "")
        assert not catalog.results.isVisible()
        assert "не найдено" in catalog.catalog_state.title.text()
        services.game_process = type("RunningProcess", (), {"poll": lambda self: None})()
        stopped = []
        monkeypatch.setattr(services, "_stop_game", lambda: stopped.append(True))
        host._sync_state(True)
        assert js(app, host.page, "!document.querySelector('#game-stop').hidden")
        host._action("stop-game", "")
        assert stopped == [True]
        services.game_process = None
        assert not host.page.script_errors
    finally:
        services.game_process = None
        host.close()


def test_ui2_action_policy_rejects_paths_duplicate_ids_and_foreign_origins(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, _ = candidate
    host = DesignHost(services)
    observed = []
    host.page.ui_action.connect(lambda *value: observed.append(value))
    try:
        wait(app, lambda: host.page.url().toString().startswith(host.server.origin))
        wait(app, lambda: bool(js(app, host.page, "!!window.NexusUI")))
        for value in ("/ui-action/create?id=../../data", "/ui-action/open-build?id=x&id=y",
                      "/ui-action/create?path=C:/", "/ui-action/not-a-command", "/ui-action/create#x"):
            assert not host.page.acceptNavigationRequest(QUrl(host.server.origin + value), QWebEnginePage.NavigationTypeLinkClicked, True)
        assert not host.page.acceptNavigationRequest(QUrl("https://example.com/ui-action/create"), QWebEnginePage.NavigationTypeLinkClicked, True)
        assert observed == []
        host.page.acceptNavigationRequest(QUrl(host.server.origin + "/ui-action/open-build?id=owned-id"), QWebEnginePage.NavigationTypeLinkClicked, True)
        assert observed == [("open-build", "owned-id")]
    finally:
        host.close()


def test_ui2_create_persists_content_rows_keep_authority_and_sensitive_data_stays_native(candidate, monkeypatch):  # noqa: F811
    import hashlib
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.instance_ui import CreateInstanceDialog
    from nexus_launcher.nexus_account import NexusProfile
    from nexus_launcher.nexus_platform.design_bridge import DesignHost, world_display
    from nexus_launcher.user_instances import InstalledMod
    from nexus_launcher.updater import InstallState

    app, services, _ = candidate
    host = DesignHost(services)
    host.show()
    try:
        wait(app, lambda: host.page.url().toString().startswith(host.server.origin))
        wait(app, lambda: bool(js(app, host.page, "!!window.NexusUI")))

        def fill():
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, CreateInstanceDialog)
            dialog.name.setText("Создано через NEXUS 2.0")
            captures = os.environ.get("NEXUS_UI2_CAPTURE_DIR")
            if captures:
                dialog.grab().save(str(Path(captures) / "create-dialog.png"))
            dialog.accept()
        QTimer.singleShot(100, fill)
        host._action("create", "")
        instances = services.instance_service.list()
        assert len(instances) == 1
        instance = instances[0]
        assert instance.name == "Создано через NEXUS 2.0"
        instance.loader = "fabric"
        jar = services.instance_service.path_for(instance.id) / "mods" / "local.jar"
        jar.write_bytes(b"local test fixture")
        instance.installed_mods = [InstalledMod("", "", "Локальный мод", jar.name,
                                                hashlib.sha512(jar.read_bytes()).hexdigest())]
        services.instance_service.save(instance)
        host._action("open-build", instance.id)
        page = services.instances_page
        page.mods.setCurrentRow(0)
        assert page.mods.currentItem().data(Qt.UserRole) == "local.jar"
        page._toggle_mod()
        assert not services.instance_service.load(instance.id).installed_mods[0].enabled
        assert not jar.exists()
        assert (jar.parent.parent / "disabled_mods" / "local.jar").exists()
        root = services.instance_service.path_for(instance.id)
        (root / "saves" / "Мой сохранённый мир").mkdir(parents=True)
        (root / "resourcepacks" / "local.zip").write_bytes(b"presentation fixture")
        page.refresh(instance.id)
        world_list = page.content_lists["saves"][0]
        assert world_list.count() == 1
        assert world_list.itemWidget(world_list.item(0)) is not None
        assert page.content_lists["resourcepacks"][0].count() == 1
        captures = os.environ.get("NEXUS_UI2_CAPTURE_DIR")
        if captures:
            page.detail.setCurrentIndex(3)
            QTest.qWait(150)
            host.grab().save(str(Path(captures) / "local-world-fixture.png"))
            page.detail.setCurrentIndex(0)
        services.account_profile = NexusProfile("<Игрок>", "private@example.test")
        host._sync_state(True)
        js(app, host.page, "window.NexusUI.navigate('profile')")
        assert js(app, host.page, "document.body.innerText.includes('<Игрок>')")
        assert not js(app, host.page, "document.documentElement.innerHTML.includes('private@example.test')")
        world = services.world_views[0]
        services._install_states[world.id] = InstallState.DOWNLOADING
        assert world_display(world, services)["delivery"].lower() == "downloading"
        services._current_page = "studio"
        monkeypatch.setattr(services.studio_page, "may_leave", lambda: False)
        host._action("leave", "")
        assert services._current_page == "studio"
        assert not host.close()
        assert host.state_timer.isActive()
        monkeypatch.setattr(services.studio_page, "may_leave", lambda: True)
        services._current_page = "home"
        assert not host.page.script_errors
    finally:
        host.close()


def test_ui2_state_matrix_search_recovery_focus_and_reduced_motion(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, _ = candidate
    host = DesignHost(services)
    host.resize(1280, 720)
    host.show()
    try:
        wait(app, lambda: host.page.url().toString().startswith(host.server.origin))
        wait(app, lambda: bool(js(app, host.page, "!!window.NexusUI")))
        QTest.qWait(200)
        host._sync_state(True)
        js(app, host.page, "window.NexusUI.navigate('catalog')")
        js(app, host.page, "(()=>{const q=document.querySelector('#world-search');q.value='нет-такого-мира';q.dispatchEvent(new Event('input',{bubbles:true}));})()")
        assert js(app, host.page, "document.body.innerText.includes('Ничего не найдено')")
        js(app, host.page, "document.querySelector('#clear-search').click()")
        assert js(app, host.page, "document.activeElement.id==='world-search'")
        assert js(app, host.page, "document.querySelectorAll('.world-card').length") == len(services.world_views)
        assert js(app, host.page, "document.querySelectorAll('.sidebar [aria-current=page]').length") == 1
        host._library_error = "Проверьте доступ к папке данных."
        host._sync_state(True)
        js(app, host.page, "window.NexusUI.navigate('home')")
        assert js(app, host.page, "document.body.innerText.includes('Библиотека недоступна')")
        services.config["reducedMotion"] = True
        host._sync_state(True)
        assert js(app, host.page, "document.querySelector('.app').classList.contains('profile-low-motion')")
        assert not host.page.script_errors
    finally:
        host.close()

def test_native_maximize_matches_renderer(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, _ = candidate
    host = DesignHost(services)
    services.hide()
    host.setGeometry(100, 80, 1200, 720)
    host.show()
    try:
        wait(app, lambda: bool(js(app, host.page, "document.querySelector('.hero') !== null")))
        for _ in range(5):
            host.title_bar.maximize.click()
            QTest.qWait(1500)
            area = host.screen().availableGeometry()
            assert host.isMaximized() and not host.isFullScreen()
            assert abs(host.width() - area.width()) <= 2
            assert abs(host.height() - area.height()) <= 2
            assert host.centralWidget().width() == host.width()
            assert host.view.width() == host.width()
            viewport = json.loads(js(app, host.page, "JSON.stringify([innerWidth,innerHeight])"))
            assert viewport == [host.view.width(), host.view.height()]
            host.title_bar.maximize.click()
            QTest.qWait(1500)
            assert not host.isMaximized()
            assert host.size().width() == 1200
            assert host.view.width() == host.width()
    finally:
        host.close()


