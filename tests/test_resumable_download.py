import http.client
import io
import ssl
import urllib.error

import pytest

from nexus_launcher.resumable_download import receive


class Response(io.BytesIO):
    def __init__(self, body, *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def test_interrupted_stream_requests_only_missing_prefix_and_finishes():
    class Broken(Response):
        def read1(self, amount):
            if self.tell():
                raise http.client.IncompleteRead(b'', 3)
            return super().read1(3)
    offsets = []
    def open_response(offset):
        offsets.append(offset)
        return Broken(b'abc', headers={'Content-Length': '6'}) if not offset else Response(
            b'def', status=206, headers={'Content-Length': '3', 'Content-Range': 'bytes 3-5/6'})
    output = io.BytesIO()
    assert receive(output, open_response, size=6, limit=6, progress=lambda *_: None) == 6
    assert offsets == [0, 3]
    assert output.getvalue() == b'abcdef'


def test_ignored_range_restarts_instead_of_appending():
    offsets = []
    def open_response(offset):
        offsets.append(offset)
        return Response(b'abc' if not offset else b'abcdef', headers={'Content-Length': '6'})
    output = io.BytesIO()
    receive(output, open_response, size=6, limit=6, progress=lambda *_: None)
    assert offsets == [0, 3]
    assert output.getvalue() == b'abcdef'


@pytest.mark.parametrize('range_value', ['bytes 2-5/6', 'bytes 3-5/7', 'bytes 3-6/6', 'garbage'])
def test_wrong_range_never_appends(range_value):
    output = io.BytesIO()
    def open_response(offset):
        return Response(b'abc', headers={'Content-Length': '6'}) if not offset else Response(
            b'def', status=206, headers={'Content-Length': '3', 'Content-Range': range_value})
    with pytest.raises(ValueError):
        receive(output, open_response, size=6, limit=6, progress=lambda *_: None)
    assert output.getvalue() == b'abc'


def test_retries_are_bounded_and_incomplete_data_never_reports_completion():
    calls, samples = [], []
    def open_response(offset):
        calls.append(offset)
        raise ConnectionError('synthetic disconnect')
    with pytest.raises(ConnectionError):
        receive(io.BytesIO(), open_response, size=6, limit=6, progress=lambda *v: samples.append(v))
    assert calls == [0, 0, 0]
    assert samples == []


@pytest.mark.parametrize('error', [ssl.SSLCertVerificationError('fixture'), urllib.error.HTTPError('https://fixture.invalid', 403, 'fixture', {}, None)])
def test_certificate_and_http_refusal_do_not_retry(error):
    calls = []
    def open_response(offset):
        calls.append(offset)
        raise error
    with pytest.raises(type(error)):
        receive(io.BytesIO(), open_response, size=6, limit=6, progress=lambda *_: None)
    assert calls == [0]


def test_unknown_size_and_overflow_are_bounded():
    output = io.BytesIO()
    samples = []
    assert receive(output, lambda _: Response(b'abc'), size=0, limit=4, progress=lambda *v: samples.append(v)) == 3
    assert samples[-1] == (3, 0)
    with pytest.raises(ValueError):
        receive(io.BytesIO(), lambda _: Response(b'abcde'), size=0, limit=4, progress=lambda *_: None)


def test_deadline_stops_retries(monkeypatch):
    monkeypatch.setattr('nexus_launcher.resumable_download.time.monotonic', lambda: 10)
    with pytest.raises(TimeoutError):
        receive(io.BytesIO(), lambda _: pytest.fail('opened after deadline'), size=1, limit=1, timeout=0, progress=lambda *_: None)
