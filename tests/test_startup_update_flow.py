"""Offline synthetic backend tests. Never launches an executable or uses HTTP."""
import pytest

from nexus_launcher.startup_update_flow import Phase, StartupFlow


class Backend:
    def __init__(self, *, release=True, failure=None, result="COMPLETE", installed=True):
        self.release, self.failure, self.result, self.installed = release, failure, result, installed
        self.calls = []

    def call(self, name):
        self.calls.append(name)
        if self.failure == name:
            raise RuntimeError("must-never-render: password=secret-token")

    def check(self):
        self.call("check")
        return object() if self.release else None

    def download(self, release, progress):
        self.call("download")
        progress(1, 2)
        progress(2, 2)
        return object()

    def stage(self, archive, release):
        self.call("stage")
        return object()

    def activate(self, candidate):
        self.call("activate")
        return self.result

    def launch_current(self):
        self.call("launch")
        return True

    def can_launch_current(self):
        self.call("installed")
        return self.installed


def make(**kwargs):
    backend, views = Backend(**kwargs), []
    return StartupFlow(backend, views.append), backend, views


@pytest.mark.parametrize("error,code", [
    (PermissionError("private/path token=secret"), "VERIFY_IO"),
    (ValueError("private/path token=secret"), "VERIFY_REJECTED"),
    (RuntimeError("private/path token=secret"), "VERIFY_FAILED"),
])
def test_verification_failure_has_safe_category_and_never_activates(error, code):
    flow, backend, _ = make()

    def refuse(archive, release):
        raise error

    backend.stage = refuse
    assert not flow.run()
    assert flow.view.phase == Phase.ERROR
    assert code in flow.view.detail
    assert "private" not in flow.view.detail and "secret" not in flow.view.detail
    assert flow.view.retry and flow.view.offline
    assert "activate" not in backend.calls and "launch" not in backend.calls


def test_update_waits_for_authenticated_ready_before_success():
    flow, backend, views = make()
    assert flow.run() is True
    assert backend.calls == ["check", "download", "stage", "activate"]
    assert [v.phase for v in views] == [Phase.CHECKING, Phase.DOWNLOADING, Phase.DOWNLOADING,
                                       Phase.DOWNLOADING, Phase.VERIFYING, Phase.STARTING, Phase.READY]
    assert [v.percent for v in views if v.percent is not None] == [50, 99]
    assert not flow.run()
    assert backend.calls.count("activate") == 1


def test_current_version_starts_when_no_update_available():
    flow, backend, _ = make(release=False)
    assert flow.run()
    assert backend.calls == ["check", "launch"]


@pytest.mark.parametrize("failure", ["check", "download", "stage"])
def test_prelaunch_failure_offers_explicit_retry_and_verified_installed_version(failure):
    flow, backend, views = make(failure=failure)
    assert not flow.run()
    assert flow.view.phase == Phase.ERROR and flow.view.retry and flow.view.offline
    assert "secret-token" not in repr(views)
    backend.failure = None
    assert flow.run(offline=True)
    assert backend.calls[-1] == "launch"
    assert backend.calls.count("check") == 1


@pytest.mark.parametrize("failure,release", [("activate", True), ("launch", False)])
def test_ambiguous_launch_never_retries_or_launches_old_version(failure, release):
    flow, backend, _ = make(failure=failure, release=release)
    assert not flow.run()
    assert flow.view.phase == Phase.BLOCKED
    assert not flow.view.retry and not flow.view.offline
    calls = backend.calls[:]
    assert not flow.run() and not flow.run(offline=True)
    assert backend.calls == calls


@pytest.mark.parametrize("result", ["UNKNOWN", None, "healthy", True])
def test_only_exact_complete_result_is_success(result):
    flow, _, _ = make(result=result)
    assert not flow.run()
    assert flow.view.phase == Phase.BLOCKED


def test_confirmed_rollback_offers_previous_without_automatically_launching():
    flow, backend, _ = make(result="ROLLED_BACK")
    assert not flow.run()
    assert flow.view.offline
    assert "launch" not in backend.calls
    assert flow.run(offline=True)


def test_unverified_or_missing_installed_version_is_not_offered():
    flow, backend, _ = make(failure="check", installed=False)
    assert not flow.run()
    assert not flow.view.offline
    assert not flow.run(offline=True)
    assert "launch" not in backend.calls


def test_reentrant_call_cannot_start_a_second_attempt():
    backend = Backend()
    flow = StartupFlow(backend, lambda view: flow.run() if view.phase == Phase.CHECKING else None)
    assert flow.run()
    assert backend.calls.count("check") == 1


def test_progress_rejects_untrusted_numbers():
    flow, _, views = make()
    flow._show(Phase.DOWNLOADING, "title", "detail")
    for done, total in [(True, 3), (1, 0), (3, 2), (-1, 3), (1, float("inf"))]:
        flow._progress(done, total)
    assert len(views) == 1
