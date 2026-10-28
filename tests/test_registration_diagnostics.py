import io
import ast
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
import urllib.error
from unittest.mock import patch

import pytest

from nexus_launcher.nexus_account import AccountError, NexusAccountClient, TransportError, OfflineError, ProtocolError
from nexus_launcher.registration_errors import registration_error
from tests.test_nexus_account import FakeResponse


@pytest.mark.parametrize('message,status,expected', [
    ('Аккаунт с такой почтой уже существует.',409,'Аккаунт уже создан!'),
    ('Пароль: от 8 до 1024 символов.',400,'8 до 1024'),
    ('Неверный код подтверждения.',400,'Неверный код.'),
    ('Код истёк. Запросите новый код.',400,'Код истёк'),
    ('Новый код можно запросить через минуту.',429,'минуту'),
    ('Не удалось отправить письмо. Попробуйте позже.',502,'отправку письма'),
    ('Этот ник уже занят в NEXUS.',409,'ник уже занят'),
    ('unknown',429,'Слишком много'),
    ('unknown',401,'Войдите снова'),
    ('unknown',403,'проверкой безопасности'),
    ('unknown',503,'временно недоступен'),
])
def test_error_copy(message,status,expected):
    assert expected in registration_error(AccountError(message,http_status=status),'code')


@pytest.mark.parametrize('error', [TransportError('sensitive'),OfflineError('sensitive',outcome='network_error'),ProtocolError('sensitive',http_status=200,outcome='protocol_error'),TransportError('sensitive',http_status=502)])
def test_unknown_mutations_never_claim_failure_or_retry(error):
    assert 'мог быть создан' in registration_error(error,'register')
    assert 'сначала проверит' in registration_error(error,'profile')
    assert 'sensitive' not in registration_error(error,'code')


@pytest.mark.parametrize('status',[400,409,429,502,503])
def test_request_status_and_logs_do_not_include_sensitive_data(status):
    client=NexusAccountClient('https://example.test')
    body={'error':'secret-password-code-recipient@example.invalid','code':'sensitive-provider-code'}
    error=urllib.error.HTTPError('https://example.test/private?secret-query',status,'secret-reason',{},io.BytesIO(json.dumps(body).encode()))
    records=[]
    class Capture(logging.Handler):
        def emit(self,record):records.append(record.getMessage())
    logger=logging.getLogger('nexus.account.request');handler=Capture();old=logger.level
    logger.addHandler(handler);logger.setLevel(logging.INFO)
    try:
        with patch('nexus_launcher.nexus_account.open_https',side_effect=error) as network:
            with pytest.raises(AccountError) as caught:
                client._request('/api/auth/email/request-code',method='POST',payload={'email':'private@example.invalid','password':'secret-password'},token='secret-token')
            assert network.call_count==1
        assert caught.value.http_status==status
        assert caught.value.outcome=='http_error'
        assert len(records)==1
        assert 'operation=registration_code outcome=http_error' in records[0]
        assert f'http_status={status}' in records[0]
        assert not any(x in records[0] for x in ['secret','private','@','password','token'])
        assert 'secret' not in registration_error(caught.value,'code')
    finally:
        logger.removeHandler(handler);logger.setLevel(old)


def test_success_and_protocol_error_are_distinguished():
    client=NexusAccountClient('https://example.test')
    with patch('nexus_launcher.nexus_account.open_https',return_value=FakeResponse({'ok':True,'challengeId':'synthetic'})):
        assert client._request('/api/auth/email/request-code')[0]['ok']
    with patch('nexus_launcher.nexus_account.open_https',return_value=FakeResponse([])):
        with pytest.raises(ProtocolError) as caught:client._request('/api/auth/email/request-code')
    assert caught.value.outcome=='protocol_error'


def test_network_failure_retains_no_exception_text_and_does_not_retry():
    with patch('nexus_launcher.nexus_account.open_https',side_effect=urllib.error.URLError('secret-endpoint-token')) as network:
        with pytest.raises(OfflineError) as caught:NexusAccountClient('https://example.test')._request('/api/auth/register')
    assert network.call_count==1
    assert caught.value.outcome=='network_error'
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('email,password,confirmation,expected', [
    ('bad','abcdefgh','abcdefgh','корректную почту'),
    ('a@example.invalid','short','short','слишком короткий'),
    ('a@example.invalid','        ','        ','не только пробелы'),
    ('a@example.invalid','x'*1025,'x'*1025,'слишком длинный'),
    ('a@example.invalid','abcdefgh','abcdefgh1','не совпадают'),
])
def test_real_submit_validation_without_qt_or_network(email,password,confirmation,expected):
    registration = Path(__file__).resolve().parents[1] / 'nexus_launcher' / 'nexus_platform' / 'registration.py'
    tree=ast.parse(registration.read_text(encoding='utf-8'))
    validator=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='valid_registration_email')
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RegistrationDialog')
    submit=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_submit')
    namespace={'re':re};exec(compile(ast.Module(body=[validator,submit],type_ignores=[]),'<actual-registration-validation>','exec'),namespace)
    output=[]
    field=lambda value:SimpleNamespace(text=lambda:value,setFocus=lambda:None)
    owner=SimpleNamespace(busy=False,completed=False,email=field(email),nick=field('Player_1'),password=field(password),confirm=field(confirmation),error=SimpleNamespace(setText=output.append))
    namespace['_submit'](owner)
    assert len(output)==1 and expected in output[0]
