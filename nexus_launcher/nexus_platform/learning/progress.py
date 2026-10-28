"""Independent atomic learning progress; no project document writes."""
import json
import os
import tempfile
from pathlib import Path


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.learning-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProgressManager:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {'schema': 1, 'current': None, 'lessons': {}, 'dismissed_tips': [],
                     'achievements': [], 'settings': {'mode': 'guided', 'tips': True,
                     'hints': True, 'auto_start': False, 'show_completed': True, 'locale': 'ru',
                     'onboarding_seen': False, 'reduced_motion': False}}
        if self.path.is_file():
            # Never silently overwrite corrupt or newer progress files.
            loaded = json.loads(self.path.read_text(encoding='utf-8'))
            if loaded.get('schema') != 1 or not isinstance(loaded.get('lessons'), dict):
                raise ValueError('Unsupported learning progress format')
            self.data.update({k: loaded[k] for k in self.data if k in loaded and k != 'settings'})
            self.data['settings'].update(loaded.get('settings', {}))

    def save(self):
        write_json(self.path, self.data)

    def reset(self):
        self.data.update(current=None, lessons={}, achievements=[], dismissed_tips=[])
        self.save()
