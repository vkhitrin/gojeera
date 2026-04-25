from gojeera.internal.styling.themes import create_theme_from_config

from .test_helpers import open_first_work_item_from_search, with_snapshot_assertion


async def wait_for_loaded_work_item(pilot):
    await open_first_work_item_from_search(pilot)


def _configure_custom_theme(app) -> None:
    custom_theme_config = {
        'name': 'custom-test-theme',
        'primary': '#00ff00',
        'secondary': '#ff00ff',
        'accent': '#ffff00',
        'background': '#1a1a1a',
        'surface': '#2a2a2a',
        'panel': '#3a3a3a',
        'foreground': '#e0e0e0',
        'success': '#00ff00',
        'warning': '#ffaa00',
        'error': '#ff0000',
        'dark': True,
    }
    custom_theme = create_theme_from_config(custom_theme_config)
    app.register_theme(custom_theme)
    app.config.theme = 'custom-test-theme'
    app.theme = 'custom-test-theme'


class TestAppAppearance:
    """Snapshot tests to verify TUI appearance at various states."""

    @with_snapshot_assertion(wait_for_loaded_work_item, terminal_size=(80, 24))
    def test_app_with_terminal_size_small(self):
        pass

    @with_snapshot_assertion(
        wait_for_loaded_work_item,
        configure_configuration=lambda config: setattr(config, 'theme', None),
    )
    def test_app_with_default_theme(self):
        pass

    @with_snapshot_assertion(
        wait_for_loaded_work_item,
        configure_configuration=lambda config: setattr(config, 'theme', 'dracula'),
    )
    def test_app_with_theme_dracula(self):
        pass

    @with_snapshot_assertion(
        wait_for_loaded_work_item,
        configure_app=lambda app: _configure_custom_theme(app),
    )
    def test_app_with_custom_theme(self):
        pass
