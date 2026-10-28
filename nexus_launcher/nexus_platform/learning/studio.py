"""Studio's first learning adapter: reused page builder, isolated practice files."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget, QVBoxLayout

from nexus_launcher.modern_main import resource
from nexus_launcher.nexus_platform.prototype_host import AssetServer, ResourcePolicy, same_origin
from .content import LearningContent
from .engine import LearningEngine
from .schema import RunState
from .progress import ProgressManager, write_json


class CanvasAdapter:
    def __init__(self):
        self.document = {'components': [], 'selected': ''}

    def snapshot(self):
        return self.document

    def resolve_target(self, target):
        # Declarative description resolved by the renderer, never screen coordinates.
        return {'type': target.type, 'id': target.id, 'property': target.property,
                'componentType': target.component_type}


class LearningPage(QWebEnginePage):
    editor_event = Signal(object)

    def __init__(self, profile, origin, parent):
        super().__init__(profile, parent)
        self.origin = origin
        self.script_errors = []

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.script_errors.append({'message': message, 'line': line_number})
        if message.startswith('NEXUS_CREATOR_EVENT:') and len(message) < 250000 and same_origin(source_id, self.origin):
            try:
                data = json.loads(message.removeprefix('NEXUS_CREATOR_EVENT:'))
                if isinstance(data, dict) and isinstance(data.get('type'), str):
                    self.editor_event.emit(data)
            except (ValueError, TypeError):
                pass

    def acceptNavigationRequest(self, url, _kind, is_main_frame):
        return is_main_frame and same_origin(url.toString(), self.origin) and url.path() == '/'

    def createWindow(self, _kind):
        return None


class CreatorWorkspace(QWidget):
    back_requested = Signal()

    def __init__(self, storage: Path, parent=None, reduced_motion=False):
        super().__init__(parent)
        from nexus_launcher.nexus_platform.presentation_style import stylesheet
        self.setObjectName("platformRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(stylesheet())
        self.storage = storage
        self.content = LearningContent(resource('academy'))
        self.adapter = CanvasAdapter()
        self.progress = ProgressManager(storage / 'progress.json')
        self.engine = LearningEngine(self.content.registry, self.progress, self.adapter)
        self.engine.settings(reduced_motion=bool(reduced_motion))
        self.engine.listeners.append(lambda _engine: self.refresh_learning())
        current = self.progress.data.get('current')
        self.document_id: str = current if isinstance(current, str) and current in self.content.registry.lessons else 'practice'
        self.pending_lesson = None
        self.ready = False
        self.show_academy_on_ready = False
        self.server = AssetServer(creator=True)
        self.profile = QWebEngineProfile(self)
        self.policy = ResourcePolicy(self.server.origin, self.profile)
        self.profile.setUrlRequestInterceptor(self.policy)
        self.profile.downloadRequested.connect(lambda item: item.cancel())
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.page = LearningPage(self.profile, self.server.origin, self.view)
        self.page.editor_event.connect(self._event)
        self.view.setPage(self.page)
        for flag in (QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                     QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                     QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows):
            self.page.settings().setAttribute(flag, False)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        self.page.loadFinished.connect(self._loaded)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.view, 1)
        self.view.load(QUrl(self.server.origin + '/'))

    def _back(self):
        self.engine.exit()
        self.back_requested.emit()

    def _call(self, method, value=None):
        argument = json.dumps(value, ensure_ascii=True, allow_nan=False)
        self.page.runJavaScript(f'window.NexusCreator?.{method}({argument})')

    @property
    def document_path(self):
        if self.document_id not in {*self.content.registry.lessons, 'practice', 'template'}:
            raise ValueError('Unknown practice document')
        return self.storage / 'practice-documents' / (self.document_id + '.json')

    def _loaded(self, ok):
        if not ok:
            return
        document = json.loads(self.document_path.read_text(encoding='utf-8')) if self.document_path.is_file() else None
        self._call('load', document)

    def _save_document(self):
        write_json(self.document_path, self.adapter.snapshot())

    def _event(self, event):
        kind = event['type']
        if kind == 'editor.back_requested':
            self._back()
            return
        if kind.startswith('learning.'):
            self._learning_action(kind.removeprefix('learning.'), event)
            return
        if 'snapshot' in event:
            document = event['snapshot']
            if not isinstance(document, dict) or not isinstance(document.get('components'), list) or len(document['components']) > 30:
                return
            self.adapter.document = document
        if kind == 'editor.ready':
            self.ready = True
            if self.pending_lesson:
                lesson, restart = self.pending_lesson
                self.pending_lesson = None
                self.engine.start(lesson, restart=restart)
            elif self.progress.data['current']:
                saved_state = self.progress.data['lessons'].get(self.progress.data['current'], {}).get('state')
                self.engine.resume()
                if saved_state in (RunState.PAUSED.value, RunState.MINIMIZED.value):
                    self.engine.suspend(RunState(saved_state))
            self.refresh_learning()
            if not self.progress.data['settings']['onboarding_seen']:
                self._call('onboarding')
            elif self.show_academy_on_ready:
                self.open_academy()
        elif kind == 'project.save_requested':
            self._save_document()
            self.engine.observe({'type': 'project.saved'})
            self._call('saved')
        elif kind != 'component.selected' and kind != 'canvas.selected':
            # Commit snapshots only, never on pointermove/animation frames.
            self._save_document()
            self.engine.observe(event)
        else:
            self.engine.observe(event)

    def start_lesson(self, lesson_id, restart=False):
        self.content.registry.get(lesson_id)  # Reject foreign IDs before any path access.
        self.document_id = lesson_id
        self.pending_lesson = (lesson_id, restart)
        document = None if restart or not self.document_path.is_file() else json.loads(self.document_path.read_text(encoding='utf-8'))
        self._call('load', document)

    def _learning_action(self, action, event):
        handlers = {'next': self.engine.next, 'skip': lambda: self.engine.next(skip=True),
                    'back': self.engine.back, 'hint': self.engine.hint, 'resume': self.engine.restore,
                    'pause': self.engine.exit, 'minimize': lambda: self.engine.suspend(RunState.MINIMIZED),
                    'exit-request': lambda: self.engine.suspend(RunState.EXITING), 'exit': self.engine.exit,
                    'academy': self.open_academy, 'help': lambda: self._call('help', self.t('help.canvas')),
                    'restart': lambda: self.start_lesson(self.engine.lesson.id, restart=True) if self.engine.lesson else None,
                    'reset': self.reset_progress, 'onboarding': lambda: self._call('onboarding')}
        if action in handlers:
            handlers[action]()
        elif action == 'start' and event.get('lesson') in self.content.registry.lessons:
            self.start_lesson(event['lesson'])
        elif action == 'preference' and event.get('name') in {'tips', 'hints', 'auto_start', 'show_completed'}:
            self.engine.settings(**{event['name']: bool(event.get('value'))})
        elif action == 'locale' and event.get('value') in {'ru', 'en', 'de', 'ky'}:
            self.engine.settings(locale=event['value'])
        elif action == 'mode' and event.get('value') in {'guided', 'assisted', 'advanced'}:
            self.engine.settings(mode=event['value'])
            if event['value'] == 'advanced':
                self.engine.exit()
        elif action == 'welcome-choice' and event.get('value') in {'guided', 'template', 'explore', 'advanced'}:
            value = event['value']
            self.engine.settings(onboarding_seen=True, mode='advanced' if value == 'advanced' else 'guided', auto_start=value == 'guided')
            self._call('closeWelcome')
            if value == 'guided':
                self.start_lesson('first-page')
            elif value == 'template':
                self.document_id = 'template'
                self._call('loadTemplate')

    def reset_progress(self):
        self.progress.reset()
        self.engine.state = RunState.IDLE
        self.engine.lesson = None
        self.refresh_learning()
        self.open_academy()

    def t(self, key):
        return self.content.text(key, self.progress.data['settings']['locale'])

    def refresh_learning(self):
        if not self.ready:
            return
        engine = self.engine
        payload = {'ui': {key.removeprefix('ui.'): self.t(key) for key in self.content.strings['en'] if key.startswith('ui.')},
                   'settings': self.progress.data['settings'], 'state': engine.state.value,
                   'message': self.t(engine.message) if engine.message else '',
                   'lessons': [{'id': lesson.id, 'title': self.t(lesson.title), 'description': self.t(lesson.description),
                                'completed': self.progress.data['lessons'].get(lesson.id, {}).get('completed', False)}
                               for lesson in self.content.registry.lessons.values()]}
        if engine.lesson and engine.step:
            payload.update(title=self.t(engine.step.title), instruction=self.t(engine.step.title if self.progress.data['settings']['mode'] == 'assisted' else engine.step.instruction),
                           index=engine.step_index + 1, count=len(engine.lesson.steps), validated=engine.validated,
                           allowSkip=engine.step.allow_skip, target=self.adapter.resolve_target(engine.step.target),
                           hint=self.t(engine.step.hints[engine.hint_index - 1]) if engine.hint_index and engine.step.hints else '',
                           completed=engine._record().get('completed', False))
        self._call('learning', payload)

    def open_academy(self):
        self.show_academy_on_ready = True
        if self.ready:
            self.refresh_learning()
            self._call('academy')

    def shutdown(self):
        self.engine.exit()
        self.server.close()
