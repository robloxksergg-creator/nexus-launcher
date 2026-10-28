"""Declarative lessons: data only, never executable expressions or scripts."""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StepType(StrEnum):
    INTRO = 'INTRO'
    EXPLANATION = 'EXPLANATION'
    CLICK = 'CLICK'
    SELECT = 'SELECT'
    DRAG = 'DRAG'
    RESIZE = 'RESIZE'
    MOVE = 'MOVE'
    TYPE = 'TYPE'
    CHANGE_VALUE = 'CHANGE_VALUE'
    SELECT_OPTION = 'SELECT_OPTION'
    ADD_COMPONENT = 'ADD_COMPONENT'
    DELETE_COMPONENT = 'DELETE_COMPONENT'
    DUPLICATE = 'DUPLICATE'
    ALIGN = 'ALIGN'
    GROUP = 'GROUP'
    REORDER_LAYER = 'REORDER_LAYER'
    UPLOAD_ASSET = 'UPLOAD_ASSET'
    APPLY_STYLE = 'APPLY_STYLE'
    PREVIEW = 'PREVIEW'
    SAVE = 'SAVE'
    PUBLISH = 'PUBLISH'
    OBSERVE = 'OBSERVE'
    CHALLENGE = 'CHALLENGE'
    FREEFORM = 'FREEFORM'


class RunState(StrEnum):
    IDLE = 'IDLE'
    INTRO = 'INTRO'
    ACTIVE = 'ACTIVE'
    WAITING_FOR_ACTION = 'WAITING_FOR_ACTION'
    SHOWING_HINT = 'SHOWING_HINT'
    VALIDATING = 'VALIDATING'
    COMPLETED = 'COMPLETED'
    PAUSED = 'PAUSED'
    MINIMIZED = 'MINIMIZED'
    EXITING = 'EXITING'


@dataclass(frozen=True)
class Target:
    type: str
    id: str = ''
    property: str = ''
    component_type: str = ''


@dataclass(frozen=True)
class Step:
    id: str
    type: StepType
    title: str
    instruction: str
    target: Target
    validation: dict[str, Any] = field(default_factory=dict)
    hints: tuple[str, ...] = ()
    optional: bool = False
    allow_skip: bool = True
    completion_message: str = 'feedback.complete'
    description: str = ''


@dataclass(frozen=True)
class Lesson:
    id: str
    course_id: str
    title: str
    description: str
    steps: tuple[Step, ...]
    version: int = 1
    difficulty: str = 'beginner'
    estimated_minutes: int = 5
    prerequisites: tuple[str, ...] = ()
    objectives: tuple[str, ...] = ()
    rewards: tuple[str, ...] = ()
    documentation_link: str = 'help.canvas'
    completion_criteria: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_data(cls, data):
        steps = tuple(Step(id=s['id'], type=StepType(s['type']), title=s['title'],
                           instruction=s['instruction'], target=Target(**s.get('target', {'type': 'canvas'})),
                           validation=dict(s.get('validation', {})), hints=tuple(s.get('hints', [])),
                           optional=bool(s.get('optional', False)), allow_skip=bool(s.get('allow_skip', True)),
                           description=s.get('description', ''), completion_message=s.get('completion_message', 'feedback.complete'))
                      for s in data['steps'])
        if not steps or len({s.id for s in steps}) != len(steps):
            raise ValueError('Lesson needs unique steps')
        return cls(id=data['id'], course_id=data['course_id'], title=data['title'],
                   description=data['description'], steps=steps, version=int(data.get('version', 1)),
                   difficulty=data.get('difficulty', 'beginner'), prerequisites=tuple(data.get('prerequisites', [])),
                   completion_criteria=dict(data.get('completion_criteria', {})),
                   objectives=tuple(data.get('objectives', [])), rewards=tuple(data.get('rewards', [])),
                   documentation_link=data.get('documentation_link', 'help.canvas'),
                   estimated_minutes=int(data.get('estimated_minutes', 5)))


class CourseRegistry:
    def __init__(self, lessons):
        self.lessons = {lesson.id: lesson for lesson in lessons}
        if len(self.lessons) != len(lessons):
            raise ValueError('Duplicate lesson ID')
        for lesson in lessons:
            if any(key not in self.lessons for key in lesson.prerequisites):
                raise ValueError('Unknown prerequisite')

    def get(self, lesson_id):
        return self.lessons[lesson_id]
