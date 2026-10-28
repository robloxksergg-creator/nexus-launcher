"""Immutable discovery filters and API facet construction, independent of Qt."""
from dataclasses import dataclass, replace
import json
import re


ENVIRONMENTS = {
    '': 'Любая среда',
    'client_and_server': 'Клиент и сервер',
    'client_only': 'Только клиент',
    'client_only_server_optional': 'Клиент · сервер необязателен',
    'singleplayer_only': 'Одиночная игра',
    'server_only': 'Только сервер',
    'server_only_client_optional': 'Сервер · клиент необязателен',
    'dedicated_server_only': 'Выделенный сервер',
    'client_or_server': 'Клиент или сервер',
    'client_or_server_prefers_both': 'Клиент или сервер · лучше вместе',
    'unknown': 'Среда не указана',
}
SORTS = {'relevance': 'Релевантность', 'downloads': 'Скачивания',
         'follows': 'Подписчики', 'newest': 'Новые', 'updated': 'Обновлённые'}


@dataclass(frozen=True)
class ModrinthFilterState:
    project_type: str = 'mod'
    versions: tuple[str, ...] = ()
    loaders: tuple[str, ...] = ()
    environment: str = ''
    categories: tuple[str, ...] = ()
    open_source: bool | None = None
    exclude_archived: bool = False
    index: str = 'relevance'

    def __post_init__(self):
        if self.project_type != 'mod':
            raise ValueError('Этот каталог устанавливает только моды')
        if self.environment not in ENVIRONMENTS or self.index not in SORTS:
            raise ValueError('Неизвестная среда или сортировка')
        if (self.open_source is not None and type(self.open_source) is not bool) or type(self.exclude_archived) is not bool:
            raise ValueError('Некорректный дополнительный фильтр')
        for field in ('versions', 'loaders', 'categories'):
            values = getattr(self, field)
            if not isinstance(values, tuple) or len(values) > 64 or len(set(values)) != len(values):
                raise ValueError('Некорректный список фильтров')
            for value in values:
                if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+\-]{0,95}', value):
                    raise ValueError('Некорректное значение фильтра')

    @classmethod
    def for_instance(cls, instance):
        return cls(versions=(instance.minecraft_version,),
                   loaders=() if instance.loader == 'vanilla' else (instance.loader,))

    def chips(self):
        result = [('versions', value, 'Minecraft ' + value) for value in self.versions]
        result += [('loaders', value, value.title()) for value in self.loaders]
        if self.environment:
            result.append(('environment', self.environment, ENVIRONMENTS[self.environment]))
        result += [('categories', value, value.replace('-', ' ').title()) for value in self.categories]
        if self.open_source is not None:
            result.append(('open_source', '', 'Открытый код' if self.open_source else 'Закрытый код'))
        if self.exclude_archived:
            result.append(('exclude_archived', '', 'Без архивных проектов'))
        return tuple(result)

    def remove(self, field, value=''):
        if field in ('versions', 'loaders', 'categories'):
            return replace(self, **{field: tuple(item for item in getattr(self, field) if item != value)})
        defaults = {'environment': '', 'open_source': None, 'exclude_archived': False}
        if field not in defaults:
            raise ValueError('Неизвестный фильтр')
        return replace(self, **{field: defaults[field]})


class ModrinthQueryBuilder:
    @staticmethod
    def facets(state):
        groups = [['project_type:' + state.project_type]]
        for field, facet in (('versions', 'versions'), ('loaders', 'categories'), ('categories', 'categories')):
            values = getattr(state, field)
            if values:
                groups.append([facet + ':' + value for value in values])
        if state.environment:
            groups.append(['environment:' + state.environment])
        if state.open_source is not None:
            groups.append(['open_source:' + str(state.open_source).lower()])
        if state.exclude_archived:
            groups.append(['disclosure_types != archived'])
        return groups

    @classmethod
    def params(cls, state, query='', offset=0):
        if type(offset) is not int or offset < 0 or not isinstance(query, str):
            raise ValueError('Некорректная страница или запрос')
        return {'query': query.strip(), 'facets': json.dumps(cls.facets(state)),
                'index': state.index, 'offset': offset, 'limit': 20}
