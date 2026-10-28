"""Application readiness probe, beyond show()/loadFinished/constructor completion.

Criterion: initialized services + resolved startup session + usable native auth
gate or launcher route + responsive renderer with installed navigation handlers.
Offline auth is a usable error state, not successful server authentication.
"""
from PySide6.QtCore import QObject, QTimer

SCRIPT = """Boolean(document.readyState === 'complete' && window.NexusUI &&
window.NexusNativeLibrary && document.querySelector('.navigation-toggle') &&
document.querySelector('.workspace') && document.querySelector('[data-route]'))"""


class TesterReadinessProbe(QObject):
    def __init__(self, host, services, auth, gate, buttons, ready):
        super().__init__(host)
        self.host, self.services, self.auth, self.gate = host, services, auth, gate
        self.buttons, self.ready, self.done, self.pending = buttons, ready, False, False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def eligible(self):
        return (self.host.isVisible() and not self.auth.busy
                and self.auth.status in {"authenticated", "unauthenticated"}
                and hasattr(self.services, 'instance_service')
                and isinstance(self.services.config, dict)
                and not self.host.page.script_errors
                and (self.host.surfaces.currentWidget() is self.host.view
                     or (self.host.surfaces.currentWidget() is self.gate
                         and all(button.isEnabled() and button.isVisible() for button in self.buttons))))

    def check(self):
        if self.done or self.pending or not self.eligible():
            return
        self.pending = True
        self.host.page.runJavaScript(SCRIPT, self._renderer_ready)

    def _renderer_ready(self, result):
        self.pending = False
        if self.done or result is not True or not self.eligible():
            return
        self.done = True
        self.timer.stop()
        # Deferred delivery proves one more turn of the native event loop after
        # the renderer responded; the IPC ACK contains no user/session content.
        QTimer.singleShot(0, self, self._deliver)

    def _deliver(self):
        if self.eligible():
            try:
                self.ready()
            except OSError:
                self.host.close()
        else:
            self.done = False
            self.timer.start()
