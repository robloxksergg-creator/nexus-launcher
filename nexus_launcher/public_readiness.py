"""A responsive production UI is readiness, not proof of server authentication."""
from PySide6.QtCore import QObject, QTimer

SCRIPT = """Boolean(document.readyState === 'complete' && window.NexusUI &&
window.NexusNativeLibrary && document.querySelector('.navigation-toggle') &&
document.querySelector('.workspace') && document.querySelector('[data-route]'))"""


class PublicReadinessProbe(QObject):
    def __init__(self, host, services, ready):
        super().__init__(host)
        self.host, self.services, self.ready = host, services, ready
        self.done = self.pending = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def eligible(self):
        return (self.host.isVisible() and self.host.view.isVisible()
                and hasattr(self.services, 'instance_service')
                and isinstance(self.services.config, dict)
                and not self.host.page.script_errors)

    def check(self):
        if self.done or self.pending or not self.eligible():
            return
        self.pending = True
        self.host.page.runJavaScript(SCRIPT, self.received)

    def received(self, responsive):
        self.pending = False
        if responsive is not True or not self.eligible() or self.done:
            return
        self.done = True
        self.timer.stop()
        QTimer.singleShot(0, self, self.deliver)

    def deliver(self):
        if self.eligible():
            try:
                self.ready()
            except OSError:
                self.host.close()
        else:
            self.done = False
            self.timer.start()
