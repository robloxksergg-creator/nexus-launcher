import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from nexus_launcher.nexus_platform.catalog_filters import ModrinthFilterState as State, ModrinthQueryBuilder as Builder
from nexus_launcher.nexus_platform.catalog_provider import CatalogProvider
from nexus_launcher.nexus_platform.mod_catalog import ModCatalog


INSTANCE = SimpleNamespace(id='fixture', name='Моя сборка', minecraft_version='1.21.1', loader='fabric')
TAGS = {'versions': ['1.21.1', '1.21.4'], 'loaders': ['fabric', 'neoforge'],
        'categories': ['optimization', 'adventure']}


def test_defaults_and_current_instance():
    assert State() == State(project_type='mod')
    state = State.for_instance(INSTANCE)
    assert state.versions == ('1.21.1',)
    assert state.loaders == ('fabric',)
    assert state.environment == '' and state.categories == () and state.open_source is None


def test_vanilla_has_no_loader_facet():
    assert State.for_instance(SimpleNamespace(minecraft_version='1.21', loader='vanilla')).loaders == ()


@pytest.mark.parametrize('field,value,facet', [
    ('versions', ('1.21.1',), ['versions:1.21.1']),
    ('versions', ('1.21.1', '1.21.4'), ['versions:1.21.1', 'versions:1.21.4']),
    ('loaders', ('fabric',), ['categories:fabric']),
    ('loaders', ('fabric', 'neoforge'), ['categories:fabric', 'categories:neoforge']),
    ('categories', ('optimization',), ['categories:optimization']),
    ('categories', ('optimization', 'adventure'), ['categories:optimization', 'categories:adventure']),
    ('environment', 'client_and_server', ['environment:client_and_server']),
    ('open_source', True, ['open_source:true']),
    ('exclude_archived', True, ['disclosure_types != archived']),
])
def test_individual_filters(field, value, facet):
    assert facet in Builder.facets(replace(State(), **{field: value}))


def test_combination_and_or_query_sort_pagination():
    state = State(versions=('1.21.1', '1.21.4'), loaders=('fabric',), categories=('optimization',),
                  environment='client_and_server', index='downloads')
    params = Builder.params(state, ' sodium ', 20)
    assert json.loads(params['facets']) == [
        ['project_type:mod'], ['versions:1.21.1', 'versions:1.21.4'], ['categories:fabric'],
        ['categories:optimization'], ['environment:client_and_server']]
    assert params['query'] == 'sodium' and params['offset'] == 20 and params['limit'] == 20
    assert params['index'] == 'downloads'


@pytest.mark.parametrize('index', ['relevance', 'downloads', 'follows', 'newest', 'updated'])
def test_all_server_sorts(index):
    assert Builder.params(State(index=index))['index'] == index


def test_empty_filters_keep_only_installable_project_type():
    assert Builder.facets(State()) == [['project_type:mod']]


def test_active_chips_and_removal():
    state = State(versions=('1.21.1',), loaders=('fabric',), categories=('optimization',),
                  environment='server_only', open_source=True, exclude_archived=True)
    assert len(state.chips()) == 6
    for field, value, _label in state.chips():
        new = state.remove(field, value)
        assert len(new.chips()) == 5
        assert len(state.chips()) == 6  # immutable applied state


@pytest.mark.parametrize('kwargs', [
    {'project_type': 'modpack'}, {'project_type': 'shader'}, {'environment': 'fake'},
    {'index': 'alphabetical'}, {'versions': ('x OR downloads>0',)},
    {'categories': ('optimization', 'optimization')}, {'versions': ['1.21']},
    {'loaders': ('fabric:evil',)}, {'exclude_archived': 'yes'},
])
def test_invalid_filter_rejected(kwargs):
    with pytest.raises(ValueError):
        State(**kwargs)


def test_actual_provider_params_and_official_tags(monkeypatch):
    provider = CatalogProvider()
    calls = []
    def get(path, params):
        calls.append((path, params))
        return {'/tag/game_version': [{'version': '1.21.1'}],
                '/tag/loader': [{'name': 'fabric', 'supported_project_types': ['mod']},
                                {'name': 'iris', 'supported_project_types': ['shader']}],
                '/tag/category': [{'name': 'optimization', 'project_type': 'mod'},
                                  {'name': 'realistic', 'project_type': 'shader'}]}.get(path, {})
    monkeypatch.setattr(provider, '_get', get)
    assert provider.filter_tags() == {key: value[:1] for key, value in TAGS.items()}
    state = State.for_instance(INSTANCE)
    provider.search_page('sodium', filters=state, offset=40)
    assert calls[-1] == ('/search', Builder.params(state, 'sodium', 40))


