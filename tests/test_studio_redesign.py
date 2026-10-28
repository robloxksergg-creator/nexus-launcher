"""Actual Studio workflows across the migrated shell and retained editor model."""

from pathlib import Path

from PySide6.QtWidgets import QApplication

from nexus_launcher.nexus_platform.learning.studio import CreatorWorkspace
from tests.test_learning_studio import js, wait


def test_contextual_creation_upload_layers_grouping_preview_save(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    workspace = CreatorWorkspace(tmp_path)
    workspace.resize(1280, 800)
    workspace.show()
    try:
        wait(app, lambda: workspace.ready)
        workspace.engine.settings(onboarding_seen=True)
        js(app, workspace.page, "NexusCreator.closeWelcome()")
        js(app, workspace.page, "NexusStudioUI.openPicker()")
        assert js(
            app, workspace.page, "!document.querySelector('.creator-picker').hidden"
        )
        js(
            app,
            workspace.page,
            "document.querySelector('.creator-picker input').value='missing';document.querySelector('.creator-picker input').dispatchEvent(new Event('input'))",
        )
        assert js(
            app,
            workspace.page,
            "[...document.querySelectorAll('.creator-component-grid button')].every(x=>x.hidden)",
        )
        js(
            app,
            workspace.page,
            "document.querySelector('.creator-component-grid button:nth-child(2)').click()",
        )
        wait(
            app,
            lambda: next(
                x
                for x in workspace.adapter.snapshot()["components"]
                if x["id"] == workspace.adapter.snapshot()["selected"]
            )["type"]
            == "png",
        )
        assert not js(
            app,
            workspace.page,
            "[...document.querySelectorAll('.creator-inspector-section')].some(x=>x.textContent.includes('Типографика'))",
        )
        # Trigger the real file-input validation path using a decoded bundled PNG.
        js(
            app,
            workspace.page,
            "fetch('/gearmorph-official.png').then(x=>x.blob()).then(blob=>{const input=properties.querySelector('input[type=file]');const transfer=new DataTransfer();transfer.items.add(new File([blob],'banner.png',{type:'image/png'}));input.files=transfer.files;input.dispatchEvent(new Event('change'));})",
        )
        wait(
            app,
            lambda: next(
                x
                for x in workspace.adapter.snapshot()["components"]
                if x["id"] == workspace.adapter.snapshot()["selected"]
            )
            .get("src", "")
            .startswith("blob:"),
        )
        js(
            app,
            workspace.page,
            "document.querySelector('.creator-rail #create-item').click()",
        )
        assert not workspace.page.script_errors, workspace.page.script_errors
        wait(
            app,
            lambda: next(
                x
                for x in workspace.adapter.snapshot()["components"]
                if x["id"] == workspace.adapter.snapshot()["selected"]
            )["type"]
            == "text",
        )
        js(
            app,
            workspace.page,
            "multiSelection.clear();studioDraft.slice(-2).forEach(x=>multiSelection.add(x.id));document.querySelector('#group-items').click()",
        )
        wait(
            app,
            lambda: bool(
                next(
                    x
                    for x in workspace.adapter.snapshot()["components"]
                    if x["id"] == workspace.adapter.snapshot()["selected"]
                ).get("group")
            ),
        )
        js(
            app,
            workspace.page,
            "document.querySelector('#ungroup-items').click();updateItem({locked:true})",
        )
        wait(
            app,
            lambda: next(
                x
                for x in workspace.adapter.snapshot()["components"]
                if x["id"] == workspace.adapter.snapshot()["selected"]
            ).get("locked"),
        )
        assert js(
            app,
            workspace.page,
            "[...properties.querySelectorAll('.position-fields input')].every(x=>x.disabled)",
        )
        js(
            app,
            workspace.page,
            "updateItem({locked:false});const b=[...properties.querySelectorAll('.creator-element-actions button')].find(x=>x.textContent==='Ниже');b.click()",
        )
        js(
            app,
            workspace.page,
            "[...properties.querySelectorAll('.creator-element-actions button')].find(x=>x.textContent==='Скрыть').click()",
        )
        assert js(
            app,
            workspace.page,
            "board.querySelector('[data-item=\"'+selectedID+'\"]').hidden",
        )
        js(
            app,
            workspace.page,
            "[...properties.querySelectorAll('.creator-element-actions button')].find(x=>x.textContent==='Показать').click();document.querySelector('#studio-save').click();document.querySelector('#studio-cancel').click()",
        )
        wait(app, lambda: workspace.document_path.is_file())
        assert js(
            app, workspace.page, "!document.querySelector('.academy-help').hidden"
        )
        js(app, workspace.page, "selectedID='';renderStudio()")
        assert js(
            app,
            workspace.page,
            "!document.querySelector('.background-settings').hidden",
        )
        assert not workspace.page.script_errors
    finally:
        workspace.shutdown()
        workspace.close()
