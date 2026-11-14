"""Bounded combined resolution before consent or any file mutation."""
from copy import deepcopy
import time
from nexus_launcher.modrinth_provider import ModrinthProvider, ProviderError


def resolve_batch(provider, projects, game_version, loader):
    if not isinstance(projects,(list,tuple)) or not 1<=len(projects)<=20 or any(not isinstance(p,str) or not p or len(p)>128 for p in projects):
        raise ProviderError('Выберите от 1 до 20 модов.')
    cache={};deadline=time.monotonic()+45
    def fetch(key,read):
        if time.monotonic()>deadline:raise ProviderError('Истекло время проверки выбранных модов.')
        if key not in cache:
            if len(cache)>=64:raise ProviderError('Слишком много зависимостей для одной установки.')
            cache[key]=read()
        if time.monotonic()>deadline:raise ProviderError('Истекло время проверки выбранных модов.')
        return deepcopy(cache[key])
    class SharedProvider(ModrinthProvider):
        def versions(self,project,game,kind):return fetch(('project',project,game,kind),lambda:provider.versions(project,game,kind))
        def version(self,key):return fetch(('version',key),lambda:provider.version(key))
    shared=SharedProvider();merged={};by_project={}
    for project in dict.fromkeys(projects):
        for version in shared.resolve(project,game_version,loader):
            key=version['id'];identity=version['project_id']
            if identity in by_project and by_project[identity]!=key:
                raise ProviderError('Выбранные моды требуют разные версии одного проекта. Измените выбор; файлы не устанавливались.')
            by_project[identity]=key
            if key in merged:
                merged[key]['required_by']=list(dict.fromkeys(merged[key].get('required_by',[])+version.get('required_by',[])))
            else:merged[key]=version
    return list(merged.values())


def resolve_exact(provider,project_id,version_id,game_version,loader):
    root=provider.version(version_id)
    if (root.get('id')!=version_id or root.get('project_id')!=project_id or
            loader not in root.get('loaders',[]) or game_version not in root.get('game_versions',[])):
        raise ProviderError('Выбранная версия не совместима с этой сборкой или относится к другому моду.')
    class ExactProvider(ModrinthProvider):
        def versions(self,project,game,kind):
            return [deepcopy(root)] if project==project_id else provider.versions(project,game,kind)
        def version(self,key):return deepcopy(root) if key==version_id else provider.version(key)
    plan=ExactProvider().resolve(project_id,game_version,loader)
    identities={}
    for version in plan:
        identity=version['project_id']
        if identity in identities and identities[identity]!=version['id']:
            raise ProviderError('Конфликт версий зависимостей. Установка не начиналась.')
        identities[identity]=version['id']
    return plan
