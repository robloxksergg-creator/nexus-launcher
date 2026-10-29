import pytest
from PySide6.QtWidgets import QApplication, QWidget

from nexus_launcher.public_readiness import PublicReadinessProbe


class Page:
    def __init__(self):
        self.script_errors = []
        self.callback = None

    def runJavaScript(self, script, callback):
        self.callback = callback


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.page = Page()
        self.view = self


class Services:
    instance_service = object()
    config = {}


@pytest.fixture
def probe():
    app = QApplication.instance() or QApplication([])
    host = Host()
    host.show()
    acknowledgments = []
    value = PublicReadinessProbe(host, Services(), lambda: acknowledgments.append('ready'))
    yield value, host, app, acknowledgments
    value.timer.stop()
    host.close()


def test_no_ack_for_hidden_host_script_errors_or_false_renderer(probe):
    value, host, app, acknowledgments = probe
    host.hide()
    value.check()
    assert host.page.callback is None
    host.show()
    host.page.script_errors.append('synthetic error')
    value.check()
    assert host.page.callback is None
    host.page.script_errors.clear()
    value.check()
    host.page.callback(False)
    app.processEvents()
    assert not acknowledgments and not value.done


def test_ack_follows_renderer_response_and_another_native_turn_only_once(probe):
    value, host, app, acknowledgments = probe
    value.check()
    assert not acknowledgments
    host.page.callback(True)
    assert not acknowledgments
    app.processEvents()
    assert acknowledgments == ['ready']
    value.check()
    value.received(True)
    app.processEvents()
    assert acknowledgments == ['ready']


def test_lost_eligibility_before_delivery_does_not_ack(probe):
    value, host, app, acknowledgments = probe
    value.check()
    host.page.callback(True)
    host.hide()
    app.processEvents()
    assert not acknowledgments and not value.done
