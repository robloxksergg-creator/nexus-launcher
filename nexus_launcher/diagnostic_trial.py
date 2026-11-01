"""Confirmed trial copies for personal instances. Never edit the source pack.

This is ordinary launcher file management, not OS isolation or crash attribution.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import uuid

from nexus_launcher.safe_paths import checked_path, pinned_directory, atomic_copy, remove_owned_tree
from nexus_launcher.resource_limits import ensure_space, MAX_FILE_BYTES, MAX_EXTRACTED_BYTES
from nexus_launcher.user_instances import InstanceService, UserInstance, INSTANCE_DIRS, atomic_json, safe_filename, utc_now

DIRECTORIES = ('mods', 'disabled_mods', 'config', 'resourcepacks', 'shaderpacks', 'saves', 'defaultconfigs', 'kubejs', 'scripts', 'datapacks')
SINGLES = ('options.txt', 'servers.dat')
MAX_FILES = 20_000


class TrialError(ValueError):
    pass


@contextmanager
def launcher_idle(owner):
    """Exclude this launcher's launch worker; do not claim external process control."""
    lock = getattr(owner, '_launch_lock', None)
    if lock is None or not lock.acquire(blocking=False):
        raise TrialError('Закройте Minecraft и дождитесь завершения запуска в этом лаунчере.')
    try:
        process = getattr(owner, 'game_process', None)
        if process is not None and process.poll() is None:
            raise TrialError('Закройте Minecraft перед созданием диагностической копии.')
        yield
    finally:
        lock.release()


@dataclass(frozen=True)
class TrialPlan:
    source_id: str
    source_root: str
    manifest: bytes
    filename: str
    files: tuple[tuple[str, int, str], ...]
    trial_id: str
    trial_name: str

    @property
    def total_bytes(self):
        return sum(size for _, size, _ in self.files)


@dataclass(frozen=True)
class TrialResult:
    source_id: str
    trial_id: str
    trial_name: str


def _cancel(cancelled):
    if cancelled():
        raise TrialError('Операция отменена до публикации копии.')


def _hash(path, cancelled):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            _cancel(cancelled)
            size += len(block)
            if size > MAX_FILE_BYTES:
                raise TrialError('Файл превышает лимит копирования 1 ГБ.')
            digest.update(block)
    return size, digest.hexdigest()


def _snapshot(root, cancelled):
    manifest_path = checked_path(root, 'instance.json')
    with manifest_path.open('rb') as stream:
        manifest = stream.read(1024 * 1024 + 1)
    if len(manifest) > 1024 * 1024:
        raise TrialError('Слишком большие метаданные сборки.')
    files, total = [], 0
    def walk_error(error):
        raise error
    def add(relative):
        nonlocal total
        _cancel(cancelled)
        path = checked_path(root, relative)
        if not path.is_file():
            raise TrialError('Объект сборки не является обычным файлом.')
        size, digest = _hash(path, cancelled)
        total += size
        files.append((relative, size, digest))
        if len(files) > MAX_FILES or total > MAX_EXTRACTED_BYTES:
            raise TrialError('Диагностическая копия ограничена 20 000 файлов и 4 ГБ.')
    for directory in DIRECTORIES:
        base = checked_path(root, directory)
        if not base.exists():
            continue
        if not base.is_dir():
            raise TrialError('Игровая папка заменена файлом.')
        for folder, dirs, names in os.walk(base, followlinks=False, onerror=walk_error):
            _cancel(cancelled)
            for name in dirs:
                checked_path(root, (Path(folder)/name).relative_to(root).as_posix())
            for name in sorted(names):
                add((Path(folder)/name).relative_to(root).as_posix())
    for name in SINGLES:
        if checked_path(root, name).exists():
            add(name)
    return manifest, tuple(sorted(files))


