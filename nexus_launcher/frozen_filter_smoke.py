"""Offline packaged-filter smoke; uses in-memory fixtures, never instance files."""
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from nexus_launcher.nexus_platform.catalog_filters import ModrinthFilterState, ModrinthQueryBuilder


def check_filters(window, report_path):
    catalog = window.services.instances_page.mod_catalog
    old = catalog.instance, catalog.filter_state, catalog._tags, catalog.search
    calls = []
    try:
        catalog.instance = SimpleNamespace(id='smoke', name='Проверка', minecraft_version='1.21.1', loader='fabric')
        catalog.filter_state = ModrinthFilterState.for_instance(catalog.instance)
        catalog._tags = {'versions': ['1.21.1', '1.21.4'], 'loaders': ['fabric', 'neoforge'],
                         'categories': ['optimization', 'adventure']}
        catalog.search = lambda *args, **kwargs: calls.append(catalog.filter_state)
        catalog._open_filters()
        panel = catalog.filter_panel
        panel.categories.list.item(0).setCheckState(Qt.CheckState.Checked)
        panel.environment.setCurrentIndex(panel.environment.findData('client_and_server'))
        QApplication.processEvents()
        panel.grab().save(str(report_path.with_name(report_path.stem + '-filters.png')))
        draft_has_no_requests = len(calls) == 0
        panel.accept()
        facets = ModrinthQueryBuilder.facets(catalog.filter_state)
        report = {'fixture_data': True, 'draft_has_no_requests': draft_has_no_requests,
                  'apply_one_request': len(calls) == 1,
                  'environment_facet': ['environment:client_and_server'] in facets,
                  'category_facet': ['categories:optimization'] in facets,
                  'network_calls': 0}
        assert all(report[key] for key in ('draft_has_no_requests', 'apply_one_request',
                                         'environment_facet', 'category_facet'))
        return report
    finally:
        if catalog.filter_panel:
            catalog.filter_panel.reject()
        catalog.instance, catalog.filter_state, catalog._tags, catalog.search = old

