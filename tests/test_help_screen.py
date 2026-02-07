import asyncio

from gojeera.app import JiraApp


async def open_help_screen(pilot):
    await asyncio.sleep(0.1)

    await pilot.press('question_mark')

    await asyncio.sleep(0.3)


async def open_help_and_scroll_down(pilot):
    await open_help_screen(pilot)
    viewer = pilot.app.screen.query_one('#help_viewer')
    viewer.scroll_down(animate=False)
    viewer.scroll_down(animate=False)
    viewer.scroll_down(animate=False)
    await asyncio.sleep(0.2)


async def open_help_and_select_topic(pilot):
    await open_help_screen(pilot)

    await pilot.press('tab')
    await asyncio.sleep(0.1)

    await pilot.press('down')
    await asyncio.sleep(0.1)

    await pilot.press('enter')
    await asyncio.sleep(0.2)


class TestHelpScreen:
    def test_help_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_help_screen)

    def test_help_screen_scrolled_down(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_help_and_scroll_down)

    def test_help_screen_topic_selected(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_help_and_select_topic)
