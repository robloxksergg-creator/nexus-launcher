"""Bounded website application data, not package or publication authority."""
from copy import deepcopy
import re
import ipaddress
from urllib.parse import urlsplit
from nexus_launcher.creator_release_plan import validate_release_plan,default_release_plan

PAGE_LIMITS=dict(name=80,summary=220,about=2400,rules=1800,team=1000,address=253,version=40,loader=40,genre=80,website=2048)
SOURCE_LIMITS=dict(html=6000,css=4000,repository=240,ref=120,buildCommand=240,outputDirectory=120)


def _text(value,limit):
    # Server limits use UTF-16 code units. Keep the same boundary for emoji.
    return isinstance(value,str) and len(value.encode('utf-16-le',errors='surrogatepass'))//2<=limit and not re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value)


def public_website(value):
    if not value:return True
    try:
        u=urlsplit(value);host=u.hostname or ''
        if u.scheme!='https' or u.username or u.password or u.port or '.' not in host or re.search(r'(?:^localhost$|\.(?:localhost|local|internal|invalid|test|example)$)',host):return False
        try:ipaddress.ip_address(host);return False
        except ValueError:pass
        return not re.fullmatch(r'[0-9.]+',host) and '[' not in host and '\\' not in value
    except ValueError:return False


def validate_page_content(value,complete=False):
    if not isinstance(value,dict) or set(value)-set(PAGE_LIMITS)-{'cover','accent','theme','mode','source','releasePlan'}:raise ValueError('Некорректные поля страницы')
    if any(not _text(value.get(k),limit) for k,limit in PAGE_LIMITS.items()):raise ValueError('Проверьте длину и содержимое полей страницы')
    if value.get('cover') not in ('city','mountains','meadow') or value.get('accent') not in ('blue','cyan','violet','amber') or value.get('theme') not in ('dark','light') or not public_website(value['website']):raise ValueError('Проверьте оформление и HTTPS-адрес сайта')
    mode=value.get('mode','blocks')
    if mode not in ('blocks','code','github'):raise ValueError('Неизвестный режим страницы')
    if 'releasePlan' in value:validate_release_plan(value['releasePlan'])
    if 'source' in value:
        source=value['source']
        if not isinstance(source,dict) or set(source)!=set(SOURCE_LIMITS) or any(not _text(source.get(k),limit) for k,limit in SOURCE_LIMITS.items()):raise ValueError('Некорректные исходники страницы')
        if mode!='code' and (source['html'] or source['css']) or mode!='github' and any(source[k] for k in ('repository','ref','buildCommand','outputDirectory')):raise ValueError('Исходники не соответствуют режиму')
        if source['repository'] and not re.fullmatch(r'https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/?',source['repository']):raise ValueError('Некорректный репозиторий')
        if source['ref'] and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*',source['ref']):raise ValueError('Некорректная ветка')
        if source['outputDirectory'] and (not re.fullmatch(r'[A-Za-z0-9_./-]+',source['outputDirectory']) or source['outputDirectory'].startswith('/') or '..' in source['outputDirectory'].split('/')):raise ValueError('Некорректный каталог результата')
    if complete:
        if any(not value[k].strip() for k in PAGE_LIMITS if k!='website'):raise ValueError('Заполните обязательные поля страницы')
        source=value.get('source',{})
        if mode=='code' and not source.get('html','').strip() or mode=='github' and not all(source.get(k,'').strip() for k in ('repository','ref','buildCommand','outputDirectory')):raise ValueError('Заполните исходники страницы')
    return deepcopy(value)


def validate_page_draft(value):
    if not isinstance(value,dict) or not isinstance(value.get('id'),str) or not re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}',value['id']):raise ValueError('Некорректный ID заявки')
    if type(value.get('revision')) is not int or not 1<=value['revision']<=2**53-1 or value.get('state') not in ('DRAFT','SUBMITTED') or type(value.get('updatedAt')) is not int or not 0<=value['updatedAt']<=2**53-1 or value.get('submittedAt') is not None and (type(value['submittedAt']) is not int or not 0<=value['submittedAt']<=2**53-1):raise ValueError('Некорректная версия заявки')
    if (value['state']=='DRAFT')!=(value.get('submittedAt') is None):raise ValueError('Некорректное состояние заявки')
    validate_page_content(value.get('content'))
    review=value.get('review')
    if review is not None and (not isinstance(review,dict) or review.get('decision') not in ('APPROVED','CHANGES_REQUESTED','REJECTED') or not _text(review.get('comment'),1000) or type(review.get('createdAt')) is not int):raise ValueError('Некорректный статус проверки')
    return deepcopy(value)


def page_from_project(project,instance):
    fields=project.get('metadata',{})
    value={k:'' for k in PAGE_LIMITS}
    value.update(name=project.get('name',''),summary=fields.get('summary',''),about=project.get('description',''),rules=fields.get('rules',''),team=fields.get('team',''),address=fields.get('address',''),version=instance.minecraft_version,loader=instance.loader,genre=fields.get('category',''),website=fields.get('website',''),cover='mountains',accent='blue',theme='dark',mode='blocks',releasePlan=deepcopy(project.get('releasePlan',default_release_plan())))
    return validate_page_content(value)
