"""Real pointer editing and deliberate accent markers in the Studio web surface."""

import json

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from nexus_launcher.nexus_platform.learning.studio import CreatorWorkspace
from tests.test_learning_studio import js, wait
from tests.test_next_shell import candidate  # noqa: F401


def test_pointer_drag_resize_and_selection_markers(tmp_path):
    app = QApplication.instance() or QApplication([])
    workspace = CreatorWorkspace(tmp_path)
    workspace.resize(1280, 800)
    workspace.show()
    try:
        wait(app, lambda: workspace.ready)
        workspace.engine.settings(onboarding_seen=True)
        js(
            app,
            workspace.page,
            "NexusCreator.closeWelcome();document.querySelector('#create-item').click()",
        )
        wait(app, lambda: len(workspace.adapter.snapshot()["components"]) == 2)

        def selected():
            document = workspace.adapter.snapshot()
            return next(
                x for x in document["components"] if x["id"] == document["selected"]
            )

        def point(selector):
            raw = js(
                app,
                workspace.page,
                "JSON.stringify((()=>{const r=document.querySelector("
                + json.dumps(selector)
                + ").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())",
            )
            value = json.loads(raw)
            return QPoint(round(value["x"]), round(value["y"]))

        QTest.qWait(100)
        initial_x = selected()["x"]
        origin = point(".canvas-node.selected")
        receiver = workspace.view.focusProxy() or workspace.view
        origin = receiver.mapFrom(workspace.view, origin)
        QTest.mousePress(receiver, Qt.LeftButton, pos=origin)
        QTest.qWait(50)
        QTest.mouseMove(receiver, origin + QPoint(60, 0), delay=30)
        QTest.mouseRelease(receiver, Qt.LeftButton, pos=origin + QPoint(60, 0))
        wait(app, lambda: selected()["x"] > initial_x)
        initial_width = selected()["w"]
        origin = point(".canvas-node.selected .resize-grip")
        origin = receiver.mapFrom(workspace.view, origin)
        QTest.mousePress(receiver, Qt.LeftButton, pos=origin)
        QTest.qWait(50)
        QTest.mouseMove(receiver, origin + QPoint(40, 20), delay=30)
        QTest.mouseRelease(receiver, Qt.LeftButton, pos=origin + QPoint(40, 20))
        wait(app, lambda: selected()["w"] > initial_width)
        assert js(
            app,
            workspace.page,
            "(()=>{const h=document.querySelector('.canvas-node.selected .resize-grip');const s=getComputedStyle(h);return s.backgroundColor!=='rgb(255, 255, 255)'&&s.borderRadius!=='50%'&&h.getClientRects().length>0})()",
        )
        js(app, workspace.page, "updateItem({locked:true})")
        assert not js(
            app,
            workspace.page,
            "!!document.querySelector('.canvas-node.selected .resize-grip')",
        )
        js(app, workspace.page, "selectedID='';multiSelection.clear();renderStudio()")
        assert not js(
            app,
            workspace.page,
            "[...document.querySelectorAll('.resize-grip')].some(x=>x.getClientRects().length)",
        )
        assert not workspace.page.script_errors
    finally:
        workspace.shutdown()
        workspace.close()


def test_host_window_controls_preserve_live_studio(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost

    app, services, _root = candidate
    host = DesignHost(services)
    host.show()
    try:
        host._action("academy", "")
        workspace = services.studio_page.creator_workspace
        wait(app, lambda: workspace.ready)
        workspace.engine.settings(onboarding_seen=True)
        js(
            app,
            workspace.page,
            "NexusCreator.closeWelcome();document.querySelector('#create-item').click()",
        )
        wait(app, lambda: len(workspace.adapter.snapshot()["components"]) == 2)
        before = workspace.adapter.snapshot()
        QTest.mouseClick(host.title_bar.minimize, Qt.LeftButton)
        app.processEvents()
        assert host.isMinimized()
        host.showNormal()
        app.processEvents()
        host.title_bar.maximize.setFocus(Qt.TabFocusReason)
        QTest.keyClick(host.title_bar.maximize, Qt.Key_Return)
        app.processEvents()
        assert host.isMaximized()
        QTest.keyClick(host.title_bar.maximize, Qt.Key_Space)
        QTest.qWait(100)
        assert not host.isMaximized()
        assert workspace.adapter.snapshot() == before
        assert not workspace.page.script_errors
        assert workspace.document_path.is_file()
    finally:
        host.close()
