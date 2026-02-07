import asyncio

from textual.widgets import Button, Input
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp


async def open_work_item_and_edit(pilot):
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)

    await pilot.press('ctrl+e')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    save_button = screen.query_one('#edit-work-item-button-save', Button)
    assert save_button.disabled, 'Save button should be disabled in initial state'


async def open_edit_screen_and_modify_fields(pilot):
    await open_work_item_and_edit(pilot)

    screen = pilot.app.screen
    summary_input = screen.query_one('#edit-work-item-summary', Input)
    summary_input.focus()
    await asyncio.sleep(0.2)

    summary_input.value = summary_input.value + ' - Modified'
    await asyncio.sleep(0.3)

    await pilot.press('tab')
    await asyncio.sleep(0.3)

    await pilot.press(*'Updated description with new content')
    await asyncio.sleep(0.3)

    save_button = screen.query_one('#edit-work-item-button-save', Button)
    assert not save_button.disabled, 'Save button should be enabled after making changes'


async def open_edit_screen_and_clear_summary(pilot):
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)

    await pilot.press('ctrl+e')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    summary_input = screen.query_one('#edit-work-item-summary', Input)
    summary_input.focus()
    await asyncio.sleep(0.2)

    summary_input.value = ''
    await asyncio.sleep(0.3)

    save_button = screen.query_one('#edit-work-item-button-save', Button)
    assert save_button.disabled, 'Save button should be disabled when summary is empty'


class TestEditWorkItemInfoScreen:
    def test_edit_work_item_info_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_work_item_and_edit)

    def test_edit_work_item_info_screen_fields_modified(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app, terminal_size=(120, 40), run_before=open_edit_screen_and_modify_fields
        )

    def test_edit_work_item_info_screen_empty_summary(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app, terminal_size=(120, 40), run_before=open_edit_screen_and_clear_summary
        )
