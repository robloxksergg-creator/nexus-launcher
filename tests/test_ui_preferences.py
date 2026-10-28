import pytest

from nexus_launcher.nexus_platform.ui_preferences import UIPreferences


def test_sound_default_and_restart(tmp_path):
    path = tmp_path / 'prefs.json'
    assert UIPreferences(path).sound_enabled()
    UIPreferences(path).save_sound(False)
    assert not UIPreferences(path).sound_enabled()
    UIPreferences(path).save_sound(True)
    assert UIPreferences(path).sound_enabled()


def test_corrupt_preferences_do_not_reenable_sound(tmp_path):
    path = tmp_path / 'prefs.json'
    path.write_text('invalid', encoding='utf-8')
    assert not UIPreferences(path).sound_enabled()


def test_only_boolean_is_accepted(tmp_path):
    with pytest.raises(ValueError):
        UIPreferences(tmp_path / 'prefs.json').save_sound('false')
