from gojeera.app import JiraApp
from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.work_log_screen import LogWorkScreen

from .test_helpers import wait_until


async def open_dirty_modal_confirmation_screen(pilot):
    screen = LogWorkScreen(work_item_key='ENG-1', mode='new')
    await pilot.app.push_screen(screen)

    await wait_until(lambda: isinstance(pilot.app.screen, LogWorkScreen), timeout=3.0)
    screen.reset_dirty_state()
    assert not screen.is_dirty()

    screen.time_spent_input.value = '2h'
    await wait_until(lambda: screen.is_dirty(), timeout=3.0)

    screen.action_dismiss_screen_with_ctrl_c()
    await wait_until(lambda: isinstance(pilot.app.screen, ConfirmationScreen), timeout=3.0)

    assert isinstance(pilot.app.screen, ConfirmationScreen)
    assert pilot.app.screen.message == 'Discard unsaved changes and close this screen?'


class TestExtendedModalScreen:
    def test_dismiss_with_ctrl_c_action_shows_confirmation_screen_when_dirty(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_dirty_modal_confirmation_screen,
        )
