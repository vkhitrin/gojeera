import asyncio

from gojeera.app import JiraApp
from gojeera.themes import create_theme_from_config

from .test_helpers import wait_for_mount


async def wait_for_loaded_work_item(pilot):
    await wait_for_mount(pilot)

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)

    await pilot.press('enter')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)


class TestAppAppearance:
    """Snapshot tests to verify TUI appearance at various states."""

    def test_app_with_terminal_size_small(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(80, 24), run_before=wait_for_loaded_work_item)

    def test_app_with_default_theme(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        config = mock_configuration

        config.theme = None

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_loaded_work_item)

    def test_app_with_theme_dracula(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        config = mock_configuration

        config.theme = 'dracula'

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_loaded_work_item)

    def test_app_with_custom_theme(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        config = mock_configuration

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

        app = JiraApp(settings=config, user_info=mock_user_info)
        app.register_theme(custom_theme)

        config.theme = 'custom-test-theme'
        app.theme = 'custom-test-theme'

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_loaded_work_item)
