"""Local, bounded, schema-only health events. Never accepts free-form messages."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
from datetime import datetime, timezone

_lock = threading.RLock()
_logger = None
_root = None
_findings = {}
_operations = {'startup', 'registration_code', 'registration_confirm', 'registration_profile', 'account', 'python_main', 'python_thread'}
_outcomes = {'started', 'ok', 'http_error', 'network_error', 'protocol_error', 'unexpected_error', 'unhandled_exception'}


def record(operation, outcome, http_status=None, duration_ms=None):
    if operation not in _operations or outcome not in _outcomes:
        return False
    if http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599):
        return False
    if duration_ms is not None and (type(duration_ms) is not int or not 0 <= duration_ms <= 86400000):
        return False
    event = {'time': datetime.now(timezone.utc).isoformat(), 'operation': operation, 'outcome': outcome, 'http_status': http_status, 'duration_ms': duration_ms}
    if outcome == 'unhandled_exception':
        finding = ('LAUNCHER_EXCEPTION', 'Ошибка Python в лаунчере. Текст исключения и данные пользователя не сохранялись.')
    elif outcome == 'network_error':
        finding = ('CONNECTION_UNCONFIRMED', 'Соединение не подтверждено: возможны сеть, TLS, прокси или сервер. Причина не установлена.')
    elif outcome == 'protocol_error':
        finding = ('RESPONSE_FORMAT', 'Ответ сервера не соответствует ожидаемому формату.')
    elif http_status == 429:
        finding = ('THROTTLED', 'Сервер ограничил число запросов. Автоматически повторять запрос не нужно.')
    elif http_status is not None and http_status >= 500:
        finding = ('SERVER_FAILURE', 'Получен отказ сервера. Это не доказательство поломки лаунчера или причины сбоя почты.')
    elif outcome == 'unexpected_error':
        finding = ('UNCLASSIFIED', 'Неизвестная ошибка в клиентской цепочке. Нужна дополнительная проверка.')
    else:
        finding = None
    with _lock:
        if _logger is None:
            return False
        try:
            _logger.info(json.dumps(event, ensure_ascii=False))
            if finding:
                _findings[finding[0]] = {'code': finding[0], 'explanation': finding[1], 'last_seen': event['time']}
            report = {'status': 'ISSUES_OBSERVED' if _findings else 'NO_ISSUE_OBSERVED_YET', 'findings': list(_findings.values()), 'last_event': event, 'limits': 'Не сканирует файлы, аккаунты и сеть. Не ловит нативные сбои, зависания или принудительное завершение процесса. Отсутствие событий не доказывает исправность.'}
            tmp = _root / 'health-summary.tmp'
            tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(_root / 'health-summary.json')
            return True
        except (OSError, ValueError):
            return False  # Diagnostics must not break the account operation.


def install(directory):
    global _logger, _root
    with _lock:
        if _logger is not None:
            return _root
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        logger = logging.Logger('nexus.health', level=logging.INFO)
        handler = RotatingFileHandler(root / 'events.jsonl', maxBytes=262144, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        _root, _logger = root, logger
    sys.excepthook = lambda *_: record('python_main', 'unhandled_exception')
    threading.excepthook = lambda _: record('python_thread', 'unhandled_exception')
    record('startup', 'started')
    return root
