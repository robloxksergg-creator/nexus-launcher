import requests
from minecraft_launcher_lib import _helper, install, runtime, microsoft_account

from nexus_launcher.minecraft_http import BoundedSession, InstallationRequests, NETWORK_TIMEOUT, configure_installation_http


def test_get_has_bounded_timeout_and_preserves_original_request_options(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, 'get', lambda *a, **k: calls.append((a, k)) or 'response')
    client = InstallationRequests()
    assert client.get('https://fixture.invalid/metadata', headers={'User-Agent': 'fixture'}) == 'response'
    assert calls[-1][1] == {'headers': {'User-Agent': 'fixture'}, 'timeout': NETWORK_TIMEOUT}
    client.get('https://fixture.invalid/metadata', timeout=None)
    assert calls[-1][1]['timeout'] == NETWORK_TIMEOUT
    client.get('https://fixture.invalid/metadata', timeout=5)
    assert calls[-1][1]['timeout'] == 5


def test_session_request_keeps_tls_default_and_caller_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(requests.Session, 'request', lambda self, *a, **k: calls.append((a, k)) or 'response')
    with InstallationRequests.session() as session:
        assert isinstance(session, BoundedSession)
        session.get('https://fixture.invalid/file', stream=True)
        assert calls[-1][1]['timeout'] == NETWORK_TIMEOUT
        assert 'verify' not in calls[-1][1]
        session.get('https://fixture.invalid/file', timeout=4)
        assert calls[-1][1]['timeout'] == 4


def test_configuration_is_idempotent_and_scoped_away_from_account_requests():
    original = requests.Session.request
    account_requests = microsoft_account.requests
    configure_installation_http()
    first = _helper.requests
    configure_installation_http()
    assert _helper.requests is first
    assert all(isinstance(m.requests, InstallationRequests) for m in (_helper, install, runtime))
    assert requests.Session.request is original
    assert microsoft_account.requests is account_requests


def test_module_without_requests_surface_remains_untouched(monkeypatch):
    monkeypatch.delattr(install, 'requests')
    configure_installation_http()
    assert not hasattr(install, 'requests')
