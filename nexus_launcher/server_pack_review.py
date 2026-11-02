"""Read-only onboarding review, never a malware verdict or execution grant.

Only declared metadata is examined. JARs, scripts, the remote server and the
effective OS/account isolation are not examined or sandboxed by this module.
"""
from dataclasses import asdict, dataclass
import json
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from nexus_launcher.secure_http import origin


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    detail: str


@dataclass(frozen=True)
class Review:
    status: str
    files: int
    declared_bytes: int
    findings: tuple[Finding, ...]


def review(server, release):
    """Inspect an existing ServerProfile and parsed PackRelease without I/O.

    REVIEW_REQUIRED means no blocking metadata finding was observed, not that
    execution is safe. This return value is intentionally not an admission API.
    """
    from nexus_launcher.updater import MAX_PACK_BYTES, validate_pack_content_path
    findings = []
    def add(code, severity, detail):
        findings.append(Finding(code, severity, detail))
    try:
        origin(server.manifest_url)
    except (ValueError, TypeError, AttributeError):
        add('MANIFEST_ORIGIN', 'block', 'Нужен HTTPS-манифест без credentials, fragment и нестандартного порта.')
    if release is None:
        add('NO_MANIFEST', 'block', 'Состав пакета недоступен.')
    else:
        for expected, actual, code in (
            (server.minecraft_version, release.minecraft, 'MINECRAFT_BINDING'),
            (server.loader, release.loader, 'LOADER_BINDING'),
            (server.loader_version, release.loader_version, 'LOADER_VERSION_BINDING'),
        ):
            if expected and actual and expected != actual:
                add(code, 'block', 'Метаданные сборки расходятся с выбранным профилем.')
            elif expected and not actual:
                add(code, 'unknown', 'Манифест не подтверждает параметр выбранного профиля.')
        if release.minecraft_server != server.address:
            # DNS aliases are not proof of equality; no DNS/network action here.
            add('SERVER_BINDING', 'unknown', 'Адреса профиля и манифеста различаются; эквивалентность не подтверждена.')
    entries = tuple(release.files) if release is not None else ()
    if release is not None and not entries:
        add('OPAQUE_ARCHIVE', 'unknown', 'Нет пофайлового списка; содержимое архива не проверено.')
    seen = set()
    total = 0
    executable_count = native_count = script_count = 0
    download_hosts = set()
    for entry in entries:
        try:
            validate_pack_content_path(entry.path)
            folded = entry.path.casefold()
            if folded in seen:
                raise ValueError('Duplicate path')
            seen.add(folded)
        except (ValueError, TypeError, IndexError):
            add('FILE_PATH', 'block', 'Недопустимый или повторяющийся путь файла.')
        if (type(entry.size) is not int or not 0 <= entry.size <= MAX_PACK_BYTES
                or not isinstance(entry.sha256, str) or len(entry.sha256) != 64
                or any(c not in '0123456789abcdefABCDEF' for c in entry.sha256)):
            add('FILE_INTEGRITY', 'block', 'Некорректный заявленный размер или SHA-256.')
        else:
            total += entry.size
        try:
            origin(entry.url)
            download_hosts.add(urlsplit(entry.url).hostname.lower())
        except (ValueError, TypeError, AttributeError):
            add('FILE_ORIGIN', 'block', 'Недопустимый адрес загрузки файла.')
        suffix = PurePosixPath(entry.path).suffix.casefold()
        if suffix == '.jar':
            executable_count += 1
        if suffix in {'.exe', '.dll', '.so', '.dylib', '.com', '.scr', '.msi'}:
            native_count += 1
        if suffix in {'.js', '.py', '.sh', '.bat', '.cmd', '.ps1', '.vbs'}:
            script_count += 1
    if executable_count:
        add('JAVA_CODE', 'review', f'JAR-файлы: {executable_count}. Хеш не доказывает отсутствие кражи данных или майнера.')
    if native_count:
        add('NATIVE_CODE', 'review', f'Нативные файлы: {native_count}. Требуется отдельная проверка происхождения и содержимого.')
    if script_count:
        add('SCRIPT_CODE', 'review', f'Скрипты: {script_count}. Требуется отдельная проверка; расширение не определяет безопасность.')
    if download_hosts:
        add('DOWNLOAD_SOURCES', 'info', f'Источников загрузки: {len(download_hosts)}. Содержимое файлов не загружалось и не анализировалось.')
    add('PUBLISHER_IDENTITY', 'unknown', 'HTTPS и заявленные SHA-256 не устанавливают личность и добросовестность издателя.')
    add('PLAYER_ISOLATION', 'unknown', 'Изоляция Java/модов от файлов, токенов и ресурсов компьютера не доказана. Отдельная папка не является sandbox.')
    add('TENANT_ISOLATION', 'unknown', 'Права владельца, границы API-токена, доступ к чужим серверам и лимиты хостинга этим отчётом не проверены.')
    return Review('BLOCKED' if any(f.severity == 'block' for f in findings) else 'REVIEW_REQUIRED', len(entries), total, tuple(findings))


def main():
    import argparse
    from nexus_launcher.projects import ServerProfile
    from nexus_launcher.updater import fetch_manifest
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--address', required=True)
    parser.add_argument('--minecraft', required=True)
    parser.add_argument('--loader', required=True)
    parser.add_argument('--loader-version', default='')
    args = parser.parse_args()
    server = ServerProfile('review', 'Review', args.address, args.manifest,
                           args.minecraft, args.loader, args.loader_version)
    # Transport uses the existing HTTPS/bounded manifest parser. No pack download.
    try:
        result = review(server, fetch_manifest(args.manifest))
    except (ValueError, OSError) as error:
        print(json.dumps({'status': 'BLOCKED', 'reason': type(error).__name__}))
        return 2
    print(json.dumps(asdict(result), ensure_ascii=True, indent=2))
    return 2 if result.status == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
