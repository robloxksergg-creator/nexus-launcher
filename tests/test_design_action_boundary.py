"""Actual method AST tests, no Qt/package imports; fixtures record dispatch only."""
import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT/'nexus_launcher/nexus_platform/design_bridge.py').read_text(encoding='utf-8'))
method = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'DesignHost'
              for n in c.body if isinstance(n, ast.FunctionDef) and n.name == '_action')
page_method = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'DesignPage'
                   for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'acceptNavigationRequest')
action_node = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'ACTIONS' for t in n.targets))
ACTIONS = frozenset(ast.literal_eval(action_node.args[0]))
# Reviewed methods have no imports, exec/eval or hidden definitions/decorators.
for node in (method, page_method):
    assert not node.decorator_list
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom, ast.Lambda)) for n in ast.walk(node))
    assert not any(isinstance(n, ast.Name) and n.id in {'eval','exec','open','__import__'} for n in ast.walk(node))
namespace={'QCursor':NS(pos=lambda:(0,0))}
exec(compile(ast.Module(body=[method], type_ignores=[]), 'actual-action-method', 'exec'),namespace)

def fixture(allow=True, identifier='valid'):
    calls=[]
    def spy(label):
        return lambda *a, **k: calls.append(label)
    services=NS(_current_page='home', config={'creatorMode':True},account_profile=NS(),game_process=None,
                play=NS(isEnabled=lambda:True),world_views=[NS(id='valid',server=NS())])
    for name in ('_toggle_pin','select_server','_save_world','_play','_login_account','_register_account',
                 '_logout_account','_refresh_account','_open_web_profile','_stop_game'):
        setattr(services,name,spy(name))
    services.studio_page=NS(open_creator=spy('academy'))
    services.instances_page=NS(_create=spy('create'),_open_card=spy('open'),_launch=spy('launch'))
    services._make_world_menu=lambda *a:NS(exec=spy('menu'))
    host=NS(services=services,_navigation_allowed=lambda *_:allow,_embed=spy('embed'),
            _hide_library=spy('hide'),_find_build=lambda i:NS() if i=='valid' else None,
            page=NS(runJavaScript=spy('notify')),projection=NS(refresh=spy('refresh')),
            _sync_state=spy('sync'),showMaximized=spy('max'),showFullScreen=spy('full'),isFullScreen=lambda:False)
    return host,calls

class URL:
    def __init__(self,text):self.text=text;self.parts=urlsplit(text)
    def path(self):return self.parts.path
    def query(self):return self.parts.query
    def fragment(self):return self.parts.fragment
    def toString(self):return self.text

class Base:
    def __init__(self):
        self.origin='http://127.0.0.1:4321'
        self.sent=[]
        self.ui_action=NS(emit=lambda *a:self.sent.append(a))
    def url(self):return URL(self.origin+'/')
    def acceptNavigationRequest(self,*a):return False

origin_tree=ast.parse((ROOT/'nexus_launcher/nexus_platform/prototype_host.py').read_text(encoding='utf-8'))
origin_node=next(n for n in origin_tree.body if isinstance(n,ast.FunctionDef) and n.name=='same_origin')
origin_ns={'urlsplit':urlsplit}
exec(compile(ast.Module(body=[origin_node],type_ignores=[]),'actual-origin-function','exec'),origin_ns)
same_origin=origin_ns['same_origin']

# Navigation method body unchanged inside synthetic base container; original Qt not loaded.
container=ast.ClassDef(name='ExtractedPage',bases=[ast.Name(id='Base',ctx=ast.Load())],
                      keywords=[],body=[page_method],decorator_list=[])
module=ast.fix_missing_locations(ast.Module(body=[container],type_ignores=[]))
nav={'Base':Base,'parse_qs':parse_qs,'IDENTIFIER':re.compile(r'^[A-Za-z0-9_-]{1,128}$'),
     'ACTIONS':ACTIONS,'same_origin':same_origin}
exec(compile(module,'actual-navigation-method','exec'),nav)

class ActionTests(unittest.TestCase):
    def test_every_declared_action_dispatches_to_fixture(self):
        for action in sorted(ACTIONS):
            with self.subTest(action=action):
                host,calls=fixture()
                namespace['_action'](host,action,'valid')
                self.assertTrue(calls, action)
    def test_unknown_action_no_effect(self):
        for name in ('unknown','__class__','../../play-server','PLAY-SERVER','',None):
            host,calls=fixture()
            namespace['_action'](host,name,'valid')
            self.assertEqual(calls,[])
    def test_unknown_resource_never_launches_or_mutates(self):
        for action in ('open-build','play-build','select-server','play-server','save-server','pin-server','server-tools'):
            host,calls=fixture()
            namespace['_action'](host,action,'foreign-resource')
            self.assertFalse(set(calls)&{'launch','open','_play','_save_world','_toggle_pin','menu','select_server'})
    def test_navigation_refusal_blocks_launch_and_create(self):
        for action in ('play-build','play-server','create','library','settings','academy'):
            host,calls=fixture(False)
            namespace['_action'](host,action,'valid')
            self.assertEqual(calls,[])
    def test_disabled_play_and_running_game_do_not_launch(self):
        for busy in (False,True):
            host,calls=fixture()
            if busy:host.services.game_process=NS(poll=lambda:None)
            else:host.services.play=NS(isEnabled=lambda:False)
            namespace['_action'](host,'play-server','valid')
            self.assertNotIn('_play',calls)
    def test_navigation_every_action_and_negative_urls(self):
        Page=nav['ExtractedPage']
        for action in ACTIONS:
            p=Page()
            self.assertFalse(p.acceptNavigationRequest(URL(p.origin+'/ui-action/'+action+'?id=valid'),0,True))
            self.assertEqual(p.sent,[(action,'valid')])
        for suffix in ('unknown?id=valid','play-server?id=a&id=b','play-server?id=../x',
                       'play-server?id=','play-server?id='+('a'*129),'play-server?other=valid','play-server?id=valid&','play-server?id=valid&x=1&y=2','play-server?id='+('a'*2048),'play-server?id=a#fragment'):
            p=Page();p.acceptNavigationRequest(URL(p.origin+'/ui-action/'+suffix),0,True)
            self.assertEqual(p.sent,[])
        for origin in ('https://evil.invalid','http://127.0.0.1:4322','http://localhost:4321'):
            p=Page();p.acceptNavigationRequest(URL(origin+'/ui-action/play-server?id=valid'),0,True)
            self.assertEqual(p.sent,[])
        p=Page();p.acceptNavigationRequest(URL(p.origin+'/ui-action/play-server?id=valid'),0,False)
        self.assertEqual(p.sent,[])

if __name__=='__main__':unittest.main()

