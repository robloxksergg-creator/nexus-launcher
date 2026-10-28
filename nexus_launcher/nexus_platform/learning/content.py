"""Trusted bundled lesson content and localization with explicit fallback."""
import json
from pathlib import Path
from .schema import Lesson, CourseRegistry


class LearningContent:
    def __init__(self, root: Path):
        self.strings = json.loads((root / 'strings.json').read_text(encoding='utf-8'))
        self.registry = CourseRegistry([Lesson.from_data(data) for data in json.loads((root / 'lessons.json').read_text(encoding='utf-8'))])

    def text(self, key, locale='ru'):
        return self.strings.get(locale, self.strings['en']).get(key, self.strings['en'].get(key, key))
