import json
from dataclasses import replace
from pathlib import Path
import pytest
from nexus_launcher.nexus_platform.learning.schema import RunState, CourseRegistry, StepType
from nexus_launcher.nexus_platform.learning.content import LearningContent
from nexus_launcher.nexus_platform.learning.engine import LearningEngine
from nexus_launcher.nexus_platform.learning.progress import ProgressManager
from nexus_launcher.nexus_platform.learning.validation import ValidationEngine


class Adapter:
    def __init__(self):
        self.document = {'components': []}
    def snapshot(self):
        return self.document
    def resolve_target(self, target):
        return target.id or target.type


@pytest.fixture
def runner(tmp_path):
    content = LearningContent(Path('assets/academy'))
    return LearningEngine(content.registry, ProgressManager(tmp_path / 'learning.json'), Adapter())


def test_schema_loading_and_all_step_types(runner):
    assert len(runner.registry.lessons) == 7
    assert len(StepType) == 24
    assert runner.registry.get('first-page').steps[1].target.id == 'add-component'


def test_interactive_next_requires_real_action(runner):
    runner.start('components')
    assert not runner.next()
    runner.observe({'type': 'component.created', 'componentType': 'video'})
    assert not runner.validated
    assert runner._record()['failed_attempts'] == 1
    runner.observe({'type': 'component.created', 'componentType': 'text'})
    assert runner.validated
    assert runner.next()
    assert runner.state == RunState.COMPLETED
    assert runner._record()['completed']


def test_pause_minimize_exit_ignore_events_and_resume(runner):
    runner.start('components')
    for state in (RunState.PAUSED, RunState.EXITING):
        runner.suspend(state)
        runner.observe({'type': 'component.created', 'componentType': 'text'})
        assert not runner.validated
        runner.restore()
    runner.exit()
    second = LearningEngine(runner.registry, ProgressManager(runner.progress.path), runner.adapter)
    second.resume()
    assert second.lesson.id == 'components'
    assert second.step.id == 'components.add'
    assert second.state == RunState.WAITING_FOR_ACTION


def test_resume_keeps_baseline_and_validated_action(runner):
    runner.adapter.document = {'components': [{'id': 'title', 'x': 10}]}
    runner.start('move')
    runner.observe({'type': 'component.created'})
    runner.next()
    runner.adapter.document['components'][0]['x'] = 25
    runner.observe({'type': 'component.moved', 'componentId': 'title'})
    assert runner.validated
    second = LearningEngine(runner.registry, ProgressManager(runner.progress.path), runner.adapter)
    second.resume()
    assert second.validated
    assert second.baseline['components'][0]['x'] == 10


def test_skipped_steps_never_award_completion(runner):
    runner.start('components')
    assert runner.next(skip=True)
    assert runner._record()['finished']
    assert not runner._record()['completed']
    runner.start('components', restart=True)
    assert not runner._record().get('skipped_steps')


def test_hints_persist_and_can_be_disabled(runner):
    runner.start('components')
    assert runner.hint().endswith('hint0')
    assert runner.hint().endswith('hint1')
    assert runner.hint().endswith('hint1')
    assert runner._record()['hints_used'] == 3
    runner.settings(hints=False)
    assert runner.hint() == ''


def test_version_migration_preserves_step_identity_invalidates_validation(runner):
    runner.start('first-page')
    runner.next()
    runner.observe({'type': 'component.created', 'componentType': 'text'})
    lesson = runner.lesson
    updated = replace(lesson, version=2, steps=(lesson.steps[-1], *lesson.steps[:-1]))
    second = LearningEngine(CourseRegistry([updated]), ProgressManager(runner.progress.path), runner.adapter)
    second.resume()
    assert second.step.id == 'first.add'
    assert not second.validated


def test_unknown_lesson_on_resume_is_safe(runner):
    runner.progress.data['current'] = 'old.removed'
    runner.resume()
    assert runner.state == RunState.IDLE


def test_progress_is_independent_and_atomic(runner, tmp_path):
    project = tmp_path / 'project.json'
    project.write_text('{"title":"real project"}')
    runner.start('canvas')
    runner.hint()
    assert project.read_text() == '{"title":"real project"}'
    assert not list(tmp_path.glob('.learning-*'))
    assert json.loads(runner.progress.path.read_text())['current'] == 'canvas'


def test_future_or_corrupt_progress_is_not_overwritten(tmp_path):
    path = tmp_path / 'progress.json'
    for data in ('bad json', '{"schema":99,"lessons":{}}'):
        path.write_text(data)
        with pytest.raises(ValueError):
            ProgressManager(path)
        assert path.read_text() == data


@pytest.mark.parametrize('locale', ['ru', 'en', 'de', 'ky'])
def test_localization_keys_and_fallback(locale):
    content = LearningContent(Path('assets/academy'))
    for lesson in content.registry.lessons.values():
        assert content.text(lesson.title, locale) != lesson.title
        for step in lesson.steps:
            assert content.text(step.instruction, locale) != step.instruction


def test_property_tolerance_and_custom_validator():
    validators = ValidationEngine()
    rule = {'kind': 'property', 'event': 'component.resized', 'property': 'w', 'value': 48, 'tolerance': 2}
    snapshot = {'components': [{'id': 'a', 'w': 49}]}
    assert validators.validate(rule, {'type': 'component.resized', 'componentId': 'a'}, snapshot, {}).success
    snapshot['components'][0]['w'] = 60
    assert not validators.validate(rule, {'type': 'component.resized', 'componentId': 'a'}, snapshot, {}).success
    validators.register('custom', lambda *args: validators.action({'event': 'test'}, *args[1:]))
    assert validators.validate({'kind': 'custom'}, {'type': 'test'}, {}, {}).success


def test_expert_mode_and_reduced_motion_persist(runner):
    runner.settings(mode='advanced', reduced_motion=True)
    settings = ProgressManager(runner.progress.path).data['settings']
    assert not settings['tips'] and not settings['auto_start'] and settings['reduced_motion']



def test_minimized_tutorial_still_observes_real_actions(runner):
    runner.start('components')
    runner.suspend(RunState.MINIMIZED)
    runner.observe({'type': 'component.created', 'componentType': 'text'})
    assert runner.validated
    assert runner.state == RunState.MINIMIZED
    runner.restore()
    assert runner.validated
    assert runner.next()
