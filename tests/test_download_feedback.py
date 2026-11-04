"""Offline Qt checks with synthetic download events, never live downloads."""
import os
from types import SimpleNamespace

_application = None


def page():
    global _application
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.nexus_platform.pages import DownloadsPage
    _application = QApplication.instance() or QApplication([])
    return DownloadsPage()


def event(done, sampled, total=1024**3, phase='download'):
    return SimpleNamespace(operation_id='synthetic', phase=phase, current_file='mods/test.jar', bytes_done=done, bytes_total=total, sampled_at=sampled)


def test_preparation_counts_are_not_network_bytes_or_speed():
    p = page()
    p.update_progress('Build', 143, 3800, unit='steps')
    assert p.bytes.text() == 'Шаги: 143 / 3800'
    assert 'не измеряется' in p.telemetry.text()
    assert p.percent.text() == '3%'


def test_download_speed_and_bounded_eta_and_retry_reset():
    p = page()
    for done, sampled in [(100, 1), (200, 2), (300, 3)]: p.update_event(event(done, sampled))
    assert p.current_speed == 100
    assert 'слишком низкая скорость' in p.telemetry.text()
    p.update_event(event(0, 4))
    assert p.current_speed == 0
    assert p.telemetry.text() == 'Расчёт времени…'
    assert p._samples['synthetic'] == [(4, 0)]


def test_verification_never_claims_transfer_speed():
    p = page()
    for done, sampled in [(100, 1), (200, 2), (300, 3)]: p.update_event(event(done, sampled, total=1000))
    assert 'осталось' in p.telemetry.text()
    p.update_event(event(300, 4, phase='verifying'))
    assert p.current_speed == 0
    assert p.telemetry.text() == 'Проверка без использования сети'
