"""Queued editor messages must not emit signals on a deleted native page."""
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from shiboken6 import delete

from nexus_launcher.nexus_platform.learning.studio import LearningPage


def test_editor_console_message_after_native_page_deletion_is_ignored():
    app = QApplication.instance() or QApplication([])
    page = LearningPage(QWebEngineProfile.defaultProfile(), 'http://127.0.0.1:12345', None)
    events = []
    page.editor_event.connect(events.append)
    delete(page)
    LearningPage.javaScriptConsoleMessage(
        page, QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel,
        'NEXUS_CREATOR_EVENT:{"type":"document.changed"}', 1, 'http://127.0.0.1:12345/')
    assert events == []
    assert app is not None
