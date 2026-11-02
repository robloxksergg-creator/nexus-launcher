"""Read-only, point-in-time preparation checks; never install, admit or predict FPS."""
from dataclasses import dataclass
import ctypes
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
from urllib.parse import urlsplit

from nexus_launcher.platform_support import java_major
from nexus_launcher.runtime_settings import required_java

MIB = 1024 * 1024

@dataclass(frozen=True)
class Check:
    key: str
    title: str
    state: str
    detail: str

@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]
    measured_at: float
    cancelled: bool = False


def read_memory():
    """Return total and available bytes, or None for fields the OS did not report."""
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
        value = Memory(); value.length = ctypes.sizeof(value)
        fn = ctypes.windll.kernel32.GlobalMemoryStatusEx
        fn.argtypes = [ctypes.POINTER(Memory)]; fn.restype = ctypes.c_int
        if not fn(ctypes.byref(value)): raise OSError('Memory information unavailable')
        return value.total, value.available
    if platform.system() == 'Linux':
        fields = {}
        with Path('/proc/meminfo').open(encoding='ascii') as stream:
            for line in stream:
                key, _, raw = line.partition(':')
                if key in {'MemTotal', 'MemAvailable'}:
                    parts = raw.split()
                    if len(parts) == 2 and parts[1] == 'kB': fields[key] = int(parts[0]) * 1024
        return fields.get('MemTotal'), fields.get('MemAvailable')
    if platform.system() == 'Darwin':
        result = subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=2, check=False)
        return (int(result.stdout.strip()), None) if result.returncode == 0 else (None, None)
    return None, None


def free_disk(root):
    # Read the existing containing filesystem, without creating or migrating an instance.
    root = Path(root).absolute()
    while not root.exists():
        if root.parent == root: raise OSError('No containing filesystem')
        root = root.parent
    return shutil.disk_usage(root).free


def inspect_java(preferred, major):
    """Bounded explicit/PATH/JAVA_HOME search, not proof of absence on the machine."""
    candidates = [preferred] if preferred else [shutil.which('java'),
        str(Path(os.environ['JAVA_HOME']) / 'bin' / ('java.exe' if os.name == 'nt' else 'java')) if os.environ.get('JAVA_HOME') else None]
    found = []
    for raw in dict.fromkeys(x for x in candidates if x):
        path = Path(raw).expanduser()
        if path.name.lower() == 'javaw.exe': path = path.with_name('java.exe')
        if path.name.lower() not in {'java', 'java.exe'} or not path.is_absolute() or not path.is_file(): continue
        value = java_major(path)  # Existing bounded -version probe; never game launch.
        if value == major: return 'ok', f'Java {value} обнаружена. Проверена версия, не запуск сборки.'
        if value is not None: found.append(value)
    if found: return 'warning', f'Найдена Java {", ".join(map(str, found))}; для этой версии Minecraft требуется Java {major}.'
    return 'unknown', f'Java {major} не подтверждена в выбранном пути, PATH и JAVA_HOME. Это не поиск по всему диску.'


def connection_time(address):
    """One DNS+TCP connect to the selected catalog endpoint, not ICMP/game ping."""
    if not isinstance(address, str) or not 1 <= len(address) <= 300 or any(c.isspace() for c in address): raise ValueError('Invalid endpoint')
    url = urlsplit('//' + address)
    if url.username or url.password or url.path or url.query or url.fragment or not url.hostname: raise ValueError('Invalid endpoint')
    host, port = url.hostname, url.port if url.port is not None else 25565
    if not 1 <= port <= 65535 or len(host.encode('idna')) > 253: raise ValueError('Invalid endpoint')
    started = time.monotonic()
    with socket.create_connection((host, port), timeout=3): pass
    return max(0, (time.monotonic() - started) * 1000)


def collect(server, storage_root, *, java_path='', allocated_mb=4096, cancelled=lambda: False):
    checks = []
    def add(key, title, state, detail): checks.append(Check(key, title, state, detail))
    def stopped(): return Report(tuple(checks), time.time(), True) if cancelled() else None
    if (result := stopped()): return result
    try:
        total, available = read_memory()
        total = f'{total / MIB / 1024:.1f} ГБ' if total else 'неизвестно'
        requested = allocated_mb if type(allocated_mb) is int and 256 <= allocated_mb <= 1048576 else None
        recommended = getattr(server, 'recommended_memory_mb', None)
        recommended = recommended if type(recommended) is int and 256 <= recommended <= 1048576 else None
        state = 'info' if available is not None else 'unknown'
        if available is not None and requested and available < requested * MIB: state = 'warning'
        if requested and recommended and requested < recommended: state = 'warning'
        add('ram', 'Оперативная память', state,
            f'Всего: {total}. Доступно сейчас: '+(f'{available / MIB / 1024:.1f} ГБ.' if available is not None else 'неизвестно.')+
            (f' Для Java выбрано {requested} МБ.' if requested else ' Настройка памяти не подтверждена.')+
            (f' Рекомендация профиля: {recommended} МБ.' if recommended else '')+
            ' Память не резервируется; системе и другим приложениям тоже нужна RAM.')
    except (OSError, ValueError, AttributeError): add('ram', 'Оперативная память', 'unknown', 'ОС не предоставила достоверные сведения о памяти.')
    if (result := stopped()): return result
    try:
        free = free_disk(storage_root)
        add('disk', 'Место для установки', 'unknown', f'Свободно {free / (1024**3):.1f} ГБ на диске папки данных. Полный размер установки не задан; достаточность места не подтверждена.')
    except OSError: add('disk', 'Место для установки', 'unknown', 'Не удалось прочитать свободное место на диске папки данных.')
    if (result := stopped()): return result
    try:
        major = required_java(server.minecraft_version, getattr(server, 'java_major', 0))
        state, detail = inspect_java(java_path, major)
        add('java', 'Java', state, detail)
    except (OSError, ValueError, subprocess.SubprocessError): add('java', 'Java', 'unknown', 'Проверка Java не завершена. Настройки и файлы не изменены.')
    if (result := stopped()): return result
    try:
        delay = connection_time(server.address)
        add('network', 'Связь с сервером', 'ok', f'DNS + TCP: {delay:.0f} мс. Порт доступен; это не игровой пинг и не подтверждение готовности Minecraft-сервера.')
    except (OSError, ValueError): add('network', 'Связь с сервером', 'unknown', 'TCP-соединение не установлено. Возможны проблемы сети, DNS, фильтрация или недоступность порта; причина не установлена.')
    if (result := stopped()): return result
    add('fps', 'FPS и скорость загрузки', 'unknown', 'Не измерялись. FPS требует установленной сборки и запуска тестовой сцены. Скорость скачивания этим тестом не проверяется.')
    return Report(tuple(checks), time.time())
