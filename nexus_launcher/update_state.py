"""Crash-released cross-process guard and authenticated anti-rollback watermark."""

import json
import os
from contextlib import contextmanager
from functools import wraps

from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.signed_release import verify_signature


@contextmanager
def update_lock(root):
    path = checked_path(root, "update.lock")
    with pinned_directory(root, create=True), path.open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("Другая операция обновления уже выполняется") from error
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def serialized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with update_lock(self.update_dir):
            return method(self, *args, **kwargs)

    return guarded


def remember_release(root, envelope):
    """Must be called under update_lock; never trust unsigned local version strings."""
    from nexus_launcher.self_update import CURRENT_VERSION, version_tuple
    from nexus_launcher.user_instances import atomic_json

    candidate = verify_signature(envelope)
    proposed = version_tuple(candidate["version"])
    if proposed <= version_tuple(CURRENT_VERSION):
        raise ValueError("Откат установленной версии запрещён")
    path = checked_path(root, "highest-release.json")
    if path.exists():
        if path.stat().st_size > 128 * 1024:
            raise ValueError("Повреждена история обновлений")
        previous = verify_signature(json.loads(path.read_text(encoding="utf-8")))
        highest = version_tuple(previous["version"])
        if proposed < highest or (proposed == highest and candidate["sha256"] != previous["sha256"]):
            raise ValueError("Откат или подмена ранее проверенного release запрещены")
        if proposed == highest:
            return
    atomic_json(path, envelope)
