"""Real Chromium composition checks, using local synthetic display state."""
import json
import os
from pathlib import Path

from PySide6.QtTest import QTest
from tests.test_next_shell import candidate  # noqa: F401
from tests.test_design_host import js, wait


def test_home_layout_truthful_state_actions_and_motion(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, _ = candidate
    host = DesignHost(services)
    host.show()
    try:
        wait(app, lambda: bool(js(app, host.page, '!!window.NexusUI')))
        host._sync_state(True)
        state = json.loads(host._last_state)
        state['builds'] = []
        state['recent'] = []
        state['reducedMotion'] = False
        for world in state['worlds']:
            world['saved'] = False
        js(app, host.page, 'window.NexusUI.setState('+json.dumps(state)+')')
        assert js(app, host.page, "document.querySelectorAll('.home-dashboard').length") == 1
        assert js(app, host.page, "document.querySelectorAll('.launchpad-link').length") == 3
        assert js(app, host.page, "document.querySelectorAll('.first-build').length") == 1
        assert js(app, host.page, "Array.from(document.querySelectorAll('.collection-readout strong')).map(n=>n.textContent).join(',')") == '0,0'
        observed = []
        host.page.ui_action.connect(lambda *args: observed.append(args))
        js(app, host.page, "document.querySelector('.launchpad [data-route=downloads]').click()")
        wait(app, lambda: ('downloads', '') in observed)
        wait(app, lambda: host._library_active)
        QTest.qWait(80)
        js(app, host.page, "window.NexusUI.navigate('home')")
        wait(app, lambda: not host._library_active)
        # A new route reveals once; a later status update must not replay it.
        assert js(app, host.page, "document.querySelector('.page').classList.contains('page-enter')")
        js(app, host.page, 'window.NexusUI.setState('+json.dumps(state)+')')
        assert not js(app, host.page, "document.querySelector('.page').classList.contains('page-enter')")
        captures = os.environ.get('NEXUS_HOME_CAPTURE_DIR')
        if captures:Path(captures).mkdir(parents=True, exist_ok=True)
        for width, height in ((1000, 740), (1366, 850), (1920, 1080), (2560, 1440)):
            host.resize(width, height)
            wait(app, lambda: int(js(app, host.page, 'innerWidth')) == host.view.width())
            QTest.qWait(650)
            geometry = json.loads(js(app, host.page, "JSON.stringify({overflow:document.documentElement.scrollWidth>innerWidth,contentOverflow:document.querySelector('#content').scrollWidth>document.querySelector('#content').clientWidth,page:document.querySelector('.page').getBoundingClientRect().width,quick:Array.from(document.querySelectorAll('.launchpad-link')).every(n=>n.getBoundingClientRect().width>140)})"))
            assert not geometry['overflow'] and not geometry['contentOverflow']
            assert geometry['page'] <= 1304
            assert geometry['quick']
            assert js(app,host.page,"(()=>{const p=document.querySelector('.page').getBoundingClientRect(),c=document.querySelector('#content').getBoundingClientRect();return p.width>Math.min(700,c.width-2)&&p.left>=c.left-1&&p.right<=c.right+1})()")
            if captures:
                host.view.update()
                QTest.qWait(150)
                assert host.grab().save(str(Path(captures)/f'home-{width}.png'))
        state['reducedMotion'] = True
        js(app, host.page, 'window.NexusUI.setState('+json.dumps(state)+')')
        assert js(app, host.page, "getComputedStyle(document.querySelector('.home-dashboard')).animationName") == 'none'
        state['builds'] = [{'id':'synthetic-pack','name':'<Сборка игрока>','version':'1.21.1','loader':'fabric','mods':7,'state':'ready','lastPlayed':'2026-11-10T12:00:00Z'}]
        js(app, host.page, 'window.NexusUI.setState('+json.dumps(state)+')')
        assert js(app, host.page, "document.querySelector('.collection-readout strong').textContent") == '1'
        assert js(app, host.page, "document.querySelectorAll('.home-builds .build-row').length") == 1
        assert js(app, host.page, "document.querySelector('.hero h2').textContent") == '<Сборка игрока>'
        assert not host.page.script_errors
    finally:
        host.close()
