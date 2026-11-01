"""Bounded, read-only instance diagnostics. Metadata is evidence, not execution.

No JAR extraction, class loading, network, repairs, or claim of malware safety.
"""
from dataclasses import dataclass
import itertools
import json
from pathlib import Path
import re
import tomllib
import zipfile

from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.dependency_versions import check_version

MAX_MODS = 1000
MAX_METADATA = 1024 * 1024
MAX_LOG = 512 * 1024
ID = re.compile(r'[a-zA-Z0-9_.-]{1,128}\Z')
BUILTINS = {'minecraft', 'java'}


@dataclass(frozen=True)
class ModInfo:
    filename: str
    ids: tuple[str, ...]
    loaders: tuple[str, ...]
    requires: tuple[tuple[str, str], ...]
    nested: bool
    versions: tuple[tuple[str, str], ...] = ()
    requirements: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class DependencyCheck:
    filename: str
    dependency: str
    expression: str
    actual: str
    status: str
    reason: str


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    title: str
    detail: str
    evidence: tuple[str, ...] = ()
    filename: str = ''


@dataclass(frozen=True)
class DiagnosticReport:
    mods: tuple[ModInfo, ...]
    findings: tuple[Finding, ...]
    complete: bool
    crash_file: str = ''
    version_checks: tuple[DependencyCheck, ...] = ()


def redact(text):
    text = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[REDACTED]', text)
    return re.sub(r'(?i)((?:access[_-]?token|refresh[_-]?token|password|authorization)\s*[=: ]\s*)[^\s,;]+', r'\1[REDACTED]', text)


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid mod ID')
    return value


def _unique_json(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError('Duplicate metadata key')
        data[key] = value
    return data


def inspect_mod(path, consume=lambda size: None):
    """Public metadata only; preserve declared version expressions verbatim."""
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Archive limit')
    ids, loaders, requires = set(), set(), set()
    versions, requirements = [], set()
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 16384:
            raise ValueError('Archive index limit')
        nested = any(x.filename == 'META-INF/jarjar/metadata.json' for x in members)
        for name, loader in [('fabric.mod.json', 'fabric'), ('META-INF/mods.toml', 'forge'), ('META-INF/neoforge.mods.toml', 'neoforge')]:
            entries = [x for x in members if x.filename == name]
            if not entries:
                continue
            if len(entries) != 1:
                raise ValueError('Ambiguous metadata')
            entry = entries[0]
            if entry.file_size > MAX_METADATA or entry.flag_bits & 1 or entry.is_dir():
                raise ValueError('Metadata limit')
            with archive.open(entry) as stream:
                raw = stream.read(MAX_METADATA + 1)
            if len(raw) > MAX_METADATA:
                raise ValueError('Metadata limit')
            consume(len(raw))
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_json) if loader == 'fabric' else tomllib.loads(raw.decode('utf-8'))
            loaders.add(loader)
            if loader == 'fabric':
                ids.add(_id(data['id']))
                value = data.get('version', '')
                versions.append((data['id'], value if isinstance(value, str) and len(value) <= 256 and type(data.get('schemaVersion')) is int and data['schemaVersion'] == 1 else ''))
                provided = data.get('provides', [])
                if not isinstance(provided, list):
                    raise ValueError('Invalid aliases')
                ids.update(_id(x) for x in provided)
                dependencies = data.get('depends', {})
                if not isinstance(dependencies, dict):
                    raise ValueError('Invalid dependencies')
                for key, value in dependencies.items():
                    if not isinstance(value, str) and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                        raise ValueError('Invalid version expression')
                    expression = json.dumps(value, ensure_ascii=False)
                    requires.add((_id(key), expression))
                    requirements.add((key, expression, 'fabric'))
                nested = nested or bool(data.get('jars'))
            else:
                mods = data.get('mods', [])
                if not isinstance(mods, list) or not mods:
                    raise ValueError('Missing mod declarations')
                ids.update(_id(x['modId']) for x in mods)
                versions.extend((x['modId'], x.get('version', '') if isinstance(x.get('version', ''), str) and len(x.get('version', '')) <= 256 else '') for x in mods)
                dependencies = data.get('dependencies', {})
                if not isinstance(dependencies, dict):
                    raise ValueError('Invalid dependencies')
                for group in dependencies.values():
                    if not isinstance(group, list):
                        raise ValueError('Invalid dependency list')
                    for item in group:
                        if item.get('side', 'BOTH') == 'SERVER':
                            continue
                        if item.get('mandatory') is True or item.get('type') == 'required':
                            value = item.get('versionRange', '')
                            if not isinstance(value, str):
                                raise ValueError('Invalid version range')
                            requires.add((_id(item['modId']), value))
                            requirements.add((item['modId'], value, 'maven'))
    return ModInfo(path.name, tuple(sorted(ids)), tuple(sorted(loaders)), tuple(sorted(requires)), nested, tuple(versions), tuple(sorted(requirements)))


