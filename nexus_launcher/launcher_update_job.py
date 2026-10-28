"""Windows update helper, run from a copy of the currently trusted launcher.

Only the executable is replaced; account/config/instances are never migrated here.
The durable backup is kept for manual recovery, including after a power loss.
"""

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from nexus_launcher.process_utils import hidden_process_kwargs
from nexus_launcher.resource_limits import copy_limited, ensure_space, read_limited
from nexus_launcher.safe_paths import checked_path, pinned_directory, relative_parts, replace_file
from nexus_launcher.update_state import remember_release, update_lock
from nexus_launcher.user_instances import atomic_json


def require_exe_only_layout(executable: Path):
    """This legacy helper cannot replace a coherent PyInstaller onedir package.

    Reject any _internal entry (including broken links) before preparing a job.
    This is a refusal guard for the shipped layout, not a package updater.
    """
    marker = Path(executable).absolute().parent / "_internal"
    try:
        marker.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise RuntimeError("Не удалось проверить формат пакета обновления") from None
    raise RuntimeError("EXE-only обновление запрещено для onedir; требуется полный пакет")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_job(path):
    with path.open("rb") as stream:
        result = json.loads(read_limited(stream, 128 * 1024))
    if not isinstance(result, dict):
        raise ValueError("Некорректный журнал обновления")
    return result


def resume_interrupted_update(executable):
    """Start the retained old helper before loading UI/workers; caller must exit."""
    from nexus_launcher.platform_support import app_data_dir

    root = app_data_dir() / "updates"
    if not root.exists():
        return False
    checked_path(root, "pending")
    with update_lock(root):
        operations = [entry for entry in root.iterdir() if entry.name.startswith("release-")]
        if len(operations) > 100:
            raise ValueError("Слишком много незавершённых операций; требуется ручная проверка")
        for entry in operations:
            operation = checked_path(root, entry.name)
            path = checked_path(operation, "job.json")
            if not path.is_file():
                continue
            job = read_job(path)
            if job.get("phase") not in {"prepared", "committed"}:
                continue
            if Path(job["target"]).absolute() != executable.absolute():
                continue
            helper = checked_path(operation, "helper.exe")
            if digest(helper) != job["old_sha256"]:
                raise ValueError("Recovery helper повреждён; используйте проверенный установщик")
            job["parent_pid"] = os.getpid()
            atomic_json(path, job)
            environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("_PYI_")}
            subprocess.Popen([str(helper), "--apply-update", str(operation)], env=environment,
                             **hidden_process_kwargs())
            return True
    return False


def durable_copy(source, target):
    with pinned_directory(target.parent), pinned_directory(source.parent):
        checked_path(source.parent, source.name)
        with source.open("rb") as src, target.open("xb") as dst:
            copy_limited(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
    if digest(source) != digest(target):
        raise ValueError("Не удалось проверить резервную копию EXE")


def start_update(update_root: Path, downloaded: Path, executable: Path, parent_pid: int):
    require_exe_only_layout(executable)
    with update_lock(update_root):
        return _start_update(update_root, downloaded, executable, parent_pid)


def _start_update(update_root: Path, downloaded: Path, executable: Path, parent_pid: int):
    require_exe_only_layout(executable)
    relative = downloaded.absolute().relative_to(update_root.absolute()).as_posix()
    downloaded = checked_path(update_root, relative)
    if len(relative_parts(relative)) != 2 or not downloaded.parent.name.startswith("release-"):
        raise ValueError("Обновление не принадлежит операции загрузки")
    operation = downloaded.parent
    from nexus_launcher.self_update import LauncherRelease

    envelope = read_job(checked_path(operation, "manifest.json"))
    payload = envelope["release"]
    release = LauncherRelease(
        payload["version"], payload["url"], payload["sha256"], size=payload["size"], envelope=envelope
    )
    release.validate()
    release.authenticated()
    if downloaded.stat().st_size != release.size or digest(downloaded) != release.sha256:
        raise ValueError("Файл обновления изменился после скачивания")
    executable = executable.absolute()
    checked_path(executable.parent, executable.name)
    ensure_space(executable.parent, executable.stat().st_size + release.size)
    helper = checked_path(operation, "helper.exe")
    durable_copy(executable, helper)
    atomic_json(
        checked_path(operation, "job.json"),
        {
            "target": str(executable),
            "source": downloaded.name,
            "old_sha256": digest(executable),
            "parent_pid": parent_pid,
            "phase": "pending",
            "existed_before": True,
        },
    )
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("_PYI_")}
    return subprocess.Popen([str(helper), "--apply-update", str(operation)], env=environment,
                            **hidden_process_kwargs())


def wait_parent(pid: int, seconds=120):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # Already gone.
            return
        raise OSError("Не удалось дождаться завершения лаунчера")
    try:
        if kernel.WaitForSingleObject(handle, seconds * 1000) != 0:
            raise TimeoutError("Лаунчер не завершился; обновление не применено")
    finally:
        kernel.CloseHandle(handle)


def apply_update(operation: Path, launch=None, wait=wait_parent):
    with update_lock(operation.absolute().parent), pinned_directory(operation):
        job = read_job(checked_path(operation, "job.json"))
        target = Path(job["target"])
        if not target.is_absolute() or target.suffix.lower() != ".exe":
            raise ValueError("Некорректный целевой EXE")
        require_exe_only_layout(target)
        with pinned_directory(target.parent):
            return _apply_update(operation, launch, wait)


