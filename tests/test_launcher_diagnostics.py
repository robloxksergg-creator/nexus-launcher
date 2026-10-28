import importlib.util
import json
from pathlib import Path
import sys
import threading

import pytest


@pytest.fixture
def health(tmp_path):
    diagnostics = Path(__file__).resolve().parents[1] / 'nexus_launcher' / 'launcher_diagnostics.py'
    spec=importlib.util.spec_from_file_location('isolated_health', diagnostics)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old_main,old_thread=sys.excepthook,threading.excepthook
    module.install(tmp_path)
    yield module,tmp_path
    sys.excepthook,threading.excepthook=old_main,old_thread
    for handler in module._logger.handlers:handler.close()


def test_server_error_is_not_misclassified_as_client_crash(health):
    h,p=health;assert h.record('registration_code','http_error',502,123)
    report=json.loads((p/'health-summary.json').read_text(encoding='utf-8'))
    assert report['findings'][0]['code']=='SERVER_FAILURE'
    assert 'LAUNCHER_EXCEPTION' not in (p/'health-summary.json').read_text(encoding='utf-8')


def test_sensitive_values_are_rejected_not_redacted_after_logging(health):
    h,p=health
    for value in ['private@example.invalid','password-token-123456','https://secret.invalid/']:
        assert h.record(value,'ok') is False
        assert h.record('account',value) is False
        assert h.record('account','ok',value) is False
        assert h.record('account','ok',200,value) is False
        assert value not in (p/'events.jsonl').read_text(encoding='utf-8')


def test_exception_hooks_store_no_exception_message(health):
    h,p=health
    sys.excepthook(RuntimeError,RuntimeError('secret-password-code'),None)
    text=(p/'health-summary.json').read_text(encoding='utf-8')
    assert 'LAUNCHER_EXCEPTION' in text and 'secret-password-code' not in text


def test_network_and_protocol_remain_distinct(health):
    h,p=health
    h.record('account','network_error');h.record('account','protocol_error')
    codes={x['code'] for x in json.loads((p/'health-summary.json').read_text(encoding='utf-8'))['findings']}
    assert codes=={'CONNECTION_UNCONFIRMED','RESPONSE_FORMAT'}


def test_rotation_and_install_are_bounded(health):
    h,p=health;assert h.install(p/'unused')==p
    for _ in range(1800):assert h.record('account','ok',200,10)
    assert len(list(p.glob('events.jsonl*')))<=3
    assert all(f.stat().st_size<=263000 for f in p.glob('events.jsonl*'))
