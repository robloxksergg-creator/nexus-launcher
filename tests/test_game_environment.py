from nexus_launcher.process_utils import game_environment


def test_game_does_not_inherit_service_secrets_or_vm_injection():
    source = {
        'PATH': 'synthetic-bin', 'SystemRoot': 'synthetic-windows',
        'TEMP': 'synthetic-temp', 'APPDATA': 'synthetic-appdata',
        'RESEND_API_KEY': 'canary', 'CLOUDFLARE_API_TOKEN': 'canary',
        'CUSTOM_SERVICE_CREDENTIAL': 'canary', 'NEXUS_GAME_TICKET': 'old-canary',
        'JAVA_TOOL_OPTIONS': '-javaagent:canary', '_JAVA_OPTIONS': 'canary',
        'JDK_JAVA_OPTIONS': 'canary', 'PYTHONPATH': 'canary', '_PYI_ARCHIVE_FILE': 'canary',
    }
    actual = game_environment(source, 'new-synthetic-ticket')
    assert actual == {
        'PATH': 'synthetic-bin', 'SystemRoot': 'synthetic-windows',
        'TEMP': 'synthetic-temp', 'APPDATA': 'synthetic-appdata',
        'NEXUS_GAME_TICKET': 'new-synthetic-ticket',
    }
    assert source['NEXUS_GAME_TICKET'] == 'old-canary'
    assert 'NEXUS_GAME_TICKET' not in game_environment(source)


def test_secret_values_are_not_even_read_from_input_mapping():
    class Environment(dict):
        def __getitem__(self, key):
            assert key == 'PATH'
            return super().__getitem__(key)
    assert game_environment(Environment(PATH='synthetic', PRIVATE_SECRET='unread')) == {'PATH': 'synthetic'}


def test_actual_launch_passes_filtered_environment_to_process(tmp_path, monkeypatch):
    import nexus_launcher.launcher_core as launcher_core
    from types import SimpleNamespace

    launcher = launcher_core.MinecraftLauncher(tmp_path, log=lambda _: None)
    monkeypatch.setattr(launcher, '_java', lambda **_: 'synthetic-java')
    monkeypatch.setattr(launcher, 'install', lambda _: None)
    monkeypatch.setattr('nexus_launcher.native_minecraft.get_minecraft_command',
                        lambda *_: ['synthetic-java', 'SyntheticMain'])
    monkeypatch.setattr(launcher_core, 'hidden_process_kwargs', lambda: {})
    monkeypatch.setattr(launcher_core.os, 'environ', {
        'PATH': 'synthetic-bin', 'RESEND_API_KEY': 'synthetic-secret',
        'JAVA_TOOL_OPTIONS': 'synthetic-agent', 'NEXUS_GAME_TICKET': 'stale',
    })
    calls = []
    tickets = []

    def fresh_ticket():
        tickets.append('issued')
        return 'a' * 64

    def fake_process(command, **kwargs):
        assert tickets == ['issued']
        calls.append((command, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(launcher_core.subprocess, 'Popen', fake_process)
    process = launcher.launch('1.21.1', 'Synthetic_User', 2048,
                              loader='vanilla', ticket_supplier=fresh_ticket)
    try:
        assert len(calls) == 1
        assert calls[0][1]['env'] == {
            'PATH': 'synthetic-bin', 'NEXUS_GAME_TICKET': 'a' * 64,
        }
        assert calls[0][0] == ['synthetic-java', 'SyntheticMain']
    finally:
        process._nexus_log_handle.close()


def test_ticket_is_obtained_after_install_and_failure_prevents_process(tmp_path, monkeypatch):
    import pytest
    import nexus_launcher.launcher_core as launcher_core
    events = []
    launcher = launcher_core.MinecraftLauncher(tmp_path, log=lambda _: None)
    monkeypatch.setattr(launcher, '_java', lambda **_: 'fake-java')
    monkeypatch.setattr(launcher, 'install', lambda _: events.append('installed'))
    monkeypatch.setattr('nexus_launcher.native_minecraft.get_minecraft_command',
                        lambda *_: ['fake-java'])
    monkeypatch.setattr(launcher_core.subprocess, 'Popen', lambda *a, **k: pytest.fail('process started'))

    def expired():
        assert events == ['installed']
        raise PermissionError('revoked')

    with pytest.raises(PermissionError, match='revoked'):
        launcher.launch('1.21.1', 'Synthetic_User', 2048, loader='vanilla', ticket_supplier=expired)
    assert not (tmp_path / '.nexus-launcher/logs/minecraft-launch.log').exists()
    with pytest.raises(PermissionError):
        launcher.launch('1.21.1', 'Synthetic_User', 2048, loader='vanilla', ticket_supplier=lambda: '')


def test_account_change_before_and_during_ticket_issuance_is_denied():
    import pytest
    from types import SimpleNamespace
    from nexus_launcher.launch_identity import ticket_supplier
    profile = object()
    state = [profile]
    calls = []

    def issue(p):
        calls.append(p)
        state[0] = None
        return 'a' * 64

    client = SimpleNamespace(game_ticket_for=issue)
    supplier = ticket_supplier(profile, client, lambda: state[0], lambda: client)
    state[0] = None
    with pytest.raises(PermissionError):
        supplier()
    assert calls == []
    state[0] = profile
    with pytest.raises(PermissionError):
        supplier()
    assert calls == [profile]
    state[0] = profile
    client.game_ticket_for = lambda p: 'b' * 64
    assert supplier() == 'b' * 64


def test_ticket_response_is_bound_to_profile_session_and_expiration(monkeypatch):
    import time
    import pytest
    from nexus_launcher.nexus_account import NexusAccountClient, NexusProfile, AccountError
    client = NexusAccountClient('https://example.test')
    profile = NexusProfile('Synthetic_User', 'synthetic@example.test', user_id='synthetic-id')
    state = ['synthetic-session']
    monkeypatch.setattr(client, '_token', lambda: state[0])
    client._support_identity = ('synthetic-id', state[0])
    response = dict(ticket='a' * 64, minecraftNick=profile.minecraft_nick,
                    expiresAt=int(time.time() * 1000) + 120000, audience='nexus-minecraft',
                    operation='game-login', version=1)
    monkeypatch.setattr(client, '_request', lambda *a, **k: (response, None))
    assert client.game_ticket_for(profile) == 'a' * 64
    for name, value in [('minecraftNick', 'Other_User'), ('expiresAt', 0),
                        ('expiresAt', True), ('version', True), ('audience', 'other'),
                        ('operation', 'other'), ('ticket', 'malformed')]:
        original = response[name]
        response[name] = value
        with pytest.raises(AccountError):
            client.game_ticket_for(profile)
        response[name] = original

    def switched(*a, **k):
        state[0] = 'other-session'
        return response, None

    monkeypatch.setattr(client, '_request', switched)
    with pytest.raises(AccountError):
        client.game_ticket_for(profile)
    with pytest.raises(AccountError):
        client.game_ticket_for(profile)
