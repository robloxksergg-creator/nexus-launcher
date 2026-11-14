import io
import ssl
import urllib.request
from types import SimpleNamespace
import pytest
from nexus_launcher.secure_http import open_https


def test_modrinth_download_keeps_verified_tls_and_redirect_policy(monkeypatch):
    captured=[]
    class Reply(io.BytesIO):
        def geturl(self):return 'https://cdn.modrinth.com/file.jar'
    def opener(*handlers):
        captured.extend(handlers)
        return SimpleNamespace(open=lambda *a,**k:Reply(b'jar'))
    monkeypatch.setattr(urllib.request,'build_opener',opener)
    with open_https(urllib.request.Request('https://cdn.modrinth.com/file.jar'),5,allowed_hosts={'cdn.modrinth.com'}) as response:
        assert response.read()==b'jar'
    context=captured[1]._context
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    assert context.cert_store_stats()['x509_ca']>0
    with pytest.raises(ValueError):captured[0].validate('https://untrusted.invalid/file.jar')
    with pytest.raises(ValueError):captured[0].validate('http://cdn.modrinth.com/file.jar')


def test_other_transports_keep_existing_root_policy(monkeypatch):
    counts=[]
    monkeypatch.setattr(urllib.request,'build_opener',lambda *handlers:(counts.append(len(handlers)) or SimpleNamespace(open=lambda *a,**k:SimpleNamespace(geturl=lambda:'https://example.com/file'))))
    open_https(urllib.request.Request('https://example.com/file'),5)
    assert counts==[1]


def test_certificate_failure_is_not_retried_insecurely(monkeypatch):
    calls=[]
    def fail(*a,**k):
        calls.append(1)
        raise ssl.SSLCertVerificationError('untrusted fixture')
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:SimpleNamespace(open=fail))
    with pytest.raises(ssl.SSLCertVerificationError):
        open_https(urllib.request.Request('https://cdn.modrinth.com/file.jar'),5)
    assert len(calls)==1
