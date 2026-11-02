"""Fetch hash-pinned private CI review assets; never pass credentials to CDN."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from urllib.parse import urlsplit

REPO = 'robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024'
NAMES = {'initial-package.zip', 'initial-envelope.json', 'update-package.zip', 'update-envelope.json'}
LIMIT = 300 * 1024 * 1024


class AnonymousRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise ValueError('Only HTTPS redirects allowed')
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header('Authorization')
        return redirected


def download(config, destination):
    records = json.loads(Path(config).read_text(encoding='utf-8'))
    if not isinstance(records, dict) or set(records) != NAMES:
        raise ValueError('Unexpected acceptance asset set')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('New acceptance input directory required')
    destination.mkdir()
    token = os.environ['GITHUB_TOKEN']
    opener = urllib.request.build_opener(AnonymousRedirects())
    for name, record in records.items():
        if (set(record) != {'id', 'bytes', 'sha256'} or type(record['id']) is not int
                or type(record['bytes']) is not int or not 0 < record['bytes'] <= LIMIT):
            raise ValueError('Invalid pinned asset')
        url = f'https://api.github.com/repos/{REPO}/releases/assets/{record["id"]}'
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
                     'Accept': 'application/octet-stream', 'User-Agent': 'NEXUS-offline-acceptance'})
        digest, received = hashlib.sha256(), 0
        with opener.open(request, timeout=90) as stream, (destination / name).open('xb') as output:
            while block := stream.read(1024 * 1024):
                received += len(block)
                if received > record['bytes']:
                    raise ValueError('Asset exceeded pinned size')
                digest.update(block)
                output.write(block)
        if received != record['bytes'] or digest.hexdigest() != record['sha256']:
            raise ValueError('Acceptance input integrity mismatch')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    download(args.config, args.destination)
    print('Four pinned acceptance inputs verified')