class Future:
    def __init__(self, work):
        self.work = work
        self.cancelled = False
    def cancel(self):
        self.cancelled = True
    def done(self):
        return False


class Pool:
    def __init__(self):
        self.jobs = []
    def submit(self, work):
        job = Future(work)
        self.jobs.append(job)
        return job
    def shutdown(self, **kwargs):
        pass


@pytest.fixture
def catalog(monkeypatch):
    app = QApplication.instance() or QApplication([])
    widget = ModCatalog()
    widget.pool.shutdown(wait=False, cancel_futures=True)
    widget.pool = Pool()
    widget._tags = TAGS
    monkeypatch.setattr(widget.provider, 'search_page', lambda *a, **k: {'hits': [], 'total_hits': 0})
    widget.resize(1100, 700)
    widget.show()
    widget.open_for(INSTANCE)
    app.processEvents()
    yield app, widget
    if widget.filter_panel:
        widget.filter_panel.reject()
    widget.shutdown()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_draft_apply_no_request_storm_and_escape(catalog):
    app, widget = catalog
    old = widget.filter_state
    widget._open_filters()
    panel = widget.filter_panel
    for selector in (panel.versions, panel.loaders, panel.categories):
        selector.list.item(1).setCheckState(Qt.Checked)
    panel.environment.setCurrentIndex(panel.environment.findData('client_and_server'))
    panel.open_source.setChecked(True)
    assert widget.filter_state == old and len(widget.pool.jobs) == 1
    panel.reject()
    assert widget.filter_state == old and len(widget.pool.jobs) == 1
    widget._open_filters()
    widget.filter_panel.categories.list.item(0).setCheckState(Qt.Checked)
    widget.filter_panel.accept()
    assert widget.filter_state.categories == ('optimization',)
    assert len(widget.pool.jobs) == 2 and widget.pool.jobs[0].cancelled
    app.processEvents()


def test_chip_reset_query_sort_and_paging(catalog):
    app, widget = catalog
    widget.query.setText('sodium')
    widget._apply_filters(replace(widget.filter_state, categories=('optimization',), index='follows'))
    widget.search(offset=20)
    assert widget.offset == 20 and widget.query.text() == 'sodium'
    widget.open_for(INSTANCE)
    assert widget.offset == 20
    assert widget.filter_state.index == 'follows'
    widget._remove_filter('categories', 'optimization')
    assert widget.offset == 0 and widget.filter_state.categories == ()
    assert widget.query.text() == 'sodium'
    widget._reset_filters()
    assert widget.filter_state == State.for_instance(INSTANCE)
    assert widget.query.text() == 'sodium'


def test_more_than_64_selections_does_not_submit_invalid_state(catalog):
    app, widget = catalog
    widget._open_filters()
    selector = widget.filter_panel.versions
    selector.clear()
    selector.set_values([f'1.20.{i}' for i in range(65)])
    for i in range(65):
        selector.list.item(i).setCheckState(Qt.Checked)
    assert len(selector.selected()) == 64
    assert len(widget.pool.jobs) == 1


def test_stale_cancelled_response_and_same_instance_restore(catalog):
    app, widget = catalog
    token = widget.generation
    widget.query.setText('sodium')
    widget._apply_filters(replace(widget.filter_state, categories=('optimization',)))
    widget._received(token, {'hits': [{'project_id': 'stale', 'title': 'Stale'}]}, '')
    assert widget.results.count() == 0
    widget.open_for(INSTANCE)
    assert widget.query.text() == 'sodium'
    assert widget.filter_state.categories == ('optimization',)
    other = SimpleNamespace(id='other', name='Другая', minecraft_version='1.20.1', loader='forge')
    widget.open_for(other)
    assert widget.filter_state == State.for_instance(other) and widget.query.text() == ''
    widget.open_for(INSTANCE)
    assert widget.query.text() == 'sodium' and widget.filter_state.categories == ('optimization',)


