"""Display-only projection. Remote entries never become install authority."""
import re
import uuid


def validate_creator_catalogue(value):
    if not isinstance(value, dict) or not isinstance(value.get('items'), list) or len(value['items']) > 50:
        raise ValueError('Некорректный каталог сообщества')
    cursor = value.get('next')
    if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r'community-[a-z0-9-]{1,70}', cursor)):
        raise ValueError('Некорректная страница каталога')
    output, seen = [], set()
    for row in value['items']:
        if not isinstance(row, dict) or not isinstance(row.get('id'),str):
            raise ValueError('Некорректная запись')
        try:
            identifier = str(uuid.UUID(row['id']))
        except ValueError as error:
            raise ValueError('Некорректный ID') from error
        if identifier != row['id'] or identifier in seen:
            raise ValueError('Повторяющийся ID')
        seen.add(identifier)
        clean = {'id':identifier}
        for field, limit in [('slug',80),('name',80),('summary',220),('genre',80),('version',40),('loader',40)]:
            text = row.get(field)
            if not isinstance(text,str) or len(text)>limit or any(ord(c)<32 for c in text):
                raise ValueError('Некорректное поле каталога')
            clean[field] = text
        if not re.fullmatch(r'community-[a-z0-9-]{1,70}',clean['slug']) or row.get('access') not in ('PUBLIC','PAID','PRIVATE'):
            raise ValueError('Некорректный доступ или адрес')
        if row.get('downloadEnabled') is not False:
            raise ValueError('Каталог не является разрешением на установку')
        website = row.get('website')
        if website is not None and website != '/servers/'+clean['slug']:
            raise ValueError('Неподтверждённая ссылка')
        clean.update(access=row['access'],website=website,downloadEnabled=False)
        output.append(clean)
    return {'items':output,'next':cursor}
