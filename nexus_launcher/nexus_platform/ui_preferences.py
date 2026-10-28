"""One non-sensitive preview preference, independent of temporary APPDATA."""
import json
import os
import tempfile
from pathlib import Path


class UIPreferences:
    def __init__(self, path=None):
        root = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local' / 'share')
        self.path = Path(path) if path else root / 'NexusDesignPreview' / 'ui-preferences.json'

    def sound_enabled(self):
        if not self.path.exists():
            return True
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data.get('soundEnabled') is True
        except (OSError, ValueError, AttributeError):
            # Never silently re-enable sound if a prior preference is unreadable.
            return False

    def save_sound(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('soundEnabled must be boolean')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='ui-preferences-', suffix='.tmp', delete=False) as file:
                temporary = Path(file.name)
                json.dump({'version': 1, 'soundEnabled': enabled}, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
