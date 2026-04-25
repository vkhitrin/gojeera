import asyncio

from gojeera.widgets.layout.record_list import RecordList

from .test_helpers import assert_confirmation_screen, assert_snapshot_matches, focus_work_item_tab


async def open_confirmation_screen_via_delete_attachment(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=1)

    record_list = pilot.app.screen.query_one(RecordList)
    record_list.focus()
    await asyncio.sleep(0.3)

    await pilot.press('ctrl+d')
    await asyncio.sleep(0.5)

    screen = assert_confirmation_screen(pilot.app.screen)
    assert screen.message == 'Are you sure you want to delete the file?', (
        f'Expected delete file message, got: {screen.message}'
    )


OPEN = open_confirmation_screen_via_delete_attachment


class TestConfirmationScreen:
    def test_confirmation_screen_via_delete_attachment(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, OPEN)
