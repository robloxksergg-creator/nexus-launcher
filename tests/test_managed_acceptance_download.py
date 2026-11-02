import hashlib
import io
import json
from pathlib import Path
import runpy
import urllib.request

import pytest

tool = runpy.run_path(str(Path(__file__).parents[1] / 'packaging/download_managed_acceptance.py'))


def test_redirect_strips_bearer_without_changing_original_request():
    request = urllib.request.Request('https://api.github.com/example',
                                     headers={'Authorization': 'Bearer SYNTHETIC_ONLY'})
    redirected = tool['AnonymousRedirects']().redirect_request(
        request, None, 302, 'Found', {}, 'https://release-assets.githubusercontent.com/fixture')
    assert redirected.get_header('Authorization') is None
    assert request.get_header('Authorization') == 'Bearer SYNTHETIC_ONLY'
    with pytest.raises(ValueError, match='HTTPS'):
        tool['AnonymousRedirects']().redirect_request(request, None, 302, 'Found', {}, 'http://example.test/x')


def test_four_hash_pinned_inputs_only_use_literal_repository_api(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'SYNTHETIC_ONLY')
    seen = []

    class Opener:
        def open(self, request, timeout):
            assert request.full_url.startswith('https://api.github.com/repos/' + tool['REPO'] + '/releases/assets/')
            seen.append(request.full_url)
            return io.BytesIO(b'a')

    monkeypatch.setattr(urllib.request, 'build_opener', lambda *_: Opener())
    config = tmp_path / 'inputs.json'
    config.write_text(json.dumps({name: {'id': i + 1, 'bytes': 1,
                      'sha256': hashlib.sha256(b'a').hexdigest()}
                      for i, name in enumerate(tool['NAMES'])}))
    destination = tmp_path / 'owned-downloads'
    tool['download'](config, destination)
    assert len(seen) == 4
    assert {p.name for p in destination.iterdir()} == tool['NAMES']
    assert all(p.read_bytes() == b'a' for p in destination.iterdir())
    with pytest.raises(ValueError, match='New acceptance'):
        tool['download'](config, destination)
