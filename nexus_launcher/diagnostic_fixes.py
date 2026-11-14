"""Evidence-bound trial suggestions, never a promise of a repaired launch."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FixSuggestion:
    finding_index: int
    title: str
    detail: str
    filename: str = ''


def suggest_fixes(report):
    suggestions=[]
    known={mod.filename for mod in report.mods}
    trial_codes={'LOADER_MISMATCH','UNREADABLE_MOD','MISSING_DEPENDENCY','VERSION_MISMATCH'}
    for index,finding in enumerate(report.findings):
        if finding.code=='DUPLICATE_ID':
            for name in dict.fromkeys(finding.evidence):
                if name in known:
                    suggestions.append(FixSuggestion(index,'Проверить без дубликата: '+name,
                        'Отключить только этот JAR в отдельной копии. Выбор нужной версии остаётся за вами; успешный запуск не подтверждён.',name))
        elif finding.code in trial_codes and finding.filename:
            advice={'MISSING_DEPENDENCY':'Предпочтительно подобрать обязательную зависимость в каталоге. Для проверки можно временно отключить требующий её мод в копии.',
                'VERSION_MISMATCH':'Подберите совместимую версию зависимости. Альтернатива — проверить копию без требующего её мода.',
                'LOADER_MISMATCH':'Нужна версия мода для загрузчика этой сборки. Пробный вариант отключит несовместимый JAR только в копии.',
                'UNREADABLE_MOD':'Переустановите файл из доверенного источника. Пробный вариант проверит копию без этого JAR.'}[finding.code]
            suggestions.append(FixSuggestion(index,finding.title,advice,finding.filename))
        elif finding.level in {'error','warning'}:
            suggestions.append(FixSuggestion(index,finding.title,
                'Автоматический фикс не определён по этим данным. Изучите доказательства и повторите проверку после ручного изменения.'))
    return suggestions
