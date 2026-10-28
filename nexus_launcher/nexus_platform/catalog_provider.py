"""Paged Modrinth search; installation remains in the existing verified provider."""
import json
import time
import urllib.parse
import urllib.request
from threading import Lock

from nexus_launcher.resource_limits import read_limited
from nexus_launcher.secure_http import open_https

from nexus_launcher.modrinth_provider import ModrinthProvider
from nexus_launcher.user_instances import VALID_LOADERS
from .catalog_filters import ModrinthFilterState, ModrinthQueryBuilder


class CatalogProvider(ModrinthProvider):
    def __init__(self):
        super().__init__()
        self._cache = {}
        self._lock = Lock()

    def _get(self, path, params=None):
        key = path + '?' + urllib.parse.urlencode(params or {})
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.monotonic() - entry[0] < 300:
                return entry[1]
        request = urllib.request.Request('https://api.modrinth.com/v2' + key,
            headers={'User-Agent': self.user_agent, 'Accept': 'application/json'})
        with open_https(request, timeout=8, allowed_hosts={'api.modrinth.com'}) as response:
            value = json.loads(read_limited(response))
        with self._lock:
            if len(self._cache) >= 64:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic(), value)
        return value

    def project(self, project_id):
        return self._get('/project/' + urllib.parse.quote(project_id, safe=''))

    def search_page(self, query, version='', loader='', *, category='', side='',
                    sort='relevance', offset=0, filters=None):
        # Existing read-only callers retain their signature. New UI passes a snapshot.
        state = filters or ModrinthFilterState(
            versions=(version,) if version else (),
            loaders=(loader,) if loader and loader != 'vanilla' else (),
            categories=(category,) if category else (), index=sort)
        params = ModrinthQueryBuilder.params(state, query, offset)
        if side:
            groups = {
                'client': ('client_and_server', 'client_only', 'client_only_server_optional',
                           'singleplayer_only', 'server_only_client_optional',
                           'client_or_server', 'client_or_server_prefers_both'),
                'server': ('client_and_server', 'server_only', 'server_only_client_optional',
                           'dedicated_server_only', 'client_only_server_optional',
                           'client_or_server', 'client_or_server_prefers_both'),
            }
            if side not in groups:
                raise ValueError('Неизвестная среда')
            facets = json.loads(params['facets'])
            facets.append(['environment:' + value for value in groups[side]])
            params['facets'] = json.dumps(facets)
        return self._get('/search', params)

    def filter_tags(self):
        versions = self._get('/tag/game_version', {})
        loaders = self._get('/tag/loader', {})
        categories = self._get('/tag/category', {})
        return {
            'versions': [tag['version'] for tag in versions],
            'loaders': [tag['name'] for tag in loaders if 'mod' in tag.get('supported_project_types', [])
                        and tag['name'] in VALID_LOADERS - {'vanilla'}],
            'categories': [tag['name'] for tag in categories if tag.get('project_type') == 'mod'],
        }