def test_known_incompatible_results_cannot_install(catalog):
    app, widget = catalog
    hits = [{'project_id': 'wrong', 'title': 'Wrong', 'versions': ['1.20.1'], 'categories': ['fabric']},
            {'project_id': 'loader', 'title': 'Loader', 'versions': ['1.21.1'], 'categories': ['neoforge']},
            {'project_id': 'right', 'title': 'Right', 'versions': ['1.21.1'], 'categories': ['fabric']}]
    widget._received(widget.generation, {'hits': hits, 'total_hits': 3}, '')
    assert '1.20.1' in widget._hit_context(hits[0])
    assert '1.21.1' not in widget._hit_context(hits[0])
    for row in range(3):
        widget.results.setCurrentRow(row)
        assert widget.install.isEnabled() is (row == 2)


def test_tag_search_clear_reset_and_keyboard(catalog):
    app, widget = catalog
    widget._open_filters()
    panel = widget.filter_panel
    panel.versions.search.setText('1.21.4')
    assert panel.versions.list.item(0).isHidden()
    panel.versions.clear()
    panel.categories.list.item(0).setCheckState(Qt.Checked)
    panel.reset()
    assert panel.state() == State.for_instance(INSTANCE)
    from PySide6.QtTest import QTest
    QTest.keyClick(panel, Qt.Key_Escape)
    assert widget.filter_panel is None


def test_keyboard_multiselect_popup_escape_and_enter_apply(catalog):
    from PySide6.QtTest import QTest
    app, widget = catalog
    widget._open_filters()
    panel = widget.filter_panel
    panel.categories.list.setFocus()
    panel.categories.list.setCurrentRow(0)
    QTest.keyClick(panel.categories.list, Qt.Key_Space)
    assert panel.categories.selected() == ('optimization',)
    QTest.keyClick(panel.categories.list, Qt.Key_A, Qt.ControlModifier)
    assert panel.categories.selected() == ('optimization',)
    panel.versions.list.setCurrentRow(0)
    QTest.keyClick(panel.versions.list, Qt.Key_Down)
    QTest.keyClick(panel.versions.list, Qt.Key_Space)
    assert set(panel.versions.selected()) == {'1.21.1', '1.21.4'}
    panel.environment.showPopup()
    app.processEvents()
    QTest.keyClick(panel.environment.view(), Qt.Key_Escape)
    app.processEvents()
    assert panel.isVisible()
    QTest.keyClick(panel, Qt.Key_Return)
    assert widget.filter_panel is None
    assert len(widget.pool.jobs) == 2
    assert widget.filter_state.categories == ('optimization',)


def test_tag_failure_keeps_selection_and_shows_retry(catalog):
    app, widget = catalog
    widget._open_filters()
    widget._tags_received({}, 'offline')
    assert widget.filter_panel.retry.isVisible()
    assert widget.filter_panel.state() == widget.filter_state
    assert 'недоступны' in widget.filter_panel.metadata_status.text()


def test_integrated_filters_custom_controls_and_popover_bounds(catalog):
    from PySide6.QtWidgets import QComboBox, QCheckBox, QDialog
    app, widget = catalog
    widget.resize(900, 650)
    widget._open_filters()
    panel = widget.filter_panel
    assert not isinstance(panel, QDialog)
    assert not panel.findChildren(QComboBox)
    assert not panel.findChildren(QCheckBox)
    assert panel.extra.isHidden()
    panel.categories.toggle_value('optimization')
    assert panel.categories.selected() == ('optimization',)
    assert len(widget.pool.jobs) == 1
    panel.versions.showPopup()
    app.processEvents()
    popup = panel.versions.popup
    assert popup.parentWidget() is widget.window()
    assert widget.window().rect().contains(popup.geometry())
    popup.close_popup()
    panel.reject()
    assert widget.filter_state.categories == ()
    assert len(widget.pool.jobs) == 1


def test_empty_filter_chips_hidden_and_wrap(catalog):
    app, widget = catalog
    widget.filter_state = State()
    widget._update_chips()
    app.processEvents()
    assert widget.chips_widget.isHidden()
    widget.filter_state = State(versions=('1.21.1', '1.21.4'), loaders=('fabric', 'forge'), categories=('optimization', 'adventure'))
    widget._update_chips()
    assert not widget.chips_widget.isHidden()
    assert widget.chips.heightForWidth(260) > 38
