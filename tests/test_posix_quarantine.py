"""OS trust refusals must not become update or execution authority."""
import errno
import os
import subprocess
import sys

import pytest
from tests.test_posix_updates import bundle

from nexus_launcher import posix_quarantine as q
from nexus_launcher.startup_update_flow import OSApprovalRequired, Phase, StartupFlow


def test_darwin_attribute_abi_bounds_and_binary_values(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    calls = []
    value = b'abc\x00def'
    def get(path, name, buffer, size, position, options):
        calls.append((path, name, size, position, options))
        if buffer is not None:
            ctypes.memmove(buffer, value, len(value))
        return len(value)
    def put(path, name, buffer, size, position, options):
        assert ctypes.string_at(buffer, size) == value
        assert position == 0 and options == 1
        return 0
    monkeypatch.setattr(q, '_libc', lambda: SimpleNamespace(getxattr=get, setxattr=put))
    assert q._get_attribute('fixture') == value
    q._set_attribute('fixture', value)
    assert calls == [(b'fixture', q.ATTRIBUTE.encode(), 0, 0, 1),
                     (b'fixture', q.ATTRIBUTE.encode(), len(value), 0, 1)]
    with pytest.raises(ValueError):
        q._get_attribute('bad\x00path')
    with pytest.raises(ValueError):
        q._set_attribute('fixture', b'x' * (q.MAX_ATTRIBUTE_BYTES + 1))


@pytest.mark.parametrize('responses', [(65537,), (4, 3), (4, -1)])
def test_darwin_attribute_oversize_change_and_error_fail_closed(monkeypatch, responses):
    import ctypes
    from types import SimpleNamespace
    answers = iter(responses)
    def get(*args):
        ctypes.set_errno(errno.ERANGE)
        return next(answers)
    monkeypatch.setattr(q, '_libc', lambda: SimpleNamespace(getxattr=get))
    with pytest.raises(OSError):
        q._get_attribute('fixture')


def test_quarantine_is_preserved_and_downloads_are_marked(monkeypatch):
    monkeypatch.setattr(q.sys, 'platform', 'darwin')
    writes = []
    original = b'0083;12345678;Browser;fixture'
    monkeypatch.setattr(q, '_get_attribute', lambda _: original)
    monkeypatch.setattr(q, '_set_attribute', lambda *a: writes.append(a))
    q.preserve('original.app', 'staged.app')
    assert writes[0] == ('staged.app', original)
    q.mark_download('owned-cache.zip')
    assert writes[1][0] == 'owned-cache.zip'
    assert writes[1][1].startswith(b'0081;') and b';NEXUS;' in writes[1][1]


def test_missing_quarantine_is_distinct_from_attribute_read_failure(monkeypatch):
    monkeypatch.setattr(q.sys, 'platform', 'darwin')
    def absent(*a, **k):
        raise OSError(getattr(errno, 'ENOATTR', 93), 'absent')
    monkeypatch.setattr(q, '_get_attribute', absent)
    assert q.read('fixture') is None
    def denied(*a, **k):
        raise OSError(errno.EACCES, 'denied')
    monkeypatch.setattr(q, '_get_attribute', denied)
    with pytest.raises(OSError):
        q.read('fixture')


def test_assessment_is_read_only_and_refusal_is_explicit(monkeypatch):
    monkeypatch.setattr(q, 'read', lambda _: b'quarantined')
    calls = []
    def refusal(args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.CalledProcessError(1, args, stderr=b'private diagnostic')
    monkeypatch.setattr(q.subprocess, 'run', refusal)
    with pytest.raises(OSApprovalRequired):
        q.assess('/owned/staged.app', {'PATH': '/usr/bin:/bin'})
    assert calls[0][0] == ['/usr/sbin/spctl', '--assess', '--type', 'execute', '/owned/staged.app']
    assert calls[0][1]['timeout'] == 30 and calls[0][1]['check'] is True


def test_no_os_policy_command_for_non_quarantined_local_fixture(monkeypatch):
    monkeypatch.setattr(q, 'read', lambda _: None)
    monkeypatch.setattr(q.subprocess, 'run', lambda *a, **k: pytest.fail('Unexpected OS policy command'))
    q.assess('local-fixture.app', {})


def test_os_refusal_before_activation_keeps_offline_launch_available():
    class Backend:
        def check(self): return {'verified': True}
        def download(self, release, progress): return 'owned-cache'
        def stage(self, archive, release): raise OSApprovalRequired('private path and diagnostic')
        def can_launch_current(self): return True
        def activate(self, candidate): pytest.fail('Activation forbidden')
        def launch_current(self): pytest.fail('No automatic fallback spawn')
    flow = StartupFlow(Backend(), lambda _: None)
    assert flow.run() is False
    assert flow.view.phase == Phase.ERROR and flow.view.offline and flow.view.retry
    assert 'OS_APPROVAL_REQUIRED' in flow.view.detail and 'private' not in flow.view.detail


@pytest.mark.skipif(sys.platform != 'darwin', reason='Real macOS extended attributes required')
def test_native_quarantine_attribute_copy(tmp_path):
    source, target = tmp_path / 'download.fixture', tmp_path / 'staged.fixture'
    source.write_bytes(b'not executable')
    target.write_bytes(b'not executable')
    q.mark_download(source)
    original = q.read(source)
    assert original and original.startswith(b'0081;')
    q.preserve(source, target)
    assert q.read(target) == original and q.read(source) == original


@pytest.mark.skipif(sys.platform != 'darwin', reason='Real macOS quarantine propagation required')
def test_native_archive_and_adoption_keep_quarantine(tmp_path, bundle):
    from tests.test_posix_updates import zip_bytes
    from nexus_launcher.posix_package import stage_archive, stage_directory
    p, sign, keys, data = bundle
    archive = tmp_path / 'local-fixture.zip'
    archive.write_bytes(zip_bytes(p, data))
    q.mark_download(archive)
    original = q.read(archive)
    slot = stage_archive(archive, sign(p), tmp_path / 'staged', keys=keys)
    assert q.read(slot / 'files/NEXUS-Linux-x64') == original
    adopted = stage_directory(slot / 'files', sign(p), tmp_path / 'adopted', keys=keys, installed=True)
    assert q.read(adopted / 'files/NEXUS-Linux-x64') == original
