from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from nexus_launcher.nexus_platform.prototype_host import AssetServer, same_origin


def test_navigation_command_whitelist():
    from nexus_launcher.nexus_platform.prototype_host import COMMANDS
    assert COMMANDS == {"login", "register", "services", "packs", "mods", "sound-on", "sound-off", "library-leave"}
    assert not COMMANDS.intersection({"exec", "eval", "readFile", "install", "setManifest"})


def test_origin_is_exact():
    assert same_origin("http://127.0.0.1:42/#packs", "http://127.0.0.1:42")
    for value in ("https://127.0.0.1:42", "http://127.0.0.1:43", "file:///etc/passwd", "http://evil.example:42", "http://127.0.0.1:999999"):
        assert not same_origin(value, "http://127.0.0.1:42")


def test_static_server_only_exposes_approved_assets():
    server = AssetServer()
    try:
        with urlopen(server.origin + "/", timeout=3) as response:
            assert b"Launcher Design Preview" in response.read()
        with urlopen(server.origin + "/gearmorph-official.png", timeout=3) as response:
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"
        for path in ("/../launcher.json", "/launcher_core.py", "/api/launch", "/index.html"):
            with pytest.raises(HTTPError) as error:
                urlopen(server.origin + path, timeout=3)
            assert error.value.code == 404
    finally:
        server.close()


