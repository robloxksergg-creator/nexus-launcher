import io
import json
import urllib.error

import pytest
from nexus_launcher import updater


@pytest.mark.parametrize('primary,backup',[
    ('nexusmc-site.robloxksergg.workers.dev','nexusmc.flux-productions.com'),
    ('nexusmc.flux-productions.com','nexusmc-site.robloxksergg.workers.dev'),
])
def test_existing_nexus_fallback_is_bounded_and_keeps_manifest_validation(monkeypatch,primary,backup):
    calls=[]
    body=json.dumps({'version':'1','url':'https://github.com/file.zip','sha256':'0'*64}).encode()
    class Reply(io.BytesIO):
        headers={'Content-Length':str(len(body))}
    def opened(request, **kwargs):
        calls.append(request.full_url)
        assert request.get_header('Authorization') is None
        if len(calls)==1: raise urllib.error.URLError('synthetic unavailable')
        return Reply(body)
    monkeypatch.setattr(updater,'open_https',opened)
    path='/api/launcher/modpacks/gearmorph'
    result=updater.fetch_manifest('https://'+primary+path)
    assert result.version=='1'
    assert calls==['https://'+primary+path,'https://'+backup+path]


def test_exhausted_sources_preserve_transport_error_and_do_not_invent_a_mirror(monkeypatch):
    calls=[]
    def opened(request, **kwargs):
        calls.append(request.full_url)
        raise urllib.error.URLError('synthetic unavailable')
    monkeypatch.setattr(updater,'open_https',opened)
    with pytest.raises(urllib.error.URLError):
        updater.fetch_manifest('https://nexusmc-site.robloxksergg.workers.dev/api/launcher/modpacks/gearmorph')
    assert len(calls)==2
