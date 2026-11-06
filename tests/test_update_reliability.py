"""Faults use disposable signed fixtures and synthetic process adapters only."""
import errno
import io
import json
import urllib.error
import zipfile

import pytest

from nexus_launcher.resumable_download import receive
from nexus_launcher.self_update import version_tuple
from nexus_launcher.portable_transition import prepare_transition,resolve_transition
from tests.test_portable_package import resign
from tests.test_resumable_download import Response
from tests.test_startup_portable_backend import setup


@pytest.mark.parametrize('a,b',[('1.2.3','1.2.3.0'),('v1.2.3','1.2.3.0'),('001.002.003','1.2.3')])
def test_equivalent_version_spellings_do_not_become_upgrades(a,b):
    assert version_tuple(a)==version_tuple(b)
    assert version_tuple('1.2.3.1')>version_tuple(a)


def test_semantically_equal_candidate_is_rejected_before_transition(tmp_path):
    backend,root,old,_,key=setup(tmp_path)
    backend.transport.envelope['release']['version']='1.0.0.0';resign(backend.transport.envelope,key)
    assert backend.check() is None
    candidate=backend.stage(backend.download(backend.transport.envelope,lambda *_:None),backend.transport.envelope)
    with pytest.raises(ValueError,match='downgrade'):
        prepare_transition(root,candidate.name,old.name,platform='windows',arch='x64',keys=backend.keys)
    assert not (root/'transition.json').exists()


@pytest.mark.parametrize('phase,pointer_new,expected',[('PREPARED',False,'ROLLED_BACK'),('COMMITTING',False,'COMPLETE'),('COMMITTING',True,'COMPLETE'),('ROLLING_BACK',False,'ROLLED_BACK'),('ROLLING_BACK',True,'ROLLED_BACK')])
def test_decided_restart_is_reverified_without_spawning(tmp_path,phase,pointer_new,expected):
    backend,root,old,new,_=setup(tmp_path)
    journal=prepare_transition(root,new.name,old.name,platform='windows',arch='x64',keys=backend.keys)
    journal['phase']=phase;(root/'transition.json').write_text(json.dumps(journal))
    (root/'active.json').write_text(json.dumps({'slot':new.name if pointer_new else old.name}))
    before=(root/'user-data.json').read_bytes()
    assert backend.can_launch_current()
    assert json.loads((root/'transition.json').read_text())['phase']==expected
    assert json.loads((root/'active.json').read_text())=={'slot':new.name if expected=='COMPLETE' else old.name}
    assert backend.adapter.calls==['wait']
    assert backend.can_launch_current() and backend.adapter.calls==['wait']
    assert (root/'user-data.json').read_bytes()==before and old.exists() and new.exists()


@pytest.mark.parametrize('phase',['LAUNCHING','UNKNOWN'])
def test_ambiguous_process_restart_stays_blocked_and_unchanged(tmp_path,phase):
    backend,root,old,new,_=setup(tmp_path)
    journal=prepare_transition(root,new.name,old.name,platform='windows',arch='x64',keys=backend.keys)
    journal['phase']=phase;(root/'transition.json').write_text(json.dumps(journal))
    before=(root/'transition.json').read_bytes()
    assert not backend.can_launch_current()
    assert (root/'transition.json').read_bytes()==before and backend.adapter.calls==[]


@pytest.mark.parametrize('fault',['lease','candidate','history','pointer','schema'])
def test_recovery_rejects_missing_authority_or_corruption_without_writes(tmp_path,fault):
    backend,root,old,new,_=setup(tmp_path)
    journal=prepare_transition(root,new.name,old.name,platform='windows',arch='x64',keys=backend.keys);journal['phase']='COMMITTING'
    if fault=='lease':backend.adapter.mode='parent-unknown'
    if fault=='candidate':(new/'files/launcher.exe').write_bytes(b'corrupt')
    if fault=='history':(root/'highest-package.json').write_text('{}')
    if fault=='pointer':(root/'active.json').write_text(json.dumps({'slot':'portable-stage-foreign'}))
    if fault=='schema':journal['schema']=True
    (root/'transition.json').write_text(json.dumps(journal));before=((root/'active.json').read_bytes(),(root/'transition.json').read_bytes())
    assert not backend.can_launch_current()
    assert before==((root/'active.json').read_bytes(),(root/'transition.json').read_bytes())
    assert not any(v in backend.adapter.calls for v in ['launch','current','stop'])


