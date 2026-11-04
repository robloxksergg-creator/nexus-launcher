"""Explicit anonymous header probes. Not a speed test or VPN detector."""
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from nexus_launcher.secure_http import open_https


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    hosts: frozenset[str]


class SourceDownloadError(ConnectionError):
    """Sanitized origin/file context, not a raw provider exception."""


def transfer_error(url, filename, error):
    reason = getattr(error, 'reason', error)
    code = f'HTTP_{error.code}' if isinstance(error, urllib.error.HTTPError) else 'TLS' if isinstance(reason, ssl.SSLError) else 'DNS' if isinstance(reason, socket.gaierror) else 'TIMEOUT' if isinstance(reason, TimeoutError) else 'CONNECTION'
    return SourceDownloadError(f"Источник загрузки: {urlsplit(url).hostname}; файл: {filename}; причина: {code}. Проверьте источники загрузки и повторите попытку.")


def sources(loader):
    from nexus_launcher.public_update_identity import FEED
    from nexus_launcher.github_updates import GITHUB_HOSTS
    loader_source = Source('NeoForge', 'https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml', frozenset({'maven.neoforged.net'}))
    if loader == 'fabric':
        loader_source = Source('Fabric', 'https://meta.fabricmc.net/v2/versions/game', frozenset({'meta.fabricmc.net'}))
    elif loader != 'neoforge':
        loader_source = Source('Библиотеки Minecraft', 'https://libraries.minecraft.net/', frozenset({'libraries.minecraft.net'}))
    return (
        Source('Обновления NEXUS / GitHub', FEED, GITHUB_HOSTS),
        Source('Метаданные Minecraft', 'https://launchermeta.mojang.com/mc/game/version_manifest_v2.json', frozenset({'launchermeta.mojang.com'})),
        loader_source,
        Source('CurseForge (сайт, не доступность модов)', 'https://www.curseforge.com/', frozenset({'www.curseforge.com', 'curseforge.com'})),
        Source('Modrinth API', 'https://api.modrinth.com/v2/tag/game_version', frozenset({'api.modrinth.com'})),
    )


def probe(source):
    started = time.monotonic()
    code, state = 'OK', 'ok'
    request = urllib.request.Request(source.url, method='HEAD', headers={'User-Agent': 'robloxksergg-creator/NEXUS-Launcher/source-diagnostics', 'Accept-Encoding': 'identity'})
    try:
        with open_https(request, timeout=5, allowed_hosts=source.hosts) as response:
            status = getattr(response, 'status', 200)
            if not 200 <= status < 300:
                code, state = f'HTTP_{status}', 'unknown'
    except urllib.error.HTTPError as error:
        code, state = f'HTTP_{error.code}', 'unknown'
        error.close()
    except (OSError, urllib.error.URLError, ValueError) as error:
        reason = getattr(error, 'reason', error)
        code = 'TLS' if isinstance(reason, ssl.SSLError) else 'DNS' if isinstance(reason, socket.gaierror) else 'TIMEOUT' if isinstance(reason, TimeoutError) else 'CONNECTION'
        state = 'unknown'
    elapsed = round((time.monotonic() - started) * 1000)
    # Deliberately exclude URL paths, queries, redirect signatures and raw exceptions.
    return state, f"{urlsplit(source.url).hostname} · {code} · {elapsed} мс. Проверены только заголовки этого адреса; скорость и скачивание файлов не проверялись."


def collect_sources(server, *, cancelled=lambda: False):
    from nexus_launcher.preinstall_check import Check, Report
    checks = []
    for index, source in enumerate(sources(getattr(server, 'loader', 'neoforge'))):
        if cancelled():
            return Report(tuple(checks), time.time(), True)
        state, detail = probe(source)
        checks.append(Check(f'source-{index}', source.name, state, detail))
    return Report(tuple(checks), time.time())
