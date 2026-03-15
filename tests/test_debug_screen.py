import asyncio

from gojeera.app import JiraApp


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
