import asyncio

from gojeera.app import JiraApp
from gojeera.components.quit_screen import QuitScreen


async def open_quit_screen(pilot):
    screen = QuitScreen()
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)

    assert isinstance(pilot.app.screen, QuitScreen)


class TestQuitScreen:
    def test_quit_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_quit_screen)
