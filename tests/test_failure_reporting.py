import threading
from types import SimpleNamespace

from nexus_launcher.failure_reporting import FailureReporter, failure_code


class Client:
    def __init__(self):
        self.token = 'secret-not-in-payload'
        self.calls = []
        self.done = threading.Event()

    def support_session(self, account):
        return self.token

    def _request(self, path, **kw):
        self.calls.append((path, kw))
        self.done.set()
        return {'id': 'a' * 64}, None


def test_opt_in_and_verified_session_required():
    client = Client()
    reporter = FailureReporter()
    profile = SimpleNamespace(user_id='owner')
    assert not reporter.submit(client, profile, 'secret', '1.0.10')
    client.token = None
    assert not reporter.submit(client, profile, 'secret', '1.0.10', enabled=True)
    assert client.calls == []


def test_schema_only_report_dedup_and_hour_limit():
    client = Client()
    reporter = FailureReporter(clock=lambda: 7201)
    profile = SimpleNamespace(user_id='owner')
    for message in ['IncompleteRead C:/Users/private password=secret',
                    'GAME_TICKET_UNAVAILABLE token=secret',
                    'maven.neoforged.net timed out private@example.com']:
        client.done.clear()
        assert reporter.submit(client, profile, message, '1.0.10', enabled=True)
        assert client.done.wait(2)
        # Join only the bounded diagnostic worker, never a real network thread.
        for worker in threading.enumerate():
            if worker.name == 'nexus-failure-report': worker.join(2)
    assert not reporter.submit(client, profile, 'other', '1.0.10', enabled=True)
    assert not reporter.submit(client, profile, 'IncompleteRead', '1.0.10', enabled=True)
    assert reporter.state == 'SAVED_TO_SUPPORT_QUEUE'
    for _, request in client.calls:
        assert set(request['payload']) == {'subject', 'category', 'text'}
        assert 'secret' not in str(request['payload'])
        assert 'private' not in str(request['payload'])
        assert len(request['idempotency_key']) == 64


def test_revoked_preference_or_identity_cancels_before_dispatch():
    client = Client()
    reporter = FailureReporter()
    assert reporter.submit(client, SimpleNamespace(user_id='owner'), 'error', 'bad-version-secret',
                           enabled=True, allowed=lambda: False)
    for worker in threading.enumerate():
        if worker.name == 'nexus-failure-report': worker.join(2)
    assert reporter.state == 'CANCELLED'
    assert client.calls == []


def test_unknown_write_is_not_retried():
    client = Client()
    def unknown(*a, **k):
        client.calls.append(True)
        raise TimeoutError('secret')
    client._request = unknown
    reporter = FailureReporter()
    profile = SimpleNamespace(user_id='owner')
    assert reporter.submit(client, profile, 'error', '1.0.10', enabled=True)
    for worker in threading.enumerate():
        if worker.name == 'nexus-failure-report': worker.join(2)
    assert not reporter.submit(client, profile, 'error', '1.0.10', enabled=True)
    assert reporter.state == 'UNKNOWN'
    assert len(client.calls) == 1


def test_unknown_error_does_not_become_free_text():
    assert failure_code('password secret URL http://private/') == 'LAUNCH_FAILED'
