"""Offline Qt/Chromium skin geometry and visual regression, synthetic PNG only."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QIODevice, QTimer, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-js', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    class Offline(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            if info.requestUrl().scheme() not in ('data', 'about'):
                info.block(True)
    profile = QWebEngineProfile()
    blocker = Offline(profile)
    profile.setUrlRequestInterceptor(blocker)
    page = QWebEnginePage(profile)
    view = QWebEngineView()
    view.setPage(page)
    view.resize(1120, 790)
    view.show()
    def wait_until(call, timeout=15000):
        loop = QEventLoop()
        result = []
        timer = QTimer()
        timer.setInterval(60)
        def tick():
            call(lambda value: (result.append(value), loop.quit()) if value else None)
        timer.timeout.connect(tick)
        timer.start()
        QTimer.singleShot(timeout, loop.quit)
        loop.exec()
        timer.stop()
        if not result:
            raise AssertionError('Browser condition timed out')
        return result[-1]
    def js(code):
        return wait_until(lambda done: page.runJavaScript(code, done))
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(QColor('transparent'))
    # Real 1-texel edges, transparent outer layer, no user's account or skin.
    for y in range(64):
        for x in range(64):
            if y < 32 and (x < 32 or y >= 16):
                image.setPixelColor(x, y, QColor('#edb85f' if (x+y) % 2 else '#4b235c'))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, 'PNG')
    png = base64.b64encode(bytes(buffer.data())).decode('ascii')
    css = (root/'assets/approved-ui/skin-preview.css').read_text(encoding='utf-8')
    old = Path(args.baseline_js).read_text(encoding='utf-8')
    new = (root/'assets/approved-ui/skin-preview.js').read_text(encoding='utf-8')
    frames = []
    for name, script in [('before', old), ('after', new)]:
        doc = '<style>body{margin:0;font:14px Arial;color:#edf4ff;background:#10161f}'+css+'</style><div id="target"></div><script>'+script+'</script><script>NexusSkin.mount(document.querySelector("#target"));NexusSkin.setProfile('+json.dumps({'png':png,'model':'classic'})+');</script>'
        import html
        frames.append('<section><h2>'+name+'</h2><iframe id="'+name+'" srcdoc="'+html.escape(doc, quote=True)+'"></iframe></section>')
    page.setHtml('<style>body{margin:12px;background:#0a0e14;color:white;font:14px Arial;display:flex;gap:16px}section{flex:1;min-width:0}iframe{width:100%;height:700px;border:0}h2{font-size:16px}</style>'+''.join(frames), QUrl('about:blank'))
    js('(()=>{const a=document.querySelector("#after")?.contentDocument,b=document.querySelector("#before")?.contentDocument;return a?.querySelectorAll(".skin-part").length===12&&b?.querySelectorAll(".skin-part").length===12})()')
    results = []
    def check(expression):
        value = js('JSON.stringify((()=>{const d=document.querySelector("#after").contentDocument;'+expression+'})())')
        data = json.loads(value)
        assert data['pass'], data
        results.append(data)
    check('const f=d.querySelector(".skin-front"),m=d.querySelector(".skin-model");return {case:"display-sized geometry",pass:parseFloat(getComputedStyle(f).width)===64&&Math.abs(new DOMMatrix(getComputedStyle(m).transform).a)<=1,width:getComputedStyle(f).width};')
    check('const f=d.querySelector(".skin-front"),c=f.getContext("2d");return {case:"nearest texels",pass:c.imageSmoothingEnabled===false&&c.getImageData(0,0,1,1).data[3]===255};')
    # Let compositor present the current frame before capture.
    js('new Boolean(true).valueOf()')
    assert view.grab().save(str(out/'comparison.png'))
    check('const z=d.querySelector("input[aria-label=\"Масштаб персонажа\"]");z.value=10;z.dispatchEvent(new Event("input"));return {case:"zoom geometry",pass:parseFloat(getComputedStyle(d.querySelector(".skin-front")).width)===80};')
    check('const a=d.querySelector("input[value=slim]");a.checked=true;a.dispatchEvent(new Event("change"));return {case:"slim arm",pass:parseFloat(getComputedStyle(d.querySelectorAll(".skin-part")[4].querySelector("canvas")).width)===30};')
    check('const t=d.querySelector("input[aria-label=\"Поворот персонажа\"]");t.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true}));return {case:"keyboard rotation",pass:Math.abs(Number(t.value)+20)<0.1};')
    check('document.querySelector("#after").contentWindow.NexusSkin.setProfile({png:null,model:"classic"});return {case:"neutral model",pass:d.querySelectorAll(".skin-part").length===6&&d.querySelector("[role=status]").textContent.includes("Скин отсутствует")};')
    view.resize(390, 790)
    js('document.querySelector("#before").parentElement.style.display="none";true')
    check('const s=d.querySelector(".skin-stage");return {case:"narrow viewport",pass:s.getBoundingClientRect().width>150&&d.querySelector("input[type=range]").getBoundingClientRect().right<=d.documentElement.clientWidth};')
    assert view.grab().save(str(out/'narrow.png'))
    (out/'result.json').write_text(json.dumps({'checks':results,'device_pixel_ratio':view.devicePixelRatioF(),'scope':'Qt Chromium, synthetic PNG; no account/server/game'},indent=2),encoding='utf8')
    print(json.dumps({'checks_passed':len(results),'scope':'offline synthetic renderer'}))
    view.close()
    page.deleteLater()
    app.processEvents()
    return 0


if __name__ == '__main__':
    sys.exit(main())
