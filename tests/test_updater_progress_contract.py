import hashlib
import io

import nexus_launcher.updater as updater
from nexus_launcher.updater import ModpackUpdater, PackRelease
from nexus_launcher.updater import DownloadProgress


class Response(io.BytesIO):
    headers = {}
    def __enter__(self): return self
    def __exit__(self, *_): pass


def test_progress_event_has_stable_operation_and_unknown_total(tmp_path, monkeypatch):
    body = b"real bytes"
    events = []
    monkeypatch.setattr(updater, "open_https", lambda *a, **k: Response(body))
    release = PackRelease("1", "https://github.com/file.zip", hashlib.sha256(body).hexdigest(), pack="pack.zip")
    service = ModpackUpdater(tmp_path, progress_event=events.append, instance_id="world-main")
    service.download(release)
    assert events
    assert {e.operation_id for e in events} == {service.operation_id}
    assert events[-1].instance_id == "world-main"
    assert events[-1].current_file == "pack.zip"
    assert events[-1].bytes_done == len(body)
    assert events[-1].bytes_total is None
    assert events[-1].phase == "download"


def test_download_ui_uses_nullable_total_and_real_sample_speed():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.nexus_platform.pages import DownloadsPage
    app = QApplication.instance() or QApplication([])
    page = DownloadsPage()
    page.update_event(DownloadProgress("op", "nexus_launcher.main", "download", "mods/a.jar", 1024, None, 1.0), "GEARMORPH")
    assert page.progress.maximum() == 0
    assert "1.0 КБ" in page.bytes.text()
    page.update_event(DownloadProgress("op", "nexus_launcher.main", "download", "mods/a.jar", 2048, 4096, 2.0), "GEARMORPH")
    page.update_event(DownloadProgress("op", "nexus_launcher.main", "download", "mods/a.jar", 3072, 4096, 3.0), "GEARMORPH")
    assert "/с" in page.telemetry.text() and "осталось" in page.telemetry.text()
    page.show_failure("SHA-256 mismatch")
    assert "Проверка" in page.failure_title.text()
    assert page.failure_file.text() == "mods/a.jar"
