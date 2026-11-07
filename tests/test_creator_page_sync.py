from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import json
import pytest
from nexus_launcher.creator_services import Capabilities,StudioService
from nexus_launcher.user_instances import InstanceService
from nexus_launcher.creator_page_workspace import CreatorPageWorkspace
from nexus_launcher.creator_page_contract import page_from_project,validate_page_content
from nexus_launcher.nexus_account import NexusAccountClient,NexusProfile,SessionRejected,ProtocolError,AccountError
from tests.test_nexus_account import FakeResponse


PROFILE=NexusProfile('Fixture','fixture@example.invalid',user_id='fixture-account',experience_role='server_creator')


def content():
    return dict(name='Synthetic world',summary='Test only',about='World',rules='Rules',team='Author',address='play.example.org',version='1.21.1',loader='fabric',genre='RPG',website='',cover='mountains',accent='blue',theme='dark',mode='blocks')


def draft(value=None):
    return dict(id='11111111-1111-4111-8111-111111111111',revision=1,state='DRAFT',content=value or content(),updatedAt=1,submittedAt=None,review=None)


def fixture(tmp_path):
    instances=InstanceService(tmp_path)
    instance=instances.create('Synthetic world','1.21.1','vanilla')
    studio=StudioService(instances,Capabilities('creator'))
    return studio,instance


class Remote:
    def __init__(self):self.items={};self.calls=[];self.drop=False
    def creator_pages(self,profile,operation=None):
        if not operation:return deepcopy(list(self.items.values()))
        self.calls.append(deepcopy(operation));action=operation['action'];old=self.items.get(operation['id'])
        if action=='create':
            if old:
                if old['revision']!=1 or old['content']!=operation['content']:raise AccountError('Conflict',http_status=409)
                return deepcopy(old)
            value=dict(draft(operation['content']),id=operation['id'])
        else:
            if not old or old['revision']!=operation['revision']:raise AccountError('Conflict',http_status=409)
            value=deepcopy(old);value['revision']+=1
            if action=='save':value['content']=deepcopy(operation['content'])
            if action=='submit':value.update(state='SUBMITTED',submittedAt=2)
            if action=='reopen':value.update(state='DRAFT',submittedAt=None)
        self.items[value['id']]=value
        if self.drop:raise TimeoutError('Synthetic timeout after commit')
        return deepcopy(value)


def test_lost_create_response_recovers_same_application_after_restart(tmp_path):
    studio,instance=fixture(tmp_path);remote=Remote()
    w=CreatorPageWorkspace(remote,PROFILE,studio,instance.id);assert w.load() is None
    remote.drop=True
    with pytest.raises(TimeoutError):w.write('save',content())
    assert w.unknown and w.path.exists()
    assert 'token' not in w.path.read_text()
    with pytest.raises(ValueError):w.write('save',content())
    assert len(remote.calls)==1
    recovered=CreatorPageWorkspace(remote,PROFILE,studio,instance.id)
    page=recovered.load()
    assert page['id']==json.loads(w.path.read_text())['id']
    assert len(remote.items)==1 and len(remote.calls)==1


def test_submit_rights_locked_content_withdraw_and_cas_conflict(tmp_path):
    studio,instance=fixture(tmp_path);remote=Remote()
    w=CreatorPageWorkspace(remote,PROFILE,studio,instance.id);w.load();w.write('save',content())
    with pytest.raises(ValueError):w.write('submit',rights=False)
    assert w.write('submit',rights=True)['state']=='SUBMITTED'
    with pytest.raises(ValueError):w.write('save',content())
    assert w.write('reopen')['state']=='DRAFT'
    remote.items[w.link['id']]['revision']+=1
    with pytest.raises(AccountError):w.write('save',dict(content(),summary='Stale save'))
    assert w.unknown
    assert remote.items[w.link['id']]['content']['summary']=='Test only'
    w.load();assert not w.unknown


def test_other_account_and_corrupt_local_link_block_without_remote_write(tmp_path):
    studio,instance=fixture(tmp_path);remote=Remote()
    w=CreatorPageWorkspace(remote,PROFILE,studio,instance.id);w.load();w.write('save',content())
    other=NexusProfile('Other','other@example.invalid',user_id='other')
    with pytest.raises(ValueError):CreatorPageWorkspace(remote,other,studio,instance.id).load()
    w.path.write_text('not JSON')
    with pytest.raises(ValueError):w.load()
    assert len(remote.calls)==1


