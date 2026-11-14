"""Bounded, untrusted placement wishes. Never ranking/publication authority."""
from copy import deepcopy
import math
import re

FORMATS = ('home_hero', 'home_card', 'catalog_card', 'top_banner')


def default_placements(title='Мой сервер', summary=''):
    return dict(version=1, title=title, summary=summary, requested=['catalog_card'],
                formats={name: dict(imageId='', x=50, y=50, zoom=100) for name in FORMATS})


def validate_placements(value):
    if not isinstance(value, dict) or set(value) != {'version','title','summary','requested','formats'}:
        raise ValueError('Некорректные настройки размещений')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Неизвестная версия размещений')
    for key, limit in (('title',80),('summary',220)):
        text = value[key]
        if not isinstance(text,str) or len(text.encode('utf-16-le',errors='surrogatepass'))//2 > limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',text):
            raise ValueError('Некорректный текст размещения')
    requested = value['requested']
    if not isinstance(requested,list) or len(requested)>4 or any(not isinstance(x,str) or x not in FORMATS for x in requested) or len(set(requested))!=len(requested):
        raise ValueError('Некорректный список желаемых размещений')
    formats = value['formats']
    if not isinstance(formats,dict) or set(formats)!=set(FORMATS):
        raise ValueError('Некорректные форматы размещений')
    for crop in formats.values():
        if not isinstance(crop,dict) or set(crop)!= {'imageId','x','y','zoom'}:
            raise ValueError('Некорректное кадрирование')
        identifier = crop['imageId']
        if not isinstance(identifier,str) or len(identifier)>128 or identifier and not re.fullmatch(r'[A-Za-z0-9_-]+',identifier):
            raise ValueError('Некорректный источник обложки')
        for key, low, high in (('x',0,100),('y',0,100),('zoom',100,160)):
            number = crop[key]
            if type(number) not in (int,float) or not math.isfinite(number) or not low<=number<=high:
                raise ValueError('Некорректный масштаб или фокус изображения')
    return deepcopy(value)
