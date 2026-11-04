import io
import socket
import ssl
from types import SimpleNamespace
import urllib.error

from nexus_launcher import download_sources as module


def test_probe_is_head_only_and_never_reads_body_or_sends_credentials(monkeypatch):
    calls = []
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_): raise AssertionError('probe must not download body')
    def opened(request, **kwargs):
        calls.append((request, kwargs))
        return Reply()
    monkeypatch.setattr(module, 'open_https', opened)
    state, detail = module.probe(module.sources('neoforge')[2])
    assert state == 'ok' and 'скорость' in detail
    request, options = calls[0]
    assert request.get_method() == 'HEAD'
    assert not any(k.lower() in {'cookie','authorization'} for k in request.headers)
    assert options == {'timeout': 5, 'allowed_hosts': frozenset({'maven.neoforged.net'})}
    assert '/releases/' not in detail


def test_failures_are_categorized_without_raw_private_exception(monkeypatch):
    for error, code in [(urllib.error.URLError(socket.gaierror('private')), 'DNS'),
                        (urllib.error.URLError(ssl.SSLCertVerificationError('private')), 'TLS'),
                        (TimeoutError('private'), 'TIMEOUT'),
                        (urllib.error.HTTPError('https://private.invalid/?secret=x',429,'private',{},io.BytesIO()), 'HTTP_429')]:
        def opened(*_, **__): raise error
        monkeypatch.setattr(module, 'open_https', opened)
        state, detail = module.probe(module.sources('neoforge')[2])
        assert state == 'unknown' and code in detail
        assert 'private' not in detail and 'secret' not in detail


def test_probe_targets_are_fixed_and_cancellation_stops_before_network(monkeypatch):
    monkeypatch.setattr(module, 'probe', lambda _: (_ for _ in ()).throw(AssertionError('network')))
    report = module.collect_sources(SimpleNamespace(loader='neoforge'), cancelled=lambda: True)
    assert report.cancelled and report.checks == ()
    assert len(module.sources('neoforge')) == 5
    assert module.sources('fabric')[2].name == 'Fabric'


def test_actual_transfer_context_excludes_signed_query_and_raw_error():
    error = module.transfer_error('https://github.com/release?secret=private', 'mods/test.jar', TimeoutError('raw-private'))
    assert isinstance(error, ConnectionError)
    assert 'github.com' in str(error) and 'mods/test.jar' in str(error) and 'TIMEOUT' in str(error)
    assert 'private' not in str(error) and 'secret' not in str(error)


def test_failure_shows_failed_file_instead_of_other_parallel_workers_last_event():
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.nexus_platform.pages import DownloadsPage
    app = QApplication.instance() or QApplication([])
    page = DownloadsPage()
    page._last_event = SimpleNamespace(instance_id='main',current_file='mods/other-worker.jar')
    reason = str(module.transfer_error('https://github.com/file', 'mods/failed.jar', TimeoutError()))
    page.show_failure(reason)
    assert page.failure_file.text() == 'mods/failed.jar'
    assert 'github.com' in page.failure_reason.text()
    assert 'TIMEOUT' in page.failure_reason.text()
    page.close()
