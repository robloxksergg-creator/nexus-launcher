"""OS trust refusals must not become update or execution authority."""
import errno
import os
import subprocess
import sys

import pytest
from tests.test_posix_updates import bundle

from nexus_launcher import posix_quarantine as q
from nexus_launcher.startup_update_flow import OSApprovalRequired, Phase, StartupFlow


def test_quarantine_is_preserved_and_downloads_are_marked(monkeypatch):
    monkeypatch.setattr(q.sys, 'platform', 'darwin')
    writes = []
    original = b'0083;12345678;Browser;fixture'
    monkeypatch.setattr(q.os, 'getxattr', lambda *a, **k: original, raising=False)
    monkeypatch.setattr(q.os, 'setxattr', lambda *a, **k: writes.append((a, k)), raising=False)
    q.preserve('original.app', 'staged.app')
    assert writes[0] == (('staged.app', q.ATTRIBUTE, original), {'follow_symlinks': False})
    q.mark_download('owned-cache.zip')
    assert writes[1][0][0] == 'owned-cache.zip'
    assert writes[1][0][2].startswith(b'0081;') and b';NEXUS;' in writes[1][0][2]


def test_missing_quarantine_is_distinct_from_attribute_read_failure(monkeypatch):
    monkeypatch.setattr(q.sys, 'platform', 'darwin')
    def absent(*a, **k):
        raise OSError(getattr(errno, 'ENOATTR', errno.ENODATA), 'absent')
    monkeypatch.setattr(q.os, 'getxattr', absent, raising=False)
    assert q.read('fixture') is None
    def denied(*a, **k):
        raise OSError(errno.EACCES, 'denied')
    monkeypatch.setattr(q.os, 'getxattr', denied, raising=False)
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
