"""Local project/application association and explicit, version-fenced network actions."""
from copy import deepcopy
import json
import uuid
from nexus_launcher.safe_paths import checked_path
from nexus_launcher.user_instances import atomic_json
from nexus_launcher.update_state import update_lock
from nexus_launcher.creator_page_contract import validate_page_content


class CreatorPageWorkspace:
    def __init__(self,client,profile,service,identifier):
        self.client,self.profile,self.service,self.identifier=client,profile,service,identifier
        self.path=checked_path(service.instances.path_for(identifier),'.nexus/website-application.json')
        self.item=None
        self.link=None
        self.loaded=False
        self.unknown=False
        self.available=[]

    def _read_link(self):
        if not self.path.exists():return None
        if self.path.stat().st_size>1024:raise ValueError('Повреждена привязка заявки. Автоматическая замена запрещена.')
        value=json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or set(value)!={'accountId','id'} or not isinstance(value.get('accountId'),str) or not 1<=len(value['accountId'])<=128 or not isinstance(value.get('id'),str) or str(uuid.UUID(value['id'],version=4))!=value['id']:
            raise ValueError('Повреждена привязка заявки. Автоматическая замена запрещена.')
        if value['accountId']!=self.profile.user_id:raise ValueError('Этот проект связан с заявкой другого аккаунта. Используйте его исходный аккаунт.')
        return value

    def load(self):
        # A verified read is mandatory on each dialog open/recovery, including a pending local ID.
        self.loaded=False
        link=self._read_link()
        items=self.client.creator_pages(self.profile)
        self.available=deepcopy(items)
        self.item=next((v for v in items if link and v['id']==link['id']),None)
        self.link=link
        self.loaded=True
        self.unknown=False
        return deepcopy(self.item)

    def attach(self,identifier):
        if not self.loaded or self.unknown or self.link is not None:raise ValueError('Сначала обновите данные. Проект уже связан с заявкой.')
        self.service.capabilities.require_creator()
        item=next((v for v in self.available if v['id']==identifier),None)
        if item is None:raise ValueError('Заявка не найдена в текущем аккаунте.')
        link={'accountId':self.profile.user_id,'id':identifier}
        with update_lock(checked_path(self.path.parent,'website-link-guard')):
            if self._read_link() is not None:raise ValueError('Привязка уже создана другой операцией. Обновите данные.')
            atomic_json(self.path,link)
        self.link=link
        self.item=deepcopy(item)
        return deepcopy(item)

    def write(self,action,content=None,rights=False):
        if not self.loaded or self.unknown:raise ValueError('Сначала обновите сохранённые данные кабинета.')
        self.service.capabilities.require_creator()
        if action not in ('save','submit','reopen'):raise ValueError('Недопустимое действие')
        if action=='save':
            validate_page_content(content)
            if self.item and self.item['state']!='DRAFT':raise ValueError('Сначала отзовите заявку для правок.')
        elif not self.item:raise ValueError('Сначала сохраните черновик.')
        elif action=='submit':
            if self.item['state']!='DRAFT' or rights is not True:raise ValueError('Подтвердите права на материалы.')
            validate_page_content(self.item['content'],True)
        elif self.item['state']!='SUBMITTED':raise ValueError('Заявка не находится на проверке.')
        # Separate per-project guard; never acquire the launcher's update/install lock.
        with update_lock(checked_path(self.path.parent,'website-link-guard')):
            stored=self._read_link()
            if self.link is not None and stored!=self.link:raise ValueError('Привязка заявки изменилась. Обновите данные.')
            if self.link is None:
                link=stored or {'accountId':self.profile.user_id,'id':str(uuid.uuid4())}
                # Persist a stable ID BEFORE dispatch, including concurrent launcher processes.
                if stored is None:atomic_json(self.path,link)
                self.link=link
        body={'id':self.link['id'],'revision':self.item['revision'] if self.item else 0,'action':'create' if action=='save' and not self.item else action}
        if action=='save':body['content']=deepcopy(content)
        if action=='submit':body['rightsConfirmed']=True
        if len(json.dumps(dict(body,accountId=self.profile.user_id),ensure_ascii=False).encode('utf-8'))>24000:
            raise ValueError('Общий размер заявки превышает 24 КБ. Сократите тексты.')
        self.unknown=True
        try:
            result=self.client.creator_pages(self.profile,body)
        except Exception:
            # A read must reconcile all failures; never blindly retry a save or a submission.
            raise
        self.item=result
        self.unknown=False
        return deepcopy(result)
