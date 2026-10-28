"""Explicit, event-driven runner independent of Qt and any particular editor."""
from copy import deepcopy
from .schema import RunState, StepType
from .validation import ValidationEngine


class LearningEngine:
    def __init__(self, registry, progress, adapter, validators=None):
        self.registry, self.progress, self.adapter = registry, progress, adapter
        self.validators = validators or ValidationEngine()
        self.state = RunState.IDLE
        self.lesson = None
        self.step_index = 0
        self.validated = False
        self.hint_index = 0
        self.message = ''
        self.baseline = {}
        self.listeners = []

    @property
    def step(self):
        return self.lesson.steps[self.step_index] if self.lesson else None

    def _record(self):
        assert self.lesson is not None
        return self.progress.data['lessons'].setdefault(self.lesson.id, {})

    def _notify(self):
        for listener in tuple(self.listeners):
            listener(self)

    def persist(self):
        if self.lesson:
            assert self.step is not None
            self._record().update(version=self.lesson.version, step_id=self.step.id,
                                  step_index=self.step_index, validated=self.validated,
                                  hint_index=self.hint_index, baseline=self.baseline, state=self.state.value)
        self.progress.save()
        self._notify()

    def start(self, lesson_id, restart=False):
        self.lesson = self.registry.get(lesson_id)
        record = self.progress.data['lessons'].get(lesson_id, {}) if not restart else {}
        old_id = record.get('step_id')
        self.step_index = next((i for i, step in enumerate(self.lesson.steps) if step.id == old_id), 0)
        same_version = record.get('version') == self.lesson.version
        self.baseline = deepcopy(record.get('baseline', self.adapter.snapshot())) if same_version else deepcopy(self.adapter.snapshot())
        self.validated = bool(record.get('validated', False)) if same_version else False
        self.hint_index = record.get('hint_index', 0) if same_version else 0
        if restart:
            self.progress.data['lessons'][lesson_id] = {}
        self.progress.data['current'] = lesson_id
        self._enter()

    def resume(self):
        current = self.progress.data['current']
        if current in self.registry.lessons:
            self.start(current)

    def _enter(self):
        assert self.step is not None
        self.message = ''
        passive = self.step.type in (StepType.INTRO, StepType.EXPLANATION, StepType.OBSERVE)
        if passive:
            self.validated = True
        self.state = RunState.INTRO if passive else RunState.ACTIVE if self.validated else RunState.WAITING_FOR_ACTION
        self.persist()

    def observe(self, event):
        if not self.step or self.validated or self.state not in (RunState.WAITING_FOR_ACTION, RunState.SHOWING_HINT, RunState.MINIMIZED):
            return
        # Only relevant events validate. No document scans or work on animation frames.
        expected = self.step.validation.get('event')
        if expected and expected != event.get('type'):
            return
        minimized = self.state == RunState.MINIMIZED
        self.state = RunState.VALIDATING
        result = self.validators.validate(self.step.validation, event, self.adapter.snapshot(), self.baseline)
        self.validated = result.success
        self.message = self.step.completion_message if result.success else result.message or 'feedback.almost'
        record = self._record()
        if not result.success:
            record['failed_attempts'] = record.get('failed_attempts', 0) + 1
        self.state = RunState.MINIMIZED if minimized else RunState.ACTIVE if result.success else RunState.WAITING_FOR_ACTION
        self.persist()

    def next(self, skip=False):
        if not self.step or self.state in (RunState.PAUSED, RunState.MINIMIZED, RunState.EXITING, RunState.COMPLETED):
            return False
        if skip and not self.step.allow_skip:
            return False
        if not self.validated and not skip:
            return False
        assert self.lesson is not None
        record = self._record()
        if skip:
            skipped = record.setdefault('skipped_steps', [])
            if self.step.id not in skipped:
                skipped.append(self.step.id)
        if self.step_index + 1 == len(self.lesson.steps):
            # A skipped practical step cannot earn lesson completion or rewards.
            record['completed'] = not record.get('skipped_steps')
            record['finished'] = True
            self.state = RunState.COMPLETED
            self.progress.data['current'] = None
            if record['completed']:
                for reward in self.lesson.rewards:
                    if reward not in self.progress.data['achievements']:
                        self.progress.data['achievements'].append(reward)
            self.persist()
            return True
        self.step_index += 1
        self.validated = False
        self.hint_index = 0
        self.baseline = deepcopy(self.adapter.snapshot())
        self._enter()
        return True

    def back(self):
        if self.step_index:
            self.step_index -= 1
            self.validated = False
            self.hint_index = 0
            self.baseline = deepcopy(self.adapter.snapshot())
            self._enter()

    def hint(self):
        if not self.step or not self.progress.data['settings']['hints']:
            return ''
        if not self.step.hints:
            return ''
        self.hint_index = min(self.hint_index + 1, len(self.step.hints))
        self._record()['hints_used'] = self._record().get('hints_used', 0) + 1
        self.state = RunState.SHOWING_HINT if not self.validated else RunState.ACTIVE
        self.persist()
        return self.step.hints[self.hint_index - 1]

    def suspend(self, state=RunState.PAUSED):
        if self.lesson and self.state != RunState.COMPLETED:
            self.state = state
            self.persist()

    def restore(self):
        if self.lesson:
            self._enter()

    def exit(self):
        if self.state == RunState.COMPLETED:
            self.state = RunState.IDLE
            self.persist()
        else:
            self.suspend(RunState.PAUSED)

    def settings(self, **values):
        allowed = set(self.progress.data['settings'])
        if not set(values).issubset(allowed):
            raise ValueError('Unknown learning preference')
        self.progress.data['settings'].update(values)
        if values.get('mode') == 'advanced':
            self.progress.data['settings'].update(auto_start=False, tips=False)
        self.progress.save()
        self._notify()
