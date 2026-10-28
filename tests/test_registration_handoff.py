"""Exercise actual nested transition functions with synthetic UI/auth owners."""
from pathlib import Path
from types import CodeType,FunctionType,SimpleNamespace

import pytest


def nested(name,values):
    source=(Path(__file__).resolve().parents[1] / 'nexus_launcher' / 'tester_main.py').read_text(encoding='utf-8')
    module=compile(source,'<tester-main>','exec')
    main=next(x for x in module.co_consts if isinstance(x,CodeType) and x.co_name=='main')
    code=next(x for x in main.co_consts if isinstance(x,CodeType) and x.co_name==name)
    cell=lambda value:(lambda:value).__closure__[0]
    return FunctionType(code,{},closure=tuple(cell(values[n]) for n in code.co_freevars))


@pytest.mark.parametrize('accepted,complete,scheduled',[(True,True,True),(True,False,False),(False,True,False),(False,False,False)])
def test_completed_registration_opens_login_only_after_profile_confirmation(accepted,complete,scheduled):
    calls=[];owner=object();gate=object()
    surfaces=SimpleNamespace(removeWidget=lambda p:calls.append('removed'),setCurrentWidget=lambda p:calls.append('gate'))
    page=SimpleNamespace(registration_form=SimpleNamespace(profile_completed=complete,nick=SimpleNamespace(text=lambda:'Synthetic_User')),deleteLater=lambda:calls.append('deleted'))
    host=SimpleNamespace(surfaces=surfaces)
    timers=[]
    timer=SimpleNamespace(singleShot=lambda delay,context,callback:timers.append((context,callback)))
    finish=nested('finish_registration',dict(QTimer=timer,host=host,gate=gate,auth=SimpleNamespace(message='synthetic'),message=SimpleNamespace(setText=lambda text:None),registration_page=owner,sign_in=lambda name:calls.append(('login',name))))
    finish(page,accepted)
    assert bool(timers)==scheduled
    assert calls==['removed','gate','deleted']
    if scheduled:
        assert timers[0][0] is host
        timers[0][1]()
        assert calls[-1]==('login','Synthetic_User')


@pytest.mark.parametrize('accepted',[True,False])
def test_login_requires_manual_password_and_cancel_never_authenticates(accepted):
    calls=[]
    dialog=SimpleNamespace(identifier=SimpleNamespace(setText=lambda text:calls.append(('identifier',text))),password=SimpleNamespace(setFocus=lambda:calls.append('focus'),clear=lambda:calls.append('cleared')),exec=lambda:accepted,credentials=lambda:('Synthetic_User','synthetic-password'))
    sign_in=nested('sign_in',dict(auth=SimpleNamespace(busy=False,run=lambda *a:calls.append(('auth',a))),NexusLogin=lambda host:dialog,host=object()))
    sign_in('Synthetic_User')
    assert calls[:2]==[('identifier','Synthetic_User'),'focus']
    assert 'cleared' in calls
    assert any(isinstance(x,tuple) and x[0]=='auth' for x in calls)==accepted


def test_auth_busy_prevents_duplicate_login_dialog():
    sign_in=nested('sign_in',dict(auth=SimpleNamespace(busy=True),NexusLogin=lambda _:pytest.fail('duplicate dialog'),host=object()))
    sign_in('Synthetic_User')


def test_qt_context_bound_transition_is_cancelled_when_host_is_destroyed():
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtCore import QTimer,QEvent
    app=QApplication.instance() or QApplication([])
    called=[];host=QWidget()
    QTimer.singleShot(0,host,lambda:called.append('opened'))
    host.deleteLater();app.sendPostedEvents(None,QEvent.DeferredDelete);app.processEvents()
    assert called==[]
