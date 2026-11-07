from copy import deepcopy
import pytest
from nexus_launcher.creator_catalogue import validate_creator_catalogue


def entry():
    return dict(id='11111111-1111-4111-8111-111111111111',slug='community-example',name='Example',summary='Demo',genre='RPG',version='1.21.1',loader='fabric',access='PUBLIC',website='/servers/community-example',downloadEnabled=False)


@pytest.mark.parametrize('access',['PUBLIC','PAID','PRIVATE'])
def test_access_labels_are_display_only(access):
    row=dict(entry(),access=access,manifest='https://untrusted.invalid/package.zip')
    result=validate_creator_catalogue(dict(items=[row],next=None))
    assert result['items'][0]['downloadEnabled'] is False
    assert 'manifest' not in result['items'][0]


@pytest.mark.parametrize('changes',[{'downloadEnabled':True},{'website':'https://evil.invalid'},{'website':'/servers/other'},{'access':'ADMIN'},{'id':'bad'},{'name':'<b>\x00'},{'name':'a'*81}])
def test_untrusted_or_oversized_entry_rejected(changes):
    value=dict(items=[dict(entry(),**changes)],next=None)
    before=deepcopy(value)
    with pytest.raises(ValueError):validate_creator_catalogue(value)
    assert value==before


def test_duplicates_and_bad_cursors_rejected():
    for value in [dict(items=[entry(),entry()],next=None),dict(items=[entry()],next='https://evil.invalid'),dict(items=[entry()]*51,next=None)]:
        with pytest.raises(ValueError):validate_creator_catalogue(value)


def test_launcher_first_does_not_invent_website_url():
    value=dict(items=[dict(entry(),website=None)],next=None)
    assert validate_creator_catalogue(value)['items'][0]['website'] is None