def analyze_crash(text, mods, filename):
    findings = []
    rules = [
        ('OUT_OF_MEMORY', 'Недостаточно памяти или исчерпан лимит JVM', 'java.lang.OutOfMemoryError', 'Проверьте выделенную память и размер сборки. Тип ошибки не устанавливает виновный мод.'),
        ('JAVA_VERSION', 'Возможна несовместимая версия Java', 'UnsupportedClassVersionError', 'Сопоставьте требование Minecraft/загрузчика с выбранной Java.'),
        ('MISSING_CLASS', 'Не удалось загрузить класс', 'NoClassDefFoundError', 'Возможны отсутствующая зависимость или несовместимые версии. По одной строке виновник не установлен.'),
    ]
    lines = text.splitlines()
    for code, title, marker, detail in rules:
        evidence = tuple(redact(line[:800]) for line in lines if marker in line)[:3]
        if evidence:
            findings.append(Finding('warning', code, title, detail, evidence))
    # Only an explicit reported ID can identify a candidate; stack frames cannot.
    candidates = set(re.findall(r"(?im)^\s*(?:Mod ID|Suspected Mods?)\s*:\s*['\"]?([a-zA-Z0-9_.-]+)", text))
    for identifier in sorted(candidates):
        matches = [mod for mod in mods if identifier in mod.ids]
        if len(matches) == 1:
            findings.append(Finding('warning', 'REPORTED_MOD', 'Отчёт указывает на мод: ' + identifier,
                'Это указание crash-report, а не доказанная причина. Проверьте зависимости и воспроизведение; автоматическое отключение не выполняется.',
                (filename + ': ' + identifier,), matches[0].filename))
    if not findings:
        findings.append(Finding('info', 'CRASH_UNKNOWN', 'Причина завершения не установлена',
            'Распознанных признаков недостаточно. Отсутствие совпадений не означает исправность сборки.', (filename,)))
    return findings


def declared_version_checks(mods, loader, complete, overridden=False):
    owners = {}
    for mod in mods:
        for identifier in mod.ids:
            owners.setdefault(identifier, []).append(mod)
    checks = []
    partial = not complete or any(mod.nested for mod in mods)
    runtime = BUILTINS | {'fabric': {'fabricloader'}, 'forge': {'forge'}, 'neoforge': {'neoforge'}}.get(loader, set())
    for mod in mods:
        for identifier, expression, syntax in mod.requirements:
            candidates = owners.get(identifier, [])
            status, actual = 'UNKNOWN', ''
            if identifier in runtime:
                reason = 'Фактическая версия компонента среды здесь не определена.'
            elif len(candidates) != 1:
                reason = 'Нет единственного распознанного поставщика зависимости.'
            else:
                provider = candidates[0]
                values = [v for key, v in provider.versions if key == identifier]
                actual = values[0] if len(values) == 1 else ''
                if overridden:
                    reason = 'Найден файл переопределений Fabric. Его правила здесь не применялись.'
                elif partial:
                    reason = 'Есть вложенные или непрочитанные JAR; полнота поставщиков не установлена.'
                elif len(mod.loaders) != 1 or len(provider.loaders) != 1 or loader not in mod.loaders or loader not in provider.loaders:
                    reason = 'Загрузчик или источник объявления неоднозначен.'
                elif len(values) != 1 or not actual:
                    reason = 'Версия отсутствует или неоднозначна. Версия алиаса не угадывается.'
                else:
                    status = check_version(actual, expression, syntax)
                    reason = {
                        'MATCH': 'Числовая объявленная версия удовлетворяет этому условию. Работа игры не проверена.',
                        'MISMATCH': 'Объявленная версия не удовлетворяет этому условию.',
                        'UNKNOWN': 'Версия или условие вне поддержанного числового подмножества.'}[status]
            checks.append(DependencyCheck(mod.filename, identifier, expression, actual, status, reason))
    return tuple(checks)


