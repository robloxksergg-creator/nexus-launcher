import copy
import json
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from nexus_launcher.creator_placements import default_placements, validate_placements
from nexus_launcher.nexus_platform.learning.studio import CreatorWorkspace
from tests.test_learning_studio import js, wait


@pytest.mark.parametrize('change',[
    lambda v:v.update(approved=True),
    lambda v:v.update(requested=['top_banner','top_banner']),
    lambda v:v.update(requested=['automatic_publish']),
    lambda v:v['formats']['home_hero'].update(zoom=161),
    lambda v:v['formats']['home_hero'].update(x=float('nan')),
    lambda v:v['formats']['home_hero'].update(x=True),
    lambda v:v['formats']['home_hero'].update(imageId='../secret'),
    lambda v:v.update(title='x'*81),
])
def test_invalid_placement_settings_rejected(change):
    value=default_placements()
    change(value)
    with pytest.raises(ValueError): validate_placements(value)


def test_crops_are_independent_and_copy_is_detached():
    value=default_placements()
    value['formats']['home_hero']['zoom']=145
    checked=validate_placements(value)
    checked['formats']['home_hero']['zoom']=120
    assert value['formats']['home_hero']['zoom']==145
    assert value['formats']['catalog_card']['zoom']==100


def test_actual_preview_edits_save_reload_and_no_publication(tmp_path):
    app=QApplication.instance() or QApplication([])
    workspace=CreatorWorkspace(tmp_path)
    workspace.resize(1440,900);workspace.show()
    try:
        wait(app,lambda:workspace.ready)
        js(app,workspace.page,'NexusCreator.closeWelcome();NexusPlacementUI.open()')
        assert js(app,workspace.page,"document.querySelector('.placement-workspace').hidden") is False
        js(app,workspace.page,"const select=document.querySelector('.placement-inspector select');select.value='practice-background';select.dispatchEvent(new Event('change'))")
        wait(app,lambda:workspace.adapter.snapshot()['placements']['formats']['home_hero']['imageId']=='practice-background')
        js(app,workspace.page,"const slider=document.querySelector('[data-crop=zoom]');slider.value=145;slider.dispatchEvent(new Event('input'));slider.dispatchEvent(new Event('change'))")
        js(app,workspace.page,"document.querySelector('[data-format=top_banner]').click();const wish=document.querySelector('.placement-wishes input[value=top_banner]');wish.click();document.querySelector('.placement-save').click()")
        wait(app,lambda:'top_banner' in workspace.adapter.snapshot()['placements']['requested'])
        wait(app,lambda:workspace.document_path.exists())
        before=copy.deepcopy(workspace.adapter.snapshot())
        assert before['placements']['formats']['home_hero']['zoom']==145
        assert before['placements']['formats']['top_banner']['zoom']==100
        assert 'top_banner' in before['placements']['requested']
        assert 'approved' not in before['placements']
        saved=json.loads(workspace.document_path.read_text(encoding='utf-8'))
        assert saved==before
        js(app,workspace.page,'NexusCreator.load('+json.dumps(saved)+');NexusPlacementUI.open()')
        assert json.loads(js(app,workspace.page,'JSON.stringify(NexusPlacementUI.snapshot())'))==before['placements']
        for width,height in ((1440,900),(1000,740),(720,640)):
            workspace.resize(width,height);QTest.qWait(100)
            assert js(app,workspace.page,'document.documentElement.scrollWidth<=innerWidth')
            assert js(app,workspace.page,"document.querySelector('.placement-inspector').getBoundingClientRect().right<=innerWidth")
        invalid=copy.deepcopy(before);invalid['placements']['approved']=True
        workspace._event({'type':'placements.changed','snapshot':invalid})
        assert workspace.adapter.snapshot()==before
        assert not workspace.page.script_errors
    finally:
        workspace.shutdown();workspace.close()
