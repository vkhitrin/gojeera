import asyncio

from gojeera.app import JiraApp
from gojeera.components.screens.work_log_screen import LogWorkScreen

from .test_helpers import wait_until


async def open_log_work_screen_empty(pilot):
    screen = LogWorkScreen(work_item_key='ENG-1', mode='new')
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.2)

    assert isinstance(pilot.app.screen, LogWorkScreen), (
        f'Expected LogWorkScreen, got {type(pilot.app.screen)}'
    )
    assert screen.save_button.disabled, 'Save button should be disabled initially'
    assert screen.time_spent_input.value == '', 'Time spent should be empty initially'


async def open_log_work_screen_with_valid_fields(pilot):
    await open_log_work_screen_empty(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, LogWorkScreen)

    await wait_until(lambda: screen.time_spent_input.has_focus, timeout=2.0)
    screen.time_spent_input.value = '2h'
    await wait_until(lambda: not screen.save_button.disabled, timeout=2.0)

    assert not screen.save_button.disabled, 'Save button should be enabled with valid time spent'
    assert screen.time_spent_input.value == '2h', (
        f'Time spent should be "2h", got {screen.time_spent_input.value}'
    )


class TestLogWorkScreen:
    def test_log_work_screen_empty_state(self, snap_compare, mock_configuration, mock_user_info):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_log_work_screen_empty)

    def test_log_work_screen_valid_fields(self, snap_compare, mock_configuration, mock_user_info):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app, terminal_size=(120, 40), run_before=open_log_work_screen_with_valid_fields
        )