def test_renderer_dispatches_only_fixed_service_commands(monkeypatch, tmp_path):
    import time
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.nexus_platform.prototype_host import PrototypeHost

    class Services:
        calls = []
        library_calls = []

        def show_instances(self):
            self.library_calls.append('packs')

        @property
        def instances_page(self):
            return self

        def open_mod_catalog(self):
            self.library_calls.append('mods')

        def showMaximized(self):
            self.calls.append("services")

        def raise_(self):
            pass

        def close(self):
            pass

        def _login_account(self):
            self.calls.append('login')

        def _register_account(self):
            self.calls.append('register')

    app = QApplication.instance() or QApplication([])
    services = Services()
    host = PrototypeHost(services)
    assert not host.windowIcon().isNull()
    assert not host.windowIcon().pixmap(32, 32).isNull()
    loaded = QSignalSpy(host.view.loadFinished)
    try:
        host.show()
        # Process events without holding Python's GIL across a C++ signal wait:
        # the asset server must also execute Python on its own thread.
        deadline = time.monotonic() + 10
        while not loaded.count() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert loaded.count()
        assert loaded.at(loaded.count() - 1)[0] is True
        host.raise_()
        host.activateWindow()
        QTest.qWait(500)
        host.page.runJavaScript("""(()=>{
          const box=document.createElement('div');
          box.style.cssText='position:fixed;left:0;top:0;height:100px;width:100px;overflow:auto;z-index:9999';
          const fill=document.createElement('div');fill.style.height='2000px';box.append(fill);document.body.append(box);
          box.scrollTo({top:120,behavior:'smooth'});
          setTimeout(()=>window.scrollMiddle=box.scrollTop,100);
          setTimeout(()=>{window.scrollTest={middle:window.scrollMiddle,end:box.scrollTop};box.remove()},1000);
        })()""")
        scroll_result = []
        deadline = time.monotonic() + 3
        while not scroll_result and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
            host.page.runJavaScript('window.scrollTest ? JSON.stringify(window.scrollTest) : null',
                                   lambda value: scroll_result.append(value) if value else None)
        import json
        assert scroll_result
        scroll_values = json.loads(scroll_result[0])
        assert 0 <= scroll_values['middle'] <= 120
        assert scroll_values['end'] == 120
        from types import SimpleNamespace
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage, QColor
        image = QImage(64, 64, QImage.Format_ARGB32)
        image.fill(QColor('#ee4422'))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, 'PNG')
        services.account_profile = SimpleNamespace(skin_png=bytes(buffer.data()), skin_model='slim')
        host._sync_skin(force=True)
        QTest.qWait(200)
        skin_result = []
        host.page.runJavaScript("""JSON.stringify((()=>{
          showProfileSpace('overview');
          const card=document.querySelector('.skin-preview');
          const colored=card.querySelector('canvas').getContext('2d').getImageData(2,2,1,1).data[0]===238;
          const slim=card.querySelector('[role=status]').textContent.includes('Тонкие');
          const rotate=card.querySelector('input');rotate.value=90;rotate.dispatchEvent(new Event('input'));
          const rotation=card.querySelector('.skin-model').style.transform.includes('90deg');
          rotate.value=180;rotate.dispatchEvent(new Event('input'));
          for(let i=0;i<200;i++)rotate.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));
          const unlimited=card.querySelector('.skin-model').style.transform.includes('1180deg');
          card.querySelector('input[value=classic]').click();
          const unit=Number(card.querySelector('.skin-model').style.getPropertyValue('--skin-unit'));
          const classic=parseFloat(getComputedStyle(card.querySelectorAll('.skin-part')[3].querySelector('canvas')).width)===4*unit;
          card.querySelector('input[value=slim]').click();
          const thin=parseFloat(getComputedStyle(card.querySelectorAll('.skin-part')[3].querySelector('canvas')).width)===3*unit;
          showProfileSpace('about');
          const retained=document.querySelector('.skin-preview input[value=slim]').checked;
          return {colored,slim,rotation,unlimited,classic,thin,retained,avatar:!!document.querySelector('.skin-avatar canvas')};
        })())""", skin_result.append)
        for _ in range(1000):
            QTest.qWait(10)
            if skin_result:
                break
        import json
        assert skin_result, host.page.script_errors
        assert all(json.loads(skin_result[0]).values()), skin_result
        services.account_profile = None
        host._sync_skin(force=True)
        QTest.qWait(50)
        grey_result = []
        host.page.runJavaScript("document.querySelector('.skin-preview [role=status]').textContent.includes('серая')", grey_result.append)
        for _ in range(100):
            QTest.qWait(10)
            if grey_result:
                break
        assert grey_result == [True]
        host.page.runJavaScript('NexusDiscovery.showHome(false)')
        QTest.qWait(50)
        host.page.runJavaScript("location.href='/desktop-command/services'")
        for _ in range(50):
            QTest.qWait(20)
            if services.calls:
                break
        assert services.calls == ["services"]
        host.page.runJavaScript("location.href='/desktop-command/eval?code=anything'")
        QTest.qWait(200)
        assert services.calls == ["services"]
        assert host.profile.isOffTheRecord()
        from PySide6.QtCore import Qt
        assert host.view.contextMenuPolicy() == Qt.NoContextMenu
        host.page.runJavaScript("openCatalog()")
        # Wait for the actual async bridge result, yielding Python's GIL so
        # the local asset server can run under concurrent build/test load.
        deadline = time.monotonic() + 5
        while services.library_calls[-2:] != ['packs', 'mods'] and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert services.library_calls[-2:] == ['packs', 'mods']
        from PySide6.QtWebEngineCore import QWebEngineSettings
        assert host.page.settings().testAttribute(QWebEngineSettings.FullScreenSupportEnabled)
        layout_result = []
        host.page.runJavaScript("""JSON.stringify((()=>{
          const home=!document.querySelector('#discover-home').hidden;
          const viewer=!NexusProjectAccess.canEdit()&&editButton.hidden;
          document.querySelector('#server-layout-settings').click();
          const deniedClosed=!document.querySelector('.server-layout-dialog').open;
          const entry={id:'layout-test',name:'Local draft',version:'1.21.1',loader:'Fabric',mods:[],purpose:'Для себя'};
          packLibrary.push(entry);projectContexts.set(entry.id,newPackPresentation(entry));activateProject(entry.id);
          const open=document.querySelector('#server-layout-settings');open.click();
          const dialog=document.querySelector('.server-layout-dialog');const opened=dialog.open;
          const ads=document.querySelector('#zone-setting-ads');ads.checked=false;ads.dispatchEvent(new Event('input'));
          Array.from(dialog.querySelectorAll('button')).find(b=>b.textContent==='Применить').click();
          const saved=!document.querySelector('.server-ad-zone').offsetHeight;
          open.click();const retained=!document.querySelector('#zone-setting-ads').checked;
          document.querySelector('#zone-setting-mainColor').value='#334455';
          document.querySelector('#zone-setting-mainColor').dispatchEvent(new Event('input'));
          Array.from(dialog.querySelectorAll('button')).find(b=>b.textContent==='Отмена').click();
          const cancelled=backgroundSaved.desktopLayout.mainColor==='#10151e';
          const stored=projectContexts.get(activeProject).settings.desktopLayout.ads===false;
          openPackPage(entry);
          const privateFullWidth=getComputedStyle(document.querySelector('.server-presentation')).display==='block';
          worldView='discover';serverSearch='Gearmorph';showWorldsSpace();
          const catalogue=worldsSpace.querySelectorAll('.world-server-card').length===1;
          worldsSpace.querySelector('.world-card-open').click();
          const openedFromSearch=!overview.hidden&&worldsSpace.hidden;
          const merged=document.querySelector('.server-information .server-author-zone')!==null;
          const ownerHidden=editButton.hidden;
          return {home,viewer,deniedClosed,opened,saved,retained,cancelled,stored,merged,ownerHidden,catalogue,openedFromSearch,privateFullWidth};
        })())""", layout_result.append)
        for _ in range(100):
            QTest.qWait(10)
            if layout_result:
                break
        import json
        assert all(json.loads(layout_result[0]).values())
        polish_result = []
        host.page.runJavaScript("""JSON.stringify((()=>{
          worldView='discover';showWorldsSpace();
          const noViewButton=![...worldsSpace.querySelectorAll('button')].some(b=>b.textContent==='Посмотреть');
          const semantic=!!worldsSpace.querySelector('button.world-card-open[aria-label]');
          worldsSpace.querySelector('.block-actions button').click();
          const independent=!worldsSpace.hidden&&overview.hidden;
          showProfileSpace('overview');
          const joined=!!profileSpace.querySelector('.profile-identity .profile-nav');
          profileSpace.style.minHeight='2000px';scrollTo(0,150);const before=scrollY;
          showProfileSpace('about');
          const scrollKept=before>0&&scrollY===before;
          const animated=profileSpace.querySelector('.profile-panel').classList.contains('profile-enter');
          const invalid=!!NexusBannerMedia.validate({type:'video/mp4',size:0});
          const tooLarge=!!NexusBannerMedia.validate({type:'video/webm',size:201*1024*1024});
          NexusDiscovery.openServer();
          return {noViewButton,semantic,joined,animated,invalid,tooLarge,independent,scrollKept};
        })())""", polish_result.append)
        for _ in range(100):
            QTest.qWait(10)
            if polish_result:
                break
        assert all(json.loads(polish_result[0]).values())
        host.page.runJavaScript("activeSettingsSection='general';renderSettingsSection();document.querySelector('#persistent-interface-sound').click()")
        for _ in range(100):
            QTest.qWait(10)
            if host.server.preferences.path.exists():
                break
        assert not host.server.preferences.sound_enabled()
        restarted = AssetServer()
        try:
            assert b'window.NexusInitialSound=false;' in restarted.assets['/'][0]
        finally:
            restarted.close()
        import base64
        from pathlib import Path
        fixture = base64.b64encode((Path(__file__).parent / 'fixtures/banner-vp8.webm').read_bytes()).decode('ascii')
        host.page.runJavaScript("""window.bannerTestResult=null;(async()=>{
          try{
            activateProject('layout-test');document.querySelector('#server-layout-settings').click();
            const dialog=document.querySelector('.server-layout-dialog'),input=document.querySelector('#creator-banner-file');
            const bytes=Uint8Array.from(atob('__B64__'),char=>char.charCodeAt(0));
            const transfer=new DataTransfer();transfer.items.add(new File([bytes],'test.webm',{type:'video/webm'}));input.files=transfer.files;
            await input.onchange();
            const decoded=!!dialog.querySelector('video.banner-media-preview');
            [...dialog.querySelectorAll('button')].find(button=>button.textContent==='Применить').click();
            const applied=backgroundSaved.desktopLayout.banner?.kind==='video';
            const video=previewBoard.querySelector('.banner-video');
            const controls=!!video&&video.muted&&video.loop&&!!previewBoard.querySelector('.banner-pause')&&!!previewBoard.querySelector('.banner-fullscreen');
            const saved=backgroundSaved.desktopLayout.banner?.url;
            document.querySelector('#server-layout-settings').click();
            const bad=document.querySelector('#creator-banner-file'),broken=new DataTransfer();
            broken.items.add(new File([new Uint8Array([1,2,3])],'broken.webm',{type:'video/webm'}));bad.files=broken.files;
            await bad.onchange();
            const rejected=[...dialog.querySelectorAll('[role=status]')].some(node=>node.textContent.includes('Не удалось открыть'));
            [...dialog.querySelectorAll('button')].find(button=>button.textContent==='Отмена').click();
            const cancelled=backgroundSaved.desktopLayout.banner.url===saved;
            NexusDiscovery.openServer(false);window.bannerTestResult={decoded,applied,controls,rejected,cancelled};
          }catch(error){window.bannerTestResult={error:String(error)};}
        })();""".replace('__B64__', fixture))
        banner_result = []
        for _ in range(500):
            QTest.qWait(20)
            if not banner_result:
                host.page.runJavaScript('window.bannerTestResult?JSON.stringify(window.bannerTestResult):null', lambda value: banner_result.append(value) if value else None)
            else:
                break
        assert banner_result
        assert json.loads(banner_result[0]) == {'decoded': True, 'applied': True, 'controls': True, 'rejected': True, 'cancelled': True}
        host.page.runJavaScript('history.back()')
        QTest.qWait(250)
        back_result = []
        host.page.runJavaScript("!worldsSpace.hidden && overview.hidden && history.state.nexusView==='server-catalog'", back_result.append)
        for _ in range(100):
            QTest.qWait(10)
            if back_result:
                break
        assert back_result == [True]
        host.page.runJavaScript('history.forward()')
        QTest.qWait(250)
        forward_result = []
        host.page.runJavaScript("worldsSpace.hidden && !overview.hidden && history.state.nexusView==='server-page'", forward_result.append)
        for _ in range(100):
            QTest.qWait(10)
            if forward_result:
                break
        assert forward_result == [True]
        auth_result = []
        host.page.runJavaScript("""JSON.stringify((()=>{
          const entry=document.querySelector('#desktop-account-login');
          entry.click();const dialog=document.querySelector('.desktop-auth-choice');
          const open=dialog.open;const options=dialog.querySelectorAll('[data-auth-command]').length;
          const footer=!!entry.closest('.sidebar');
          const duplicates=Array.from(document.querySelectorAll('.topbar button')).some(b=>['Войти','Регистрация'].includes(b.textContent));
          dialog.close();return {open,options,footer,duplicates};
        })())""", auth_result.append)
        for _ in range(100):
            QTest.qWait(10)
            if auth_result:
                break
        import json
        assert json.loads(auth_result[0]) == {'open': True, 'options': 2, 'footer': True, 'duplicates': False}
        border_result = []
        host.page.runJavaScript("""JSON.stringify((()=>{
          const app=document.querySelector('.app');
          const initial=app.classList.contains('play-border-enabled');
          activeSettingsSection='general';renderSettingsSection();
          const input=document.querySelector('#desktop-play-border');
          input.click();const disabled=!app.classList.contains('play-border-enabled');
          renderSettingsSection();const retained=!document.querySelector('#desktop-play-border').checked;
          document.querySelector('#desktop-play-border').click();
          return {initial,disabled,retained,restored:app.classList.contains('play-border-enabled')};
        })())""", border_result.append)
        for _ in range(100):
            QTest.qWait(10)
            if border_result:
                break
        import json
        assert all(json.loads(border_result[0]).values())
        from PySide6.QtCore import Qt
        assert host.windowFlags() & Qt.FramelessWindowHint
        assert host.title_bar.height() == 36
        for width, height in ((1280, 720), (2560, 1080), (3840, 2160), (640, 600)):
            host.resize(width, height)
            QTest.qWait(150)
            profile_geometry = []
            host.page.runJavaScript("""JSON.stringify((()=>{
                showProfileSpace('overview');
                const panel=profileSpace.querySelector('.profile-panel');
                const normalHeight=panel.getBoundingClientRect().height<440;
                const noOverflow=document.documentElement.scrollWidth<=innerWidth+1;
                const tabs=profileSpace.querySelector('.profile-nav');
                const oneMarker=getComputedStyle(tabs.querySelector('button')).borderBottomWidth==='0px';
                return {normalHeight,noOverflow,oneMarker};
            })())""", profile_geometry.append)
            for _ in range(1000):
                QTest.qWait(10)
                if profile_geometry:
                    break
            assert all(json.loads(profile_geometry[0]).values()), profile_geometry
            home_geometry = []
            host.page.runJavaScript("""JSON.stringify((()=>{
                NexusDiscovery.showHome(false);
                const home=document.querySelector('#discover-home');
                const visible=!home.hidden;
                const overflow=document.documentElement.scrollWidth>innerWidth+1;
                home.querySelectorAll('.discover-playlist button')[1].click();
                const selected=home.querySelector('.discover-caption h2').textContent==='Технологии и экспедиции';
                NexusDiscovery.openServer(false);
                return {visible,overflow,selected};
            })())""", home_geometry.append)
            for _ in range(100):
                QTest.qWait(10)
                if home_geometry:
                    break
            import json
            assert json.loads(home_geometry[0]) == {'visible': True, 'overflow': False, 'selected': True}
            result = []
            host.page.runJavaScript("""JSON.stringify((()=>{
                const board=document.querySelector('.canvas-preview .artboard');
                const play=board.querySelector('.play-node');
                const b=board.getBoundingClientRect(),p=play.getBoundingClientRect();
                return {height:b.height,playInside:p.bottom<=b.bottom+1,
                    overflow:document.documentElement.scrollWidth>innerWidth+1};
            })())""", result.append)
            for _ in range(100):
                QTest.qWait(10)
                if result:
                    break
            import json
            geometry = json.loads(result[0])
            assert geometry['playInside']
            assert not geometry['overflow']
            if width > 1050:
                assert geometry['height'] <= 680
            if width == 2560:
                host.grab().save('deliverables/desktop-v5-wide.png')
        QTest.mouseClick(host.title_bar.maximize, Qt.LeftButton)
        QTest.qWait(50)
        assert host.isMaximized()
        assert all(not edge.isVisible() for edge in host.resize_edges)
        QTest.mouseClick(host.title_bar.maximize, Qt.LeftButton)
        QTest.qWait(120)
        assert not host.isMaximized()
        assert all(edge.isVisible() for index, edge in enumerate(host.resize_edges) if index != 5)
        assert not host.resize_edges[5].isVisible()  # Close control owns this corner.
        assert host.width() <= host.screen().availableGeometry().width()
        QTest.mouseDClick(host.title_bar, Qt.LeftButton)
        QTest.qWait(50)
        assert host.isMaximized()
        host.showFullScreen()
        QTest.qWait(50)
        assert not host.title_bar.isVisible()
        host.showNormal()
        QTest.qWait(50)
        assert host.title_bar.isVisible()
        host.page.runJavaScript("document.querySelector('#desktop-account-login').click()")
        QTest.qWait(100)
        host.grab().save('deliverables/desktop-v7-auth-choice.png')
        host.view.setFocus()
        QTest.keyClick(host.view.focusProxy() or host.view, Qt.Key_Escape)
        QTest.qWait(100)
        dismissed = []
        host.page.runJavaScript("!document.querySelector('.desktop-auth-choice').open", dismissed.append)
        for _ in range(100):
            QTest.qWait(10)
            if dismissed:
                break
        assert dismissed == [True]
    finally:
        host.close()
        app.processEvents()
