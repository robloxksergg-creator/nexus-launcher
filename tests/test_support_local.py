import time
import ast
import io
import json
from pathlib import Path
from urllib.error import HTTPError
import pytest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from nexus_launcher.nexus_account import NexusAccountClient, NexusProfile, AccountError
from nexus_launcher.nexus_platform.support_page import SupportPage


def test_account_profile_without_nick_and_stable_id():
    profile = NexusAccountClient('https://fixture.test')._profile_from_result({'user':{'id':'fixture-account','minecraftNick':'','email':'a@fixture.test','profileCompleted':False}}, 'fixture-token')
    assert profile.user_id == 'fixture-account'
    assert not profile.profile_completed

def test_structured_profile_error_survives_native_transport():
    error=HTTPError('https://fixture.test/api/launcher/game-ticket',409,'Conflict',{},io.BytesIO(json.dumps({'error':'Complete profile','code':'PROFILE_INCOMPLETE','setupUrl':'/profile/setup'}).encode()))
    with patch('nexus_launcher.nexus_account.open_https',side_effect=error),pytest.raises(AccountError) as raised:
        NexusAccountClient('https://fixture.test')._request('/api/launcher/game-ticket',method='POST',token='fixture-token')
    assert raised.value.code=='PROFILE_INCOMPLETE' and raised.value.setup_url=='/profile/setup'

@pytest.mark.parametrize('name',['_launch_worker','_launch_user_instance_worker'])
def test_actual_launch_workers_block_account_without_game_profile(name):
    # Compile the complete existing function without importing application startup.
    # Guards must return before any network, instance load or process launch.
    tree=ast.parse(Path('nexus_launcher/modern_main.py').read_text(encoding='utf-8-sig'))
    function=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
    namespace={};exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'actual-launch-worker','exec'),namespace)
    errors=[]
    class ForbiddenClient:
        def __getattr__(self,field):raise AssertionError('Game operation must not be reached')
    owner=SimpleNamespace(account_profile=NexusProfile('','fixture@example.invalid',user_id='fixture'),account_client=ForbiddenClient(),bridge=SimpleNamespace(failed=SimpleNamespace(emit=errors.append)))
    namespace[name](owner,*(['fixture-instance'] if name=='_launch_user_instance_worker' else []))
    assert len(errors)==1 and 'Minecraft-профиль' in errors[0]


def test_support_page_uses_account_session_and_threaded_requests(tmp_path):
    app = QApplication.instance() or QApplication([])
    calls = []
    ticket={'id':'a'*64,'subject':'Test issue','status':'waiting_for_staff','version':1}
    class Client:
        def support_session(self,account): return 'fixture-only-token'
        def _request(self,path,**kw):
            calls.append((path,kw))
            if path=='/api/launcher/profile':return {'user':{'id':'fixture-account'}},None
            if kw['method']=='POST': return ticket,None
            if path.endswith('tickets'): return {'tickets':[ticket]},None
            return {'ticket':ticket,'messages':[],'nextCursor':0,'hasMore':False},None
    launcher=SimpleNamespace(account_profile=NexusProfile('','a@fixture.test',user_id='fixture-account'),account_client=Client())
    with patch('nexus_launcher.nexus_platform.support_page.QSettings',lambda *a:QSettings(str(tmp_path/'context.ini'),QSettings.Format.IniFormat)):
        page=SupportPage(launcher);page.show()
        deadline=time.monotonic()+3
        while not calls or page.busy:
            app.processEvents();time.sleep(.01)
            assert time.monotonic()<deadline
        page.subject.setText('Test issue');page.text.setPlainText('Please help');page.send(True)
        while page.busy:
            app.processEvents();time.sleep(.01)
            assert time.monotonic()<deadline
        assert any(kwargs.get('idempotency_key') for _,kwargs in calls)
        assert all(kwargs['token']=='fixture-only-token' for _,kwargs in calls)
        page.hide();assert not page.timer.isActive();page.close()


@pytest.mark.parametrize('before_start',[False,True])
def test_switch_account_cancels_draft_without_network_mutation(tmp_path,before_start):
    app=QApplication.instance() or QApplication([])
    queued=[];calls=[]
    class Thread:
        def __init__(self,target,**kwargs):self.target=target
        def start(self):queued.append(self.target)
    class Client:
        def support_session(self,account):return 'fixture-A' if launcher.account_profile.user_id=='A' else 'fixture-B'
        def _request(self,path,**kwargs):
            calls.append((path,kwargs))
            return {'user':{'id':'A'}},None
    launcher=SimpleNamespace(account_profile=NexusProfile('','a@fixture.test',user_id='A'),account_client=Client())
    with patch('nexus_launcher.nexus_platform.support_page.QSettings',lambda *a:QSettings(str(tmp_path/'context.ini'),QSettings.Format.IniFormat)),patch('nexus_launcher.nexus_platform.support_page.threading.Thread',Thread):
        page=SupportPage(launcher);page.owner='A'
        page.subject.setText('Private A');page.text.setPlainText('Private draft A')
        if before_start:launcher.account_profile=NexusProfile('','b@fixture.test',user_id='B')
        page.send(True)
        launcher.account_profile=NexusProfile('','b@fixture.test',user_id='B')
        for work in queued:work()
        app.processEvents()
        assert not calls
        assert page.text.toPlainText()=='' and page.subject.text()==''
        assert page.pending is None and not page.messages
        page.close()


def test_captured_token_owner_is_checked_before_support_send(tmp_path):
    app=QApplication.instance() or QApplication([]);queued=[];calls=[]
    class Thread:
        def __init__(self,target,**kwargs):self.target=target
        def start(self):queued.append(self.target)
    class Client:
        def support_session(self,account):return 'fixture-B'
        def _request(self,path,**kwargs):
            calls.append((path,kwargs));return {'user':{'id':'B'}},None
    launcher=SimpleNamespace(account_profile=NexusProfile('','a@fixture.test',user_id='A'),account_client=Client())
    with patch('nexus_launcher.nexus_platform.support_page.QSettings',lambda *a:QSettings(str(tmp_path/'context.ini'),QSettings.Format.IniFormat)),patch('nexus_launcher.nexus_platform.support_page.threading.Thread',Thread):
        page=SupportPage(launcher);page.owner='A';page.subject.setText('A');page.text.setPlainText('Private A');page.send(True)
        assert calls==[]
        queued[0]();app.processEvents()
        assert [path for path,_ in calls]==['/api/launcher/profile']
        assert page.text.toPlainText()=='' and page.subject.text()==''
        assert page.pending is None
        page.close()



def test_support_session_requires_matching_verified_account_and_token():
    client=NexusAccountClient('https://fixture.test')
    with patch.object(client,'_token',return_value='fixture-A'):
        assert client.support_session('A') is None
        client._profile_from_result({'user':{'id':'A','minecraftNick':'','profileCompleted':False}},'fixture-A')
        assert client.support_session('A')=='fixture-A'
        assert client.support_session('B') is None
    with patch.object(client,'_token',return_value='fixture-B'):
        assert client.support_session('A') is None
