from textual.theme import Theme
import pytest

from tests.config_test_helpers import write_custom_theme_config

from gojeera.internal.store.config import ApplicationConfiguration
from gojeera.internal.styling.themes import create_theme_from_config, load_themes_from_directory


def test_custom_theme_uses_textual_theme_types(monkeypatch, tmp_path):
    write_custom_theme_config(
        monkeypatch,
        tmp_path,
        '  - name: "custom"',
        '    primary: "#ffffff"',
        '    dark: "true"',
    )

    config = ApplicationConfiguration()

    assert config.custom_themes is not None
    assert isinstance(config.custom_themes[0], Theme)
    assert config.custom_themes[0].dark is True


def test_create_theme_from_config_coerces_textual_theme_fields():
    theme = create_theme_from_config(
        {
            'name': 'custom',
            'primary': '#ffffff',
            'dark': 'true',
        }
    )

    assert isinstance(theme, Theme)
    assert theme.dark is True


def test_create_theme_from_config_rejects_unexpected_field():
    with pytest.raises(ValueError, match="unexpected field 'naaame'"):
        create_theme_from_config(
            {
                'naaame': 'custom',
                'primary': '#ffffff',
            }
        )


def test_load_themes_from_directory_raises_for_invalid_theme_file(tmp_path):
    themes_dir = tmp_path / 'themes'
    themes_dir.mkdir()
    (themes_dir / 'broken.yaml').write_text(
        '\n'.join(
            [
                'naaame: "custom"',
                'primary: "#ffffff"',
            ]
        )
    )

    with pytest.raises(ValueError, match='Invalid theme file "broken.yaml"'):
        load_themes_from_directory(themes_dir)
