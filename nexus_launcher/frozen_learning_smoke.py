"""Bounded asynchronous portable acceptance for the actual Studio adapter."""
import json
from PySide6.QtCore import QTimer
from nexus_launcher.nexus_platform.learning.progress import ProgressManager
from nexus_launcher.nexus_platform.learning.schema import RunState


def start_learning(window, output, app):
    window._action('academy', '')
    workspace = window.services.studio_page.creator_workspace
    stage = [0]
    timer = QTimer(window)
    timer.setInterval(50)
    attempts = [0]

    def finish(report):
        timer.stop()
        def capture():
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            window.grab().save(str(output.with_suffix('.png')))
            window.close()
            app.quit()
        # Let Chromium present the frame before taking visual evidence.
        QTimer.singleShot(900, capture)

    def tick():
        attempts[0] += 1
        if attempts[0] > 400:
            finish({'error': 'Academy smoke timed out', 'scriptErrors': workspace.page.script_errors})
            return
        if stage[0] == 0 and workspace.ready:
            workspace.engine.settings(onboarding_seen=True)
            workspace.page.runJavaScript('window.NexusCreator.closeWelcome()')
            workspace.start_lesson('first-page', restart=True)
            stage[0] = 1
        elif stage[0] == 1 and workspace.engine.lesson:
            workspace.engine.next()
            workspace.page.runJavaScript("studio.querySelector('#create-item').click()")
            stage[0] = 2
        elif stage[0] == 2 and workspace.engine.validated:
            workspace.engine.suspend(RunState.MINIMIZED)
            minimized = workspace.engine.state == RunState.MINIMIZED
            workspace.engine.restore()
            restored = workspace.engine.validated
            workspace.engine.exit()
            persisted = ProgressManager(workspace.progress.path)
            report = {'ready': True, 'real_component_action': True, 'validated_step': workspace.engine.step.id,
                      'minimized': minimized, 'restored_validation': restored,
                      'progress_persisted': persisted.data['current'] == 'first-page',
                      'document_separate': workspace.document_path != workspace.progress.path and workspace.document_path.is_file(),
                      'publishing_authority': window.services.studio_page.service.capabilities.can_publish,
                      'scriptErrors': workspace.page.script_errors}
            finish(report)

    timer.timeout.connect(tick)
    timer.start()
