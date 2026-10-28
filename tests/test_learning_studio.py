"""Real reused Studio canvas integration, event detection and restart storage."""
import time
from PySide6.QtWidgets import QApplication
from nexus_launcher.nexus_platform.learning.studio import CreatorWorkspace


def wait(app, predicate, timeout=20):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    assert predicate()


def js(app, page, expression):
    values=[]
    page.runJavaScript(expression, lambda value: values.append(value))
    wait(app, lambda: bool(values))
    return values[0]


def test_real_canvas_actions_validation_highlight_resume_and_separate_storage(tmp_path):
    app=QApplication.instance() or QApplication([])
    workspace=CreatorWorkspace(tmp_path)
    workspace.resize(1280,800)
    workspace.show()
    try:
        wait(app, lambda: workspace.ready)
        assert not workspace.page.script_errors
        workspace.engine.settings(onboarding_seen=True)
        js(app,workspace.page,'window.NexusCreator.closeWelcome()')
        workspace.start_lesson('first-page')
        wait(app, lambda: workspace.engine.lesson is not None)
        assert workspace.engine.step.id == 'first.intro'
        workspace.engine.next()
        wait(app, lambda: js(app,workspace.page, "!!document.querySelector('#create-item.academy-highlight')"))
        assert not workspace.engine.next()
        js(app,workspace.page,"document.querySelector('#create-item').click()")
        wait(app, lambda: workspace.engine.validated)
        assert workspace.adapter.snapshot()['components'][-1]['type']=='text'
        workspace.engine.next()
        js(app,workspace.page,"updateItem({y:2})")
        wait(app, lambda: workspace.engine._record().get('failed_attempts',0)>0)
        assert not workspace.engine.validated
        js(app,workspace.page,"updateItem({x:20})")
        wait(app, lambda: workspace.engine.validated)
        workspace.engine.next()
        js(app,workspace.page,"updateItem({w:30})")
        wait(app, lambda: workspace.engine.validated)
        step=workspace.engine.step.id
        workspace.engine.exit()
        assert workspace.progress.path.is_file()
        assert workspace.document_path.is_file()
        assert workspace.progress.path!=workspace.document_path
        assert not workspace.page.script_errors
    finally:
        workspace.shutdown()
        workspace.close()
    second=CreatorWorkspace(tmp_path)
    second.resize(1280,800)
    second.show()
    try:
        wait(app,lambda: second.ready and second.engine.lesson is not None)
        assert second.engine.step.id==step
        assert second.engine.validated
        assert second.adapter.snapshot()['components'][-1]['x']==20
        second.engine.restore()
        second.engine.next()
        js(app,second.page,"updateItem({text:'NEXUS PAGE'})")
        wait(app,lambda: second.engine.validated)
        second.engine.next()
        js(app,second.page,"studio.querySelector('[data-category=layers]').click();[...properties.querySelectorAll('button')].find(x=>x.textContent==='Ниже').click()")
        wait(app,lambda: second.engine.validated)
        second.engine.next()
        js(app,second.page,"studio.querySelector('#studio-save').click()")
        wait(app,lambda: second.engine.validated)
        second.engine.next()
        assert second.engine._record()['completed']
        assert not second.page.script_errors
    finally:
        second.shutdown()
        second.close()


from tests.test_next_shell import candidate  # noqa: E402, F401


def test_academy_route_keeps_studio_authority_and_native_owner(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, root=candidate
    host=DesignHost(services)
    host.show()
    try:
        host._action('academy','')
        workspace=services.studio_page.creator_workspace
        assert workspace is not None
        assert services.studio_page.stack.currentWidget() is workspace
        assert not services.studio_page.service.capabilities.can_publish
        wait(app,lambda: workspace.ready)
        assert not workspace.page.script_errors
        assert services._current_page=='studio'
        workspace.start_lesson('first-page')
        wait(app,lambda: workspace.engine.lesson is not None)
        workspace.engine.exit()
        assert workspace.progress.data['current']=='first-page'
    finally:
        host.close()