def test_completed_journal_detects_pointer_rollback(tmp_path):
    backend,root,old,new,_=setup(tmp_path)
    j=prepare_transition(root,new.name,old.name,platform='windows',arch='x64',keys=backend.keys)
    resolve_transition(root,'HEALTHY',operation_id=j['operation_id'],candidate_identity=j['candidate_identity'],keys=backend.keys)
    assert backend.can_launch_current()
    (root/'active.json').write_text(json.dumps({'slot':old.name}))
    assert not backend.can_launch_current() and backend.adapter.calls==[]


def test_verified_installed_package_still_requires_matching_platform(tmp_path):
    backend,*_=setup(tmp_path);backend.arch='arm64'
    assert not backend.can_launch_current() and backend.adapter.calls==[]


@pytest.mark.parametrize('phase',['PREPARED','COMMITTING','ROLLING_BACK'])
def test_recovery_write_failure_remains_recoverable_without_a_second_process(tmp_path,monkeypatch,phase):
    import nexus_launcher.portable_transition as module
    backend,root,old,new,_=setup(tmp_path)
    j=prepare_transition(root,new.name,old.name,platform='windows',arch='x64',keys=backend.keys);j['phase']=phase
    (root/'transition.json').write_text(json.dumps(j));real=module.atomic_json
    def fail_final(path,value):
        if path.name=='transition.json':raise OSError('synthetic disk failure')
        real(path,value)
    with monkeypatch.context() as patch:
        patch.setattr(module,'atomic_json',fail_final);assert not backend.can_launch_current()
    assert backend.can_launch_current()
    assert not any(v in backend.adapter.calls for v in ['launch','current','stop'])


@pytest.mark.parametrize('broken',[False,True])
def test_staging_consumes_only_the_exact_owned_archive(tmp_path,broken):
    backend,root,old,_,_=setup(tmp_path);sentinel=root/'cache'/'user-file'
    release=backend.check();archive=backend.download(release,lambda *_:None);sentinel.write_bytes(b'keep')
    if broken:archive.write_bytes(b'corrupt')
    if broken:
        with pytest.raises((ValueError,zipfile.BadZipFile)):backend.stage(archive,release)
    else:assert backend.stage(archive,release).exists()
    assert not archive.exists() and sentinel.read_bytes()==b'keep' and old.exists()


def test_retry_backoff_and_retry_after_are_bounded(monkeypatch):
    pauses=[];monkeypatch.setattr('nexus_launcher.resumable_download.time.sleep',pauses.append)
    calls=[]
    def opened(offset):
        calls.append(offset)
        if len(calls)==1:raise ConnectionError('synthetic')
        if len(calls)==2:raise urllib.error.HTTPError('https://fixture.invalid',429,'fixture',{'Retry-After':'3'},None)
        return Response(b'ok',headers={'Content-Length':'2'})
    output=io.BytesIO();assert receive(output,opened,size=2,limit=2,progress=lambda *_:None)==2
    assert pauses==[.5,3] and output.getvalue()==b'ok'


@pytest.mark.parametrize('fault',['disk','short-write','progress','flush'])
def test_local_io_errors_are_never_retried_as_network_errors(fault):
    calls=[]
    class Output(io.BytesIO):
        def write(self,value):
            if fault=='disk':raise OSError(errno.ENOSPC,'synthetic full disk')
            if fault=='short-write':return super().write(value[:-1])
            return super().write(value)
        def flush(self):
            if fault=='flush':raise OSError('synthetic flush failure')
            return super().flush()
    def opened(offset):calls.append(offset);return Response(b'ok')
    def progress(*_):
        if fault=='progress':raise OSError('synthetic UI callback failure')
    with pytest.raises(OSError):receive(Output(),opened,size=2,limit=2,progress=progress)
    assert calls==[0]


