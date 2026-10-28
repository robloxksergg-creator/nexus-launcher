"""Startup presentation contract; native package execution remains adapter-owned.

No network, process creation or application import happens in this module.
Only a reviewed backend may declare a package installed/healthy. In particular,
an uncertain child process must never enable another launch or update attempt.
"""
from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class View:
    phase: Phase
    title: str
    detail: str
    percent: int | None = None
    retry: bool = False
    offline: bool = False


class UpdateFailure(Exception):
    """Public category only; transport messages/URLs never reach the UI."""


class LaunchUncertain(UpdateFailure):
    pass


class StartupFlow:
    """Single worker owner. UI must serialize calls and render returned Views.

    Backend contract: check() returns None or a verified release; download()
    returns a bounded private archive; stage() verifies/extracts the full package;
    activate() returns COMPLETE, ROLLED_BACK or UNKNOWN using portable_bootstrap;
    launch_current() must return True only after authenticated child readiness.
    can_launch_current() must verify the installed package and absence of any
    unresolved transition. No exception text is exposed, even to the logger.
    """

    def __init__(self, backend, emit):
        self.backend, self.emit = backend, emit
        self.view = View(Phase.IDLE, "NEXUS", "Подготовка к запуску")
        self._busy = False

    def _show(self, phase, title, detail, **kwargs):
        self.view = View(phase, title, detail, **kwargs)
        self.emit(self.view)

    def _blocked(self):
        self._show(Phase.BLOCKED, "Запуск требует проверки",
                   "Не удалось подтвердить состояние лаунчера. Закройте его перед повторным запуском.")

    def _offline_available(self):
        try:
            return self.backend.can_launch_current() is True
        except Exception:
            return False

    def _progress(self, done, total):
        if self.view.phase != Phase.DOWNLOADING:
            return
        if type(done) is not int or type(total) is not int or not 0 <= done <= total or total <= 0:
            return
        self._show(Phase.DOWNLOADING, "Загружаем обновление",
                   "Лаунчер откроется после проверки файлов", percent=min(99, done * 100 // total))

    def run(self, *, offline=False):
        if self._busy or self.view.phase in {Phase.READY, Phase.BLOCKED}:
            return False
        if offline and not self.view.offline:
            return False
        self._busy = True
        # After a possible process spawn, every unclassified exception is
        # ambiguous. Do not offer retry/offline and accidentally spawn twice.
        may_have_started = False
        try:
            if offline:
                if not self._offline_available():
                    raise UpdateFailure()
            else:
                self._show(Phase.CHECKING, "Проверяем обновления", "Это займёт немного времени")
                release = self.backend.check()
                if release is not None:
                    self._show(Phase.DOWNLOADING, "Загружаем обновление",
                               "Лаунчер откроется после проверки файлов")
                    archive = self.backend.download(release, self._progress)
                    self._show(Phase.VERIFYING, "Проверяем файлы", "Проверяем подпись и целостность пакета")
                    candidate = self.backend.stage(archive, release)
                    self._show(Phase.STARTING, "Запускаем новую версию", "Ожидаем готовности лаунчера")
                    may_have_started = True
                    result = self.backend.activate(candidate)
                    if result == "COMPLETE":
                        self._show(Phase.READY, "NEXUS готов", "Обновление установлено. Лаунчер запущен.")
                        return True
                    if result != "ROLLED_BACK":
                        self._blocked()
                        return False
                    # A rollback is safe only when portable_bootstrap confirmed
                    # child exit AND restored the authenticated previous slot.
                    may_have_started = False
                    raise UpdateFailure()
            self._show(Phase.STARTING, "Запускаем NEXUS", "Ожидаем готовности лаунчера")
            may_have_started = True
            if self.backend.launch_current() is not True:
                raise LaunchUncertain()
            self._show(Phase.READY, "NEXUS готов", "Лаунчер запущен")
            return True
        except LaunchUncertain:
            self._blocked()
        except Exception:
            if may_have_started:
                self._blocked()
            else:
                self._show(Phase.ERROR, "Не удалось подготовить запуск",
                           "Повторите проверку или запустите установленную версию, если она доступна.",
                           retry=True, offline=self._offline_available())
        finally:
            self._busy = False
        return False
