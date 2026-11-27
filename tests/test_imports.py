"""
Basic tests for the application.

This ensures all modules are importable and that the config is valid.
"""


def test_import_app():
    from siemens_mag8000.application import SiemensMag8000Application

    assert SiemensMag8000Application


def test_config():
    from siemens_mag8000.app_config import SiemensMag8000Config

    config = SiemensMag8000Config()
    assert isinstance(config.to_schema(), dict)


def test_ui():
    from siemens_mag8000.app_ui import SiemensMag8000UI

    assert SiemensMag8000UI


def test_tags():
    from siemens_mag8000.app_tags import SiemensMag8000Tags

    assert SiemensMag8000Tags


def test_state():
    from siemens_mag8000.app_state import SiemensMag8000State

    assert SiemensMag8000State