def test_two_open_workspaces_reuse_one_persisted_application_id(tmp_path):
    studio,instance=fixture(tmp_path);remote=Remote()
    a=CreatorPageWorkspace(remote,PROFILE,studio,instance.id)
    b=CreatorPageWorkspace(remote,PROFILE,studio,instance.id)
    a.load();b.load()
    first=a.write('save',content());second=b.write('save',content())
    assert first['id']==second['id'] and len(remote.items)==1


def test_existing_website_application_can_be_attached_without_mutation(tmp_path):
    studio,instance=fixture(tmp_path);remote=Remote();page=draft();remote.items[page['id']]=page
    w=CreatorPageWorkspace(remote,PROFILE,studio,instance.id);w.load()
    with pytest.raises(ValueError):w.attach('22222222-2222-4222-8222-222222222222')
    assert w.attach(page['id'])==page and remote.calls==[]
    assert json.loads(w.path.read_text())['id']==page['id']
    with pytest.raises(ValueError):w.attach(page['id'])


def test_actual_client_requires_bound_session_and_rejects_account_switch():
    client=NexusAccountClient('https://example.test');client._support_identity=(PROFILE.user_id,'t'*64)
    result={'accountId':PROFILE.user_id,'items':[draft()]}
    with patch.object(client,'_token',side_effect=['t'*64,'changed']),patch.object(client,'_request',return_value=(result,None)):
        with pytest.raises(SessionRejected):client.creator_pages(PROFILE)
    with patch.object(client,'_token',return_value='other'),patch.object(client,'_request') as send:
        with pytest.raises(SessionRejected):client.creator_pages(PROFILE)
        send.assert_not_called()


def test_actual_http_transport_posts_bearer_and_account_fenced_content():
    client=NexusAccountClient('https://example.test');client._support_identity=(PROFILE.user_id,'t'*64)
    value=draft();operation={'action':'create','id':value['id'],'revision':0,'content':content()}
    with patch.object(client,'_token',return_value='t'*64),patch('nexus_launcher.nexus_account.open_https',return_value=FakeResponse({'accountId':PROFILE.user_id,'item':value})) as http:
        assert client.creator_pages(PROFILE,operation)==value
    request=http.call_args.args[0]
    assert request.full_url=='https://example.test/api/launcher/creator-pages'
    assert request.get_header('Authorization')=='Bearer '+'t'*64
    payload=json.loads(request.data)
    assert payload['accountId']==PROFILE.user_id and 'token' not in payload and 'official' not in payload


def test_native_payload_uses_utf8_without_six_byte_cyrillic_expansion():
    client=NexusAccountClient('https://example.test');client._support_identity=(PROFILE.user_id,'t'*64)
    value=draft(dict(content(),about='я'*2400,rules='я'*1800,team='я'*1000))
    with patch.object(client,'_token',return_value='t'*64),patch('nexus_launcher.nexus_account.open_https',return_value=FakeResponse({'accountId':PROFILE.user_id,'item':value})) as http:
        client.creator_pages(PROFILE,{'action':'create','id':value['id'],'revision':0,'content':value['content']})
    request=http.call_args.args[0]
    assert len(request.data)<24000 and 'я'.encode('utf-8') in request.data


@pytest.mark.parametrize('change',[{'accountId':'other'},{'item':dict(draft(),revision=9)},{'item':dict(draft(),state='SUBMITTED')},{'item':dict(draft(),content=dict(content(),summary='Altered'))}])
def test_wrong_receipt_is_not_confirmed(change):
    client=NexusAccountClient('https://example.test');client._support_identity=(PROFILE.user_id,'t'*64)
    result=dict(accountId=PROFILE.user_id,item=draft());result.update(change)
    with patch.object(client,'_token',return_value='t'*64),patch.object(client,'_request',return_value=(result,None)):
        with pytest.raises(ProtocolError):client.creator_pages(PROFILE,{'action':'create','id':draft()['id'],'revision':0,'content':content()})


def test_project_mapping_never_truncates_and_keeps_release_plan(tmp_path):
    studio,instance=fixture(tmp_path);project=studio.load(instance.id)
    project['description']='x'*2401
    with pytest.raises(ValueError):page_from_project(project,instance)
    value=content();value['name']='😀'*41
    with pytest.raises(ValueError):validate_page_content(value)
