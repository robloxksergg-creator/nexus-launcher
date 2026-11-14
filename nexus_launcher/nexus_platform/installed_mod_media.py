"""Bounded background metadata/icon lookup for installed Modrinth projects."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject,Signal
from .catalog_provider import CatalogProvider
from .mod_media import safe_image,fetch_media


class InstalledModMedia(QObject):
    updated=Signal(str,object)
    received=Signal(str,object)
    def __init__(self,parent=None):
        super().__init__(parent);self.cache={};self.pending=set();self.closed=False
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='installed-icons')
        self.provider=CatalogProvider();self.received.connect(self._receive)
    def request(self,project):
        if self.closed or not project or project.startswith('local:') or project in self.cache or project in self.pending or len(self.pending)>=64:return
        self.pending.add(project);self.pool.submit(self._work,project)
    def _work(self,project):
        try:
            metadata=self.provider.project(project);url=metadata.get('icon_url','')
            data=fetch_media(url,cancelled=lambda:self.closed,max_bytes=1024*1024) if safe_image(url) else b''
            result={'title':str(metadata.get('title',''))[:160],'icon':data}
        except Exception:result={'title':'','icon':b''}
        try:self.received.emit(project,result)
        except RuntimeError:pass
    def _receive(self,project,result):
        self.pending.discard(project)
        if self.closed:return
        if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
        self.cache[project]=result;self.updated.emit(project,result)
    def shutdown(self):
        self.closed=True;self.pool.shutdown(wait=False,cancel_futures=True)
