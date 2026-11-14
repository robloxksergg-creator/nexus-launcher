"""Exercise the nested installer view without starting its frozen entry point."""
import ast
import os
from pathlib import Path


_app = None


def test_installer_percent_is_separate_and_failure_does_not_show_completion(monkeypatch, tmp_path):
    global _app
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    from PySide6 import QtWidgets
    from nexus_launcher.themed_dialog import NexusDialog
    from nexus_launcher.nexus_platform.presentation_style import stylesheet
    from nexus_launcher.nexus_platform.theme_tokens import TOKENS
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    path = Path(__file__).parents[1] / 'nexus_launcher/online_installer_main.py'
    main = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    window = next(n for n in main.body if isinstance(n, ast.ClassDef) and n.name == 'Window')
    namespace = {name: getattr(QtWidgets, name) for name in ('QLabel','QLineEdit','QPushButton','QProgressBar','QVBoxLayout','QHBoxLayout')}
    namespace.update(NexusDialog=NexusDialog, stylesheet=stylesheet, TOKENS=TOKENS, Path=Path, os=os)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[window], type_ignores=[])), str(path), 'exec'), namespace)
    view = namespace['Window']()
    view.progress(('DOWNLOADING', 50, 100))
    assert view.percent.text() == '50%'
    assert not view.bar.isTextVisible()
    assert view.bar.value() == 50
    view.progress(('CHECKING', 0, 0))
    assert view.percent.text() == '…'
    assert view.bar.maximum() == 0
    view.result((None, 'synthetic error'))
    assert view.percent.text() == 'Установка не завершена'
    assert view.bar.value() == 0
    assert view.completion is None
    assert view.worker is None
    view.close()
