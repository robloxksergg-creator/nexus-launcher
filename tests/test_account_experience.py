import pytest
from nexus_launcher.nexus_account import NexusAccountClient, ProtocolError


@pytest.mark.parametrize('role', [None, 'player', 'server_creator', 'content_maker'])
def test_interest_is_loaded_without_admin_authority(role):
    client = NexusAccountClient('https://example.test')
    profile = client._profile_from_result({'user': {'id': 'owned', 'minecraftNick': 'Builder',
        'email': 'fixture@example.test', 'isAdmin': False, 'experienceRole': role}}, 'a' * 64)
    assert profile.experience_role == role
    assert profile.is_admin is False


def test_old_server_without_role_is_compatible():
    profile = NexusAccountClient('https://example.test')._profile_from_result(
        {'user': {'minecraftNick': 'Builder', 'email': 'fixture@example.test'}}, 'a' * 64)
    assert profile.experience_role is None


@pytest.mark.parametrize('role', ['admin', 'verified', True, {}, ['server_creator']])
def test_unknown_role_does_not_publish_support_identity(role):
    client = NexusAccountClient('https://example.test')
    with pytest.raises(ProtocolError):
        client._profile_from_result({'user': {'minecraftNick': 'Builder', 'experienceRole': role}}, 'a' * 64)
    assert client._support_identity is None
