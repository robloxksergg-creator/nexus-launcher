"""Local real-window acceptance, without user projects or network access."""
import json
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from nexus_launcher.nexus_platform.learning.studio import CreatorWorkspace
from tests.test_learning_studio import wait, js

app=QApplication([])
out=Path('D:/nexus2/academy-audit-v26');out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='nexus-academy-qa-') as directory:
    workspace=CreatorWorkspace(Path(directory))
    workspace.resize(1280,800);workspace.show()
    wait(app,lambda:workspace.ready)
    wait(app,lambda:js(app,workspace.page,"!document.querySelector('.academy-welcome').hidden"))
    QTest.qWait(400)
    workspace.grab().save(str(out/'onboarding.png'))
    workspace.engine.settings(onboarding_seen=True)
    js(app,workspace.page,'window.NexusCreator.closeWelcome()')
    workspace.start_lesson('first-page')
    wait(app,lambda:workspace.engine.lesson is not None)
    workspace.engine.next()
    results=[]
    for width,height in ((1280,800),(1366,768),(900,650),(640,480)):
        workspace.resize(width,height)
        wait(app,lambda:js(app,workspace.page,'innerWidth')==workspace.view.width())
        QTest.qWait(500)
        workspace.grab().save(str(out/f'lesson-{width}x{height}.png'))
        results.append(js(app,workspace.page,"JSON.stringify({width:innerWidth,height:innerHeight,card:[...document.querySelector('.academy-card').getClientRects()].map(r=>({x:r.x,y:r.y,width:r.width,height:r.height})),highlight:!!document.querySelector('.academy-highlight')})"))
    workspace.resize(1366,900)
    wait(app,lambda:js(app,workspace.page,'innerWidth')==workspace.view.width())
    workspace.open_academy()
    wait(app,lambda:js(app,workspace.page,"!document.querySelector('.academy-panel').hidden"))
    QTest.qWait(500)
    workspace.grab().save(str(out/'academy.png'))
    js(app,workspace.page,"document.querySelector('.academy-panel details').open=true")
    QTest.qWait(500);workspace.grab().save(str(out/'learning-settings.png'))
    (out/'visual-results.json').write_text(json.dumps({'layouts':results,'scriptErrors':workspace.page.script_errors},indent=2),encoding='utf-8')
    assert not workspace.page.script_errors
    workspace.shutdown();workspace.close()
