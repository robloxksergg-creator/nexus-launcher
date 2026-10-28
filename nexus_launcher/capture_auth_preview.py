"""Local visual-only capture, without account/network service mutations."""
import os
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from nexus_launcher.nexus_platform.prototype_host import PrototypeHost


class Services:
    def close(self):
        pass


app = QApplication([])
host = PrototypeHost(Services())
host.resize(2560 if '--layout' in sys.argv else 1366, 1040 if '--layout' in sys.argv else 900)
host.show()


def loaded(ok):
    if not ok:
        return
    def opened(_value):
        def capture():
            host.grab().save('deliverables/desktop-v12-skin.png' if '--skin' in sys.argv else 'deliverables/desktop-v11-profile.png' if '--profile' in sys.argv else 'deliverables/desktop-v11-overview.png' if '--layout' in sys.argv else 'deliverables/desktop-v7-auth-choice.png')
            host.close()
            app.quit()
        QTimer.singleShot(1000, capture)
    QTimer.singleShot(500, lambda: host.page.runJavaScript("showProfileSpace('overview');document.querySelector('.skin-preview').scrollIntoView({block:'end'})" if '--skin' in sys.argv else "showProfileSpace('overview')" if '--profile' in sys.argv else "NexusDiscovery.openServer()" if '--server' in sys.argv else 'true' if '--layout' in sys.argv else "document.querySelector('#desktop-account-login').click()", opened))


host.view.loadFinished.connect(loaded)
QTimer.singleShot(15000, app.quit)
app.exec()