class DiagnosticTrials:
    def __init__(self, instances: InstanceService, source_id, idle_guard):
        self.instances, self.source_id, self.idle_guard = instances, source_id, idle_guard

    def prepare(self, filename, cancelled=lambda: False):
        filename = safe_filename(filename)
        if not filename.lower().endswith('.jar'):
            raise TrialError('Выберите JAR из включённых модов.')
        with self.idle_guard():
            root = self.instances.path_for(self.source_id)
            with pinned_directory(root):
                manifest, files = _snapshot(root, cancelled)
                original = UserInstance.from_dict(json.loads(manifest))
                if original.id != self.source_id or original.instance_type != 'custom':
                    raise TrialError('Доступно только для личной сборки.')
                names = {name.casefold() for name, _, _ in files}
                if ('mods/'+filename).casefold() not in names:
                    raise TrialError('Выбранный мод больше не находится во включённой папке.')
                if ('disabled_mods/'+filename).casefold() in names:
                    raise TrialError('В disabled_mods уже есть файл с таким именем. Конфликт не заменяется.')
                if len(names) != len(files):
                    raise TrialError('Имена файлов различаются только регистром.')
                trial_id = str(uuid.uuid4())
                return TrialPlan(self.source_id, str(root), manifest, filename, files, trial_id, original.name[:40]+' — диагностика')

    def apply(self, plan: TrialPlan, cancelled=lambda: False):
        if plan.source_id != self.source_id or str(uuid.UUID(plan.trial_id)) != plan.trial_id:
            raise TrialError('План относится к другой сборке.')
        safe_filename(plan.filename)
        with self.idle_guard():
            root = self.instances.path_for(self.source_id)
            if str(root) != plan.source_root:
                raise TrialError('Папка сборки изменилась. Подготовьте план заново.')
            with pinned_directory(root), pinned_directory(self.instances.root):
                if _snapshot(root, cancelled) != (plan.manifest, plan.files):
                    raise TrialError('Сборка изменилась после просмотра плана. Подготовьте план заново.')
                original = UserInstance.from_dict(json.loads(plan.manifest))
                if original.id != self.source_id or original.instance_type != 'custom':
                    raise TrialError('Доступно только для личной сборки.')
                source_names = {name for name, _, _ in plan.files}
                if 'mods/'+plan.filename not in source_names or 'disabled_mods/'+plan.filename in source_names:
                    raise TrialError('Изменение не соответствует выбранному моду.')
                ensure_space(self.instances.root, plan.total_bytes + 4*1024*1024)
                stage_parent = checked_path(self.instances.root, '.diagnostic-staging')
                target = checked_path(self.instances.root, plan.trial_id)
                if target.exists():
                    raise TrialError('Папка новой копии уже занята.')
                with pinned_directory(stage_parent, create=True):
                    stage = checked_path(stage_parent, plan.trial_id)
                    if stage.exists():
                        raise TrialError('Временная папка уже занята.')
                    stage.mkdir()
                    try:
                        for name, _, digest in plan.files:
                            _cancel(cancelled)
                            destination = 'disabled_mods/'+plan.filename if name == 'mods/'+plan.filename else name
                            output = checked_path(stage, destination)
                            output.parent.mkdir(parents=True, exist_ok=True)
                            atomic_copy(checked_path(root, name), output, expected_sha256=digest)
                        if _snapshot(root, cancelled) != (plan.manifest, plan.files):
                            raise TrialError('Исходная сборка изменилась во время копирования. Копия не опубликована.')
                        for directory in INSTANCE_DIRS:
                            checked_path(stage, directory).mkdir(parents=True, exist_ok=True)
                        clone = replace(original, id=plan.trial_id, name=plan.trial_name,
                            install_path='', state='ready', created_at=utc_now(), updated_at=utc_now(),
                            installed_mods=[replace(mod, enabled=False) if mod.filename==plan.filename else replace(mod) for mod in original.installed_mods],
                            last_launch='', last_exit_code=None, last_game_duration=None,
                            last_test_launch='', last_test_exit_code=None, last_test_duration=None)
                        # This staging owner cannot discover or modify the original.
                        InstanceService(stage_parent).save(clone)
                        atomic_json(checked_path(stage, '.nexus/diagnostic-trial.json'), {
                            'schema':1, 'source_id':plan.source_id, 'disabled_mod':plan.filename,
                            'source_manifest_sha256':hashlib.sha256(plan.manifest).hexdigest(),
                            'scope':'Trial only; no successful game launch or repair is claimed'})
                        _cancel(cancelled)
                        result = TrialResult(plan.source_id, plan.trial_id, plan.trial_name)
                        # The UUID folder becomes visible only after all files verify.
                        os.rename(stage, target)
                        return result
                    except BaseException:
                        if stage.exists():
                            remove_owned_tree(stage_parent, plan.trial_id)
                        raise
