import asyncio

from gojeera.app import JiraApp
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown


async def open_debug_screen(pilot):
    await asyncio.sleep(0.5)
    await pilot.press('f12')
    await asyncio.sleep(0.5)


async def open_debug_and_switch_to_server_tab(pilot):
    await open_debug_screen(pilot)
    await pilot.press('right_square_bracket')
    await asyncio.sleep(0.5)


async def open_debug_and_switch_to_user_tab(pilot):
    await open_debug_screen(pilot)
    await pilot.press('right_square_bracket', 'right_square_bracket')
    await asyncio.sleep(0.5)


async def open_debug_and_switch_to_server_tab_with_obfuscation(pilot):
    await open_debug_screen(pilot)
    await pilot.press('right_square_bracket')
    await asyncio.sleep(0.5)

    debug_screen = pilot.app.screen

    server_md = debug_screen.query_one('#server-markdown', GojeeraMarkdown)

    markdown_content = getattr(server_md, '_markdown', '')

    assert 'obfuscated' in markdown_content, (
        f"Expected 'obfuscated' in server info, but got: {markdown_content}"
    )
    assert 'https://example.atlassian.net' not in markdown_content, (
        'Server URL should be obfuscated'
    )


class TestDebugScreen:
    def test_debug_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_debug_screen)

    def test_debug_screen_server_tab(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(
            app, terminal_size=(120, 40), run_before=open_debug_and_switch_to_server_tab
        )

    def test_debug_screen_user_tab(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(
            app, terminal_size=(120, 40), run_before=open_debug_and_switch_to_user_tab
        )

    def test_debug_screen_server_tab_with_obfuscation(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration
        config.obfuscate_personal_info = True

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_debug_and_switch_to_server_tab_with_obfuscation,
        )
