"""Actual editor layout/viewport controls; isolated practice documents only."""
import json
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from nexus_launcher.nexus_platform.learning.studio import CreatorWorkspace
from tests.test_learning_studio import js, wait


def test_preview_has_own_canvas_not_a_collapsed_dialog(tmp_path):
    app=QApplication.instance() or QApplication([])
    workspace=CreatorWorkspace(tmp_path);workspace.resize(1280,800);workspace.show()
    try:
        wait(app,lambda:workspace.ready)
        js(app,workspace.page,"NexusCreator.closeWelcome();document.querySelector('#studio-cancel').click()")
        for width,height in ((1280,800),(1000,740),(720,640)):
            workspace.resize(width,height);QTest.qWait(60)
            assert js(app,workspace.page,"(()=>{const r=document.querySelector('.academy-preview-scene').getBoundingClientRect();return r.width>500&&r.height>300&&Math.abs(r.width/r.height-10/7)<.02&&r.right<=innerWidth})()")
        assert js(app,workspace.page,"document.querySelector('.academy-page-preview>header button').textContent")=='Вернуться в редактор'
        assert js(app,workspace.page,"document.querySelectorAll('.academy-preview-scene button').length")==0
        js(app,workspace.page,"document.querySelector('.academy-page-preview>header button').click()")
        assert js(app,workspace.page,"document.querySelector('.academy-help').hidden")
        assert not workspace.page.script_errors
    finally:
        workspace.shutdown();workspace.close()


def test_zoom_dock_focus_and_compact_layout_preserve_document(tmp_path):
    app = QApplication.instance() or QApplication([])
    workspace = CreatorWorkspace(tmp_path)
    workspace.resize(1440, 900)
    workspace.show()
    try:
        wait(app, lambda: workspace.ready)
        workspace.engine.settings(onboarding_seen=True)
        js(app, workspace.page, 'NexusCreator.closeWelcome()')
        wait(app, lambda: bool(workspace.adapter.snapshot()['components']))
        js(app, workspace.page, "document.querySelector('#create-item').click();updateItem({text:'Тест',w:40,h:20,scaleX:1,scaleY:1})")
        wait(app, lambda: len(workspace.adapter.snapshot()['components']) == 2)
        before = json.loads(json.dumps(workspace.adapter.snapshot()))
        js(app, workspace.page, 'NexusStudioUI.setZoom(1)')
        width = js(app, workspace.page, 'board.getBoundingClientRect().width')
        QTest.qWait(50)
        overflow = js(app, workspace.page, "board.querySelector('[data-item=\"'+selectedID+'\"]').dataset.overflow")
        js(app, workspace.page, 'NexusStudioUI.setZoom(.5)')
        smaller = js(app, workspace.page, 'board.getBoundingClientRect().width')
        QTest.qWait(50)
        assert js(app, workspace.page, "board.querySelector('[data-item=\"'+selectedID+'\"]').dataset.overflow") == overflow
        assert .48 < smaller/width < .52
        assert js(app, workspace.page, "document.querySelector('.creator-zoom-value').textContent") == '50%'
        assert workspace.adapter.snapshot() == before
        dock_width = js(app, workspace.page, "document.querySelector('.creator-dock').getBoundingClientRect().width")
        js(app, workspace.page, "document.querySelector('.creator-dock-grip').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))")
        # Responsive breakpoints can start at 270 rather than 310 pixels.
        expected_width = min(430, round(dock_width) + 10)
        assert js(app, workspace.page, "document.querySelector('.creator-dock-grip').getAttribute('aria-valuenow')") == str(expected_width)
        assert js(app, workspace.page, "document.querySelector('.creator-dock').getBoundingClientRect().width") == expected_width
        js(app, workspace.page, "[...document.querySelectorAll('.creator-zoom-tools button')].find(b=>b.textContent==='Только холст').click()")
        assert js(app, workspace.page, "getComputedStyle(document.querySelector('.creator-dock')).display") == 'none'
        js(app, workspace.page, "[...document.querySelectorAll('.creator-zoom-tools button')].find(b=>b.textContent==='Сброс').click()")
        assert js(app, workspace.page, "getComputedStyle(document.querySelector('.creator-dock')).display") != 'none'
        for width, height in ((1440,900),(1000,740),(720,640)):
            workspace.resize(width,height)
            # Chromium applies the native resize asynchronously on loaded runners.
            wait(app, lambda: json.loads(js(app, workspace.page, 'JSON.stringify([innerWidth,innerHeight])'))
                 == [workspace.view.width(), workspace.view.height()])
            js(app, workspace.page, 'NexusStudioUI.fitCanvas()')
            geometry = json.loads(js(app, workspace.page, "JSON.stringify({overflow:document.documentElement.scrollWidth>innerWidth,toolbar:document.querySelector('.canvas-toolbar').getBoundingClientRect().height,status:document.querySelector('.creator-statusbar').getBoundingClientRect().bottom,dock:document.querySelector('.creator-dock').getBoundingClientRect().right})"))
            assert not geometry['overflow']
            assert geometry['toolbar'] <= 48
            assert geometry['status'] <= height + 1
            assert geometry['dock'] <= width + 1
        after = workspace.adapter.snapshot()
        changes = [{key: (old.get(key), new.get(key)) for key in old.keys() | new.keys() if old.get(key) != new.get(key)} for old, new in zip(before['components'], after['components'])]
        assert after == before, changes
        assert not workspace.page.script_errors
    finally:
        workspace.shutdown()
        workspace.close()


def test_real_pointer_drag_at_half_zoom_uses_document_coordinates(tmp_path):
    app = QApplication.instance() or QApplication([])
    workspace = CreatorWorkspace(tmp_path)
    workspace.resize(1280, 800)
    workspace.show()
    try:
        wait(app, lambda: workspace.ready)
        workspace.engine.settings(onboarding_seen=True)
        js(app, workspace.page, 'NexusCreator.closeWelcome()')
        js(app, workspace.page, "document.querySelector('#create-item').click();updateItem({text:'Drag',x:20,y:20,w:30,h:20,locked:false,group:''});NexusStudioUI.setZoom(.5)")
        wait(app, lambda: len(workspace.adapter.snapshot()['components']) == 2)
        QTest.qWait(100)
        coordinates = json.loads(js(app, workspace.page, "JSON.stringify((()=>{const r=board.querySelector('[data-item=\"'+selectedID+'\"]').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})())"))
        start = QPoint(round(coordinates['x']), round(coordinates['y']))
        workspace.view.setFocus()
        target = workspace.view.focusProxy()
        assert target is not None
        QTest.mousePress(target, Qt.LeftButton, pos=start)
        QTest.qWait(40)
        QTest.mouseMove(target, start+QPoint(25,18), delay=30)
        QTest.mouseMove(target, start+QPoint(50,35), delay=30)
        QTest.mouseRelease(target, Qt.LeftButton, pos=start+QPoint(50,35))
        wait(app, lambda: workspace.adapter.snapshot()['components'][-1]['x'] != 20)
        item = workspace.adapter.snapshot()['components'][-1]
        assert abs(item['x']-30) <= 1 and abs(item['y']-30) <= 1
        assert item['w'] == 30 and item['h'] == 20
        assert not workspace.page.script_errors
    finally:
        workspace.shutdown()
        workspace.close()
