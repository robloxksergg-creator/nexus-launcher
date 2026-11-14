"""Early, credential-free startup breadcrumbs, before importing Qt."""
import os
from pathlib import Path
import sys
import threading
import time


class StartupTrace:
    def __init__(self, *, root=None, delay=45, notify=None):
        self.started = time.monotonic()
        self.current = 'python-start'
        self.finished = threading.Event()
        self.notify = notify or self._notify
        self.path = None
        try:
            base = Path(root) if root is not None else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'NEXUS Launcher' / 'logs'
            base.mkdir(parents=True, exist_ok=True)
            self.path = base / f'startup-{os.getpid()}.log'
        except OSError:
            pass
        self.stage('python-start')
        self.timer = threading.Timer(delay, self._timeout)
        self.timer.daemon = True
        self.timer.start()

    def stage(self, name):
        # Callers pass static stage labels only, never exception bodies/account data.
        if not name or len(name)>80 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in name):
            raise ValueError('Invalid startup stage')
        self.current = name
        if self.path is not None:
            try:
                with self.path.open('a',encoding='utf-8') as stream:
                    stream.write(f'{time.monotonic()-self.started:.3f}s {name}\n')
            except OSError:
                pass

    def ready(self):
        self.stage('renderer-ready')
        self.close()

    def close(self):
        self.finished.set()
        self.timer.cancel()

    def fail(self, stage):
        self.stage(stage)
        self.close()
        self.notify(stage, self.path)

    def _timeout(self):
        if not self.finished.is_set():
            stage = self.current
            self.stage('startup-deadline')
            self.notify(stage, self.path)

    @staticmethod
    def _notify(stage, path):
        if sys.platform == 'win32':
            import ctypes
            title = 'NEXUS — ошибка запуска' if stage in {'startup-exception','renderer-terminated'} else 'NEXUS — запуск задерживается'
            heading = 'Не удалось открыть интерфейс NEXUS.' if stage in {'startup-exception','renderer-terminated'} else 'NEXUS запускается дольше обычного.'
            message = (heading + '\n'
                f'Этап: {stage}\nЖурнал: {path or "недоступен"}\n\n'
                'Не запускайте дополнительные копии. Передайте журнал поддержке. '
                'Запуск от администратора не требуется.')
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x30)
