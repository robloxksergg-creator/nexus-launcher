"""Read-only audit of the active launcher's metadata and catalogue manifests."""
import json
import urllib.request
import zipfile
from datetime import datetime, UTC
from pathlib import Path

from nexus_launcher.projects import DEFAULT_PROJECTS
from nexus_launcher.secure_http import open_https
from nexus_launcher.self_update import MANIFEST_URL, FALLBACK_MANIFEST_URL, CURRENT_VERSION
from nexus_launcher.signed_release import verify_envelope, verify_signature
from nexus_launcher.updater import fetch_manifest, TRUSTED_DOWNLOAD_HOSTS
from nexus_launcher.user_instances import UserInstance


def audit(data_root: Path, output: Path):
    root = Path(__file__).resolve().parents[1]
    results = []
    paths = [*root.glob('assets/*.json'), root / 'docs' / 'audits' / 'data' / 'premium-ui.json',
             *data_root.rglob('*.json')]
    for path in paths:
        row = {'path': str(path), 'kind': 'local-json'}
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
            if path.name == 'instance.json':
                instance = UserInstance.from_dict(payload)
                if instance.id != path.parent.name:
                    raise ValueError('Instance ID does not match its directory')
                row['name'] = instance.name
            row['status'] = 'valid'
        except Exception as error:
            row.update(status='error', error=str(error))
        results.append(row)
    servers = {server.id: server for project in DEFAULT_PROJECTS for server in project.servers}
    for catalog in data_root.rglob('projects.json'):
        payload = json.loads(catalog.read_text(encoding='utf-8'))
        for project in payload.get('nexus_launcher.projects', []):
            for server in project.get('servers', []):
                # Include configured endpoints, without printing credentials.
                from nexus_launcher.projects import ServerProfile
                servers[server['id']] = ServerProfile(
                    server['id'], server['name'], server.get('address', ''),
                    manifest_url=server.get('manifest_url', ''),
                    local_pack_path=server.get('local_pack_path', ''),
                )
    for server in servers.values():
        row = {'server': server.id, 'kind': 'pack-manifest'}
        try:
            if server.manifest_url:
                row['url'] = server.manifest_url
                release = fetch_manifest(server.manifest_url)
                if release is None:
                    row['status'] = 'unavailable'
                else:
                    row.update(status='valid', version=release.version, files=len(release.files),
                               minimum_launcher_version=release.minimum_launcher_version)
            elif server.local_pack_path:
                row['path'] = server.local_pack_path
                archive = root / 'assets' / server.local_pack_path
                if not archive.is_file():
                    row.update(status='missing', error='Bundled pack archive is absent')
                else:
                    with zipfile.ZipFile(archive) as packed:
                        bad = packed.testzip()
                        if bad:
                            raise ValueError('Corrupt ZIP entry: ' + bad)
                        row.update(status='valid', files=len(packed.namelist()))
            else:
                row['status'] = 'no-manifest'
        except Exception as error:
            row.update(status='error', error=str(error))
        results.append(row)
    for url in (MANIFEST_URL, FALLBACK_MANIFEST_URL):
        row = {'kind': 'launcher-update', 'url': url}
        try:
            request = urllib.request.Request(url + '?platform=windows&arch=x64',
                                             headers={'Accept': 'application/json',
                                                      'User-Agent': f'NEXUS-Launcher/{CURRENT_VERSION}'})
            with open_https(request, timeout=15, allowed_hosts=TRUSTED_DOWNLOAD_HOSTS) as reply:
                payload = json.loads(reply.read(1024 * 1024 + 1))
            if payload.get('available') is False:
                row['status'] = 'no-update'
            else:
                signed = verify_signature(payload)
                row.update(signature='valid', version=signed.get('version'),
                           published_at=signed.get('published_at'),
                           expires_at=signed.get('expires_at'))
                release = verify_envelope(payload)
                row.update(status='valid', version=release.get('version'),
                           expires_at=release.get('expires_at'))
        except Exception as error:
            row.update(status='error', error=str(error))
        results.append(row)
    report = {'checked_at': datetime.now(UTC).isoformat(), 'results': results,
              'scope': 'Active launcher metadata, portable data, configured pack endpoints and update endpoints. '
                       'Download payload hashes are validated by the installer, not by downloading every file here.'}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in results:
        print(row)


if __name__ == '__main__':
    import sys
    audit(Path(sys.argv[1]), Path(sys.argv[2]))
