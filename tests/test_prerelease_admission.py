from types import SimpleNamespace

import pytest

from nexus_launcher.nexus_account import NexusProfile
from tests.test_registration_handoff import nested


def update_for(status,user):
    calls=[];view=object();gate=object()
    button=lambda:SimpleNamespace(setEnabled=lambda _:None)
    services=SimpleNamespace(account_profile=None,config={'username':'synthetic'},_save_config=lambda:None,_account_ready=lambda profile:calls.append(('admit',profile)),profile=button())
    host=SimpleNamespace(view=view,surfaces=SimpleNamespace(setCurrentWidget=lambda target:calls.append(('surface',target))),library_overlay=SimpleNamespace(hide=lambda:None),_library_active=False,_sync_state=lambda _:None)
    retry=button();retry.setVisible=lambda _:None
    update=nested('update',dict(auth=SimpleNamespace(status=status,user=user,message='synthetic',busy=False,connection='ONLINE'),services=services,host=host,gate=gate,message=SimpleNamespace(setText=lambda _:None),registration_page=None,login=button(),register=button(),retry=retry))
    update.__globals__['logging']=SimpleNamespace(info=lambda *args:None)
    update()
    return calls,view,gate


@pytest.mark.parametrize('email',['synthetic@gmail.com','synthetic@outlook.com','synthetic@proton.me','synthetic@company.example','synthetic@xn--e1afmkfd.xn--p1ai'])
@pytest.mark.parametrize('tester',[False,True])
def test_any_email_provider_with_authenticated_account_opens_regular_view(email,tester):
    user=NexusProfile('Synthetic',email,tester=tester)
    calls,view,_=update_for('authenticated',user)
    assert ('admit',user) in calls
    assert ('surface',view) in calls
    assert user.tester is tester  # UI admission never promotes the account.


@pytest.mark.parametrize('status,user',[('unauthenticated',None),('loading',None),('authenticated',None),('loading',SimpleNamespace(tester=True,is_admin=True)),('unauthenticated',SimpleNamespace(tester=True,is_admin=True))])
def test_unknown_or_unverified_session_cannot_open_regular_view(status,user):
    calls,view,gate=update_for(status,user)
    assert not any(name=='admit' for name,_ in calls)
    assert ('surface',gate) in calls
    assert ('surface',view) not in calls