def scan_instance(root, loader, cancelled=lambda: False):
    root = Path(root).absolute()
    mods, findings, complete = [], [], True
    with pinned_directory(root):
        if not root.is_dir():
            raise FileNotFoundError('Instance directory is unavailable')
        folder = checked_path(root, 'mods')
        paths = []
        if folder.exists():
            import os
            with os.scandir(folder) as entries:
                for item in itertools.islice(entries, MAX_MODS + 1):
                    paths.append(item.name)
            if len(paths) > MAX_MODS:
                paths = paths[:MAX_MODS]
                complete = False
                findings.append(Finding('warning', 'SCAN_LIMIT', 'Достигнут лимит сканирования', 'Отчёт неполный; отсутствие зависимости не подтверждается.'))
        budget = 0
        def consume(size):
            nonlocal budget
            budget += size
            if budget > 16 * 1024 * 1024:
                raise ValueError('Report limit')
        for name in sorted(paths, key=str.casefold):
            if cancelled():
                return DiagnosticReport(tuple(mods), tuple(findings), False)
            if not name.lower().endswith('.jar'):
                continue
            try:
                path = checked_path(root, 'mods/' + name)
                if not path.is_file():
                    continue
                mod = inspect_mod(path, consume)
                mods.append(mod)
                if not mod.ids:
                    complete = False
                    findings.append(Finding('info', 'UNKNOWN_METADATA', 'Не распознаны метаданные', 'JAR не исполнялся. Он может использовать неподдерживаемый формат.', (name,), name))
                if mod.loaders and loader in {'fabric', 'forge', 'neoforge', 'vanilla'} and loader not in mod.loaders:
                    findings.append(Finding('warning', 'LOADER_MISMATCH', 'Проверьте загрузчик мода', 'Заявлены: ' + ', '.join(mod.loaders) + '; сборка: ' + loader, (name,), name))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError) as error:
                complete = False
                findings.append(Finding('warning', 'UNREADABLE_MOD', 'Не удалось проверить JAR', 'Файл повреждён, недоступен или метаданные не поддерживаются. Код не запускался.', (name, type(error).__name__), name))
                if budget > 16 * 1024 * 1024:
                    findings.append(Finding('warning', 'SCAN_LIMIT', 'Достигнут лимит метаданных', 'Остальные JAR не проверены.'))
                    break
        owners = {}
        for mod in mods:
            for identifier in mod.ids:
                owners.setdefault(identifier, []).append(mod.filename)
        for identifier, names in sorted(owners.items()):
            if len(names) > 1:
                findings.append(Finding('error', 'DUPLICATE_ID', 'Повторяется ID мода: ' + identifier, 'Несколько включённых JAR заявляют одну идентичность.', tuple(names)))
        nested = any(mod.nested for mod in mods)
        for mod in mods:
            for identifier, expression in mod.requires:
                implicit = {'fabric': {'fabricloader'}, 'forge': {'forge'}, 'neoforge': {'neoforge'}}.get(loader, set())
                if identifier in BUILTINS | implicit or identifier in owners:
                    continue
                code = 'MISSING_DEPENDENCY' if complete and not nested and loader in {'fabric', 'forge', 'neoforge', 'vanilla'} else 'UNRESOLVED_DEPENDENCY'
                findings.append(Finding('warning', code, 'Не найдена зависимость: ' + identifier,
                    'Требует ' + mod.filename + '; условие: ' + expression + ('. Вложенные/непрочитанные JAR не позволяют подтвердить отсутствие.' if code == 'UNRESOLVED_DEPENDENCY' else '. Не найдена среди распознанных включённых модов.'),
                    (mod.filename, identifier, expression), mod.filename))
        overridden = loader == 'fabric' and checked_path(root, 'config/fabric_loader_dependencies.json').exists()
        checks = declared_version_checks(mods, loader, complete, overridden)
        for check in checks:
            if check.status == 'MISMATCH':
                findings.append(Finding('warning', 'VERSION_MISMATCH', 'Не подходит версия зависимости: ' + check.dependency,
                    check.reason + ' Требует: ' + check.filename,
                    ('Условие: '+check.expression, 'Объявлено: '+check.actual), check.filename))
        unknown = sum(check.status == 'UNKNOWN' for check in checks)
        if unknown:
            findings.append(Finding('info', 'VERSION_UNKNOWN', f'Не проверены условия версий: {unknown}',
                'Смотрите вкладку зависимостей. Неизвестный формат, среда, вложенные JAR или неоднозначные ID не считаются соответствием.'))
        findings.append(Finding('info', 'LIMITATIONS', 'Границы проверки', 'Проверены объявления ID и обязательных зависимостей; поддержано числовое подмножество условий Fabric и Maven. Вложенные JAR, нестандартные версии, bytecode, malware safety и успешный запуск не проверены. Снимок не атомарный: после изменения модов повторите сканирование.'))
        crash_file = ''
        crash_dir = checked_path(root, 'crash-reports')
        if crash_dir.is_dir():
            candidates = []
            for path in itertools.islice(crash_dir.iterdir(), 101):
                if len(candidates) >= 100:
                    break
                try:
                    safe = checked_path(root, 'crash-reports/' + path.name)
                    if safe.suffix.lower() == '.txt' and safe.is_file():
                        candidates.append((safe.stat().st_mtime_ns, safe.name, safe))
                except (OSError, ValueError):
                    complete = False
            if candidates:
                _, crash_file, path = max(candidates)
                try:
                    with path.open('rb') as stream:
                        size = stream.seek(0, 2)
                        stream.seek(max(0, size - MAX_LOG))
                        text = stream.read(MAX_LOG).decode('utf-8', errors='replace')
                    findings.extend(analyze_crash(text, mods, crash_file))
                    findings.append(Finding('info', 'CRASH_SCOPE', 'Источник отчёта о сбое',
                        'Последний по времени изменения среди первых 100 записей. Это не обязательно последний запуск. ' + ('Прочитан только конец большого файла.' if size > MAX_LOG else 'Прочитан целиком.'), (crash_file,)))
                except OSError:
                    complete = False
                    findings.append(Finding('warning', 'CRASH_UNREADABLE', 'Crash-report недоступен', 'Повторите проверку после завершения записи файла.'))
        if not crash_file:
            findings.append(Finding('info', 'NO_CRASH_REPORT', 'Crash-report пока не найден', 'Exit code и отсутствие отчёта не устанавливают причину завершения.'))
    return DiagnosticReport(tuple(mods), tuple(findings), complete, crash_file, checks)
