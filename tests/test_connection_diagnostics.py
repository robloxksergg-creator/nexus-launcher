import json
import socket
import ssl
import urllib.error

import pytest

from nexus_launcher.connection_diagnostics import probe_account_connection, transport_failure
from nexus_launcher.nexus_account import AccountError, OfflineError


@pytest.mark.parametrize("cause,category", [
    (ssl.SSLCertVerificationError(1, "private diagnostic"), "TLS_CERTIFICATE"),
    (ssl.SSLError(1, "private diagnostic"), "TLS"),
    (socket.gaierror(1, "private diagnostic"), "DNS"),
    (TimeoutError("private diagnostic"), "TIMEOUT"),
    (PermissionError("private diagnostic"), "CONNECTION_DENIED"),
    (OSError("private diagnostic"), "CONNECTION"),
])
def test_transport_failure_contains_codes_not_messages(cause, category):
    error = OfflineError("private account data")
    error.__cause__ = urllib.error.URLError(cause)
    report = transport_failure(error)
    assert report["category"] == category
    assert "private" not in json.dumps(report)


def test_probes_never_send_credentials_or_address(monkeypatch):
    calls = []
    class Client:
        base_url = "https://example.invalid"
        def __init__(self, timeout): assert timeout == 15
        def _request(self, path, **kwargs):
            calls.append((path, kwargs))
            raise AccountError("private response", http_status=401 if kwargs['method'] == 'GET' else 400, outcome="http_error")
    monkeypatch.setattr("nexus_launcher.nexus_account.NexusAccountClient", Client)
    report = probe_account_connection()
    assert [p['result'] for p in report['probes']] == ['EXPECTED_RESPONSE'] * 2
    assert [kwargs for _, kwargs in calls] == [dict(method='GET', payload=None), dict(method='POST', payload={})]
    assert not report['credentials_sent'] and not report['email_requested']
    assert "private" not in json.dumps(report)


def test_diagnostic_entrypoint_does_not_start_gui_or_open_storage(tmp_path, monkeypatch):
    from nexus_launcher import portable_main
    report = tmp_path / 'connection.json'
    monkeypatch.setattr('sys.argv', ['launcher.exe', '--connection-check-report', str(report)])
    monkeypatch.setattr('nexus_launcher.connection_diagnostics.probe_account_connection',
                        lambda: {'credentials_sent': False, 'email_requested': False})
    monkeypatch.setattr(portable_main, 'portable_data_root', lambda: pytest.fail('GUI storage opened'))
    portable_main.main()
    assert json.loads(report.read_text()) == {'credentials_sent': False, 'email_requested': False}
