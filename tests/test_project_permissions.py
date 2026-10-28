import pytest

from nexus_launcher.nexus_platform.project_permissions import ProjectAccess, ProjectRole


@pytest.mark.parametrize('access', [
    ProjectAccess(), ProjectAccess('a', 'a'),
    ProjectAccess('a', 'a', True, False),
    ProjectAccess('a', 'a', False, True),
    ProjectAccess('a', 'b', True, True),
    ProjectAccess(None, None, True, True),
])
def test_unverified_or_other_user_cannot_edit(access):
    with pytest.raises(PermissionError):
        access.require_edit()


def test_creator_requires_both_verified_session_and_project():
    access = ProjectAccess('a', 'a', True, True)
    assert access.role is ProjectRole.CREATOR
    access.require_edit()


def test_signed_in_noncreator_is_member_not_owner():
    assert ProjectAccess('a', 'b', True, True).role is ProjectRole.MEMBER