def _apply_update(operation: Path, launch=None, wait=wait_parent):
    from nexus_launcher.self_update import LauncherRelease

    operation = operation.absolute()
    job_path = checked_path(operation, "job.json")
    job = read_job(job_path)
    require_exe_only_layout(Path(job["target"]))
    if job.get("phase") != "pending":
        wait(int(job["parent_pid"]))
        recover_update(operation)
        if launch is None:
            environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("_PYI_")}
            environment["NEXUS_DISABLE_SELF_UPDATE"] = "1"
            subprocess.Popen([job["target"]], env=environment, **hidden_process_kwargs())
        return
    envelope = read_job(checked_path(operation, "manifest.json"))
    payload = envelope["release"]
    release = LauncherRelease(
        payload["version"], payload["url"], payload["sha256"], size=payload["size"], envelope=envelope
    )
    release.validate()
    release.authenticated()
    remember_release(operation.parent, envelope)
    source = checked_path(operation, job["source"])
    target = Path(job["target"])
    if not target.is_absolute() or target.suffix.lower() != ".exe":
        raise ValueError("Некорректный целевой EXE")
    target = checked_path(target.parent, target.name)
    backup = checked_path(operation, "original.exe")
    # A sibling stage makes the final replacement a same-volume rename.
    stage = checked_path(target.parent, f".nexus-{operation.name}.exe")
    if source.stat().st_size != release.size or digest(source) != release.sha256:
        raise ValueError("Повреждённое обновление")
    if stage.exists():
        raise ValueError("Staging уже существует; чужой файл не будет удалён")
    wait(int(job["parent_pid"]))
    if digest(target) != job["old_sha256"]:
        raise ValueError("Исходный EXE уже изменён; обновление отменено")
    ensure_space(target.parent, release.size)
    durable_copy(target, backup)
    job["phase"] = "prepared"
    atomic_json(job_path, job)
    try:
        durable_copy(source, stage)
        checked_path(target.parent, target.name)
        checked_path(target.parent, stage.name)
        replace_file(stage, target, expected_sha256=release.sha256)
        job["phase"] = "committed"
        atomic_json(job_path, job)
        job["launched_pid"] = (launch or launch_and_confirm)(target, operation)
        job["phase"] = "complete"
        atomic_json(job_path, job)
        checked_path(operation, source.name).unlink()
    except Exception:
        if digest(backup) != job["old_sha256"]:
            raise ValueError("Backup повреждён; автоматическое восстановление остановлено") from None
        # Copy backup through a fresh same-volume stage, never remove target first.
        checked_path(target.parent, stage.name).unlink(missing_ok=True)
        durable_copy(backup, stage)
        checked_path(target.parent, target.name)
        replace_file(stage, target, expected_sha256=job["old_sha256"])
        job["phase"] = "rolled_back"
        atomic_json(job_path, job)
        raise
    finally:
        checked_path(target.parent, stage.name).unlink(missing_ok=True)


def recover_update(operation: Path):
    """Restore only a prepared backup; pending means original was untouched."""
    job_path = checked_path(operation, "job.json")
    job = read_job(job_path)
    if job.get("phase") in {"pending", "complete", "rolled_back"}:
        return
    if job.get("phase") not in {"prepared", "committed"} or job.get("existed_before") is not True:
        raise ValueError("Неизвестная фаза восстановления")
    target = Path(job["target"])
    if not target.is_absolute() or target.suffix.lower() != ".exe":
        raise ValueError("Неверный EXE восстановления")
    target = checked_path(target.parent, target.name)
    if target.exists() and digest(target) == job["old_sha256"]:
        job["phase"] = "rolled_back"
        atomic_json(job_path, job)
        return
    backup = checked_path(operation, "original.exe")
    if digest(backup) != job["old_sha256"]:
        raise ValueError("Backup повреждён; исходный EXE не изменён")
    envelope = read_job(checked_path(operation, "manifest.json"))
    if target.exists() and digest(target) not in {job["old_sha256"], envelope["release"]["sha256"]}:
        raise ValueError("EXE изменён другой операцией; восстановление остановлено")
    if not target.exists() or digest(target) != job["old_sha256"]:
        fd, name = tempfile.mkstemp(prefix="nexus-recovery-", suffix=".exe", dir=target.parent)
        stage = Path(name)
        try:
            with backup.open("rb") as src, os.fdopen(fd, "wb") as dst:
                copy_limited(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            if digest(stage) != job["old_sha256"]:
                raise ValueError("Не удалось проверить восстановленный EXE")
            checked_path(target.parent, target.name)
            checked_path(target.parent, stage.name)
            replace_file(stage, target, expected_sha256=job["old_sha256"])
        finally:
            checked_path(target.parent, stage.name).unlink(missing_ok=True)
    job["phase"] = "rolled_back"
    atomic_json(job_path, job)


def launch_and_confirm(target: Path, operation: Path):
    marker = checked_path(operation, "healthy")
    marker.unlink(missing_ok=True)
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("_PYI_")}
    environment["NEXUS_DISABLE_SELF_UPDATE"] = "1"
    process = subprocess.Popen([str(target), "--update-health", str(marker)], env=environment,
                               **hidden_process_kwargs())
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if marker.exists() and marker.read_text() == "ready":
                return process.pid
            if process.poll() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError("Новая версия не подтвердила запуск; возвращена предыдущая")
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        raise