@pytest.mark.parametrize('header',['gzip','br','deflate'])
def test_encoded_bodies_never_enter_anonymous_update_cache(header):
    output=io.BytesIO()
    with pytest.raises(ValueError,match='Encoded'):
        receive(output,lambda _:Response(b'ok',headers={'Content-Encoding':header}),size=2,limit=2,progress=lambda *_:None)
    assert output.getvalue()==b''


def test_legitimate_partial_segments_are_bounded_and_reassembled(monkeypatch):
    monkeypatch.setattr('nexus_launcher.resumable_download.time.sleep',lambda _:None);offsets=[]
    def opened(offset):
        offsets.append(offset)
        if offset==0:return Response(b'abc',headers={'Content-Length':'6'})
        if offset==3:return Response(b'de',status=206,headers={'Content-Range':'bytes 3-4/6','Content-Length':'2'})
        return Response(b'f',status=206,headers={'Content-Range':'bytes 5-5/6','Content-Length':'1'})
    output=io.BytesIO();assert receive(output,opened,size=6,limit=6,progress=lambda *_:None)==6
    assert output.getvalue()==b'abcdef' and offsets==[0,3,5]


@pytest.mark.parametrize('budget',[{'attempts':0},{'attempts':True},{'attempts':100},{'timeout':float('inf')},{'timeout':-1},{'retry_delay':float('nan')}])
def test_invalid_retry_policy_cannot_start_io(budget):
    with pytest.raises(ValueError):receive(io.BytesIO(),lambda _:pytest.fail('Unexpected I/O'),size=1,limit=1,progress=lambda *_:None,**budget)


def test_large_retry_after_does_not_sleep_or_repeat(monkeypatch):
    monkeypatch.setattr('nexus_launcher.resumable_download.time.sleep',lambda _:pytest.fail('Unexpected wait'));calls=[]
    def opened(offset):calls.append(offset);raise urllib.error.HTTPError('https://fixture.invalid',503,'fixture',{'Retry-After':'999999999'},None)
    with pytest.raises(TimeoutError):receive(io.BytesIO(),opened,size=1,limit=1,progress=lambda *_:None)
    assert calls==[0]


def test_watermark_rejects_same_semantic_version_with_a_different_identity(tmp_path):
    backend,root,old,new,key=setup(tmp_path)
    j=prepare_transition(root,new.name,old.name,platform='windows',arch='x64',keys=backend.keys)
    resolve_transition(root,'FAILED',operation_id=j['operation_id'],candidate_identity=j['candidate_identity'],keys=backend.keys)
    envelope=backend.transport.envelope;envelope['release']['version']='2.0.0.0';resign(envelope,key)
    candidate=backend.stage(backend.download(envelope,lambda *_:None),envelope)
    with pytest.raises(ValueError,match='equivocation'):
        prepare_transition(root,candidate.name,old.name,platform='windows',arch='x64',keys=backend.keys)


@pytest.mark.parametrize('phase',['check','download'])
@pytest.mark.parametrize('kind,code',[('tls','UPDATE_TLS'),('network','UPDATE_NETWORK'),('disk','UPDATE_IO'),('invalid','UPDATE_REJECTED')])
def test_prelaunch_errors_show_safe_categories_without_disabling_verification(phase,kind,code):
    import ssl
    from tests.test_startup_update_flow import make
    flow,backend,_=make()
    error={'tls':urllib.error.URLError(ssl.SSLCertVerificationError('SECRET')),'network':ConnectionError('SECRET'),'disk':OSError(errno.ENOSPC,'SECRET'),'invalid':ValueError('SECRET')}[kind]
    def fail(*_):raise error
    setattr(backend,phase,fail)
    assert not flow.run() and code in flow.view.detail and 'SECRET' not in flow.view.detail
    assert flow.view.offline and not any(v in backend.calls for v in ['launch','activate'])
