import asyncio

from textual.widgets import Button

from gojeera.app import JiraApp, MainScreen
from gojeera.components.clone_work_item_screen import CloneWorkItemScreen
from gojeera.components.unified_search import UnifiedSearchBar
from gojeera.components.work_item_result import WorkItemSearchResultsScroll


async def clone_and_search_work_item(pilot):
    work_item_key = 'EXAMPLE-1234'
    original_summary = 'Original Work Item Summary'

    # NOTE: (vkhitrin) we directly "enter" the screen without navigating
    #       the UI.
    screen = CloneWorkItemScreen(work_item_key=work_item_key, original_summary=original_summary)
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)

    assert isinstance(pilot.app.screen, CloneWorkItemScreen)
    assert pilot.app.screen.work_item_key == work_item_key
    assert pilot.app.screen.original_summary == original_summary

    assert screen.summary_input.value == 'CLONE - Original Work Item Summary'
    assert not screen.clone_button.disabled

    clone_button = screen.clone_button
    clone_button.press()

    await asyncio.sleep(1.5)

    assert isinstance(pilot.app.screen, MainScreen)

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.3)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    assert search_bar is not None, 'Unified search bar should be visible'
    assert search_bar.search_mode == 'basic', f'Expected basic mode, got {search_bar.search_mode}'

    work_item_input = search_bar.query_one('#basic-work-item-key')
    work_item_input.focus()
    await asyncio.sleep(0.2)

    for char in 'EXAMPLE-2':
        await pilot.press(char)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    assert not work_item_input.has_class('-invalid'), (
        f'Expected valid work item key but input has -invalid class. Value: "{work_item_input.value}"'
    )

    search_button = search_bar.query_one('#unified-search-button', Button)
    search_button.press()
    await asyncio.sleep(1.5)

    search_results_list = pilot.app.screen.query_one(WorkItemSearchResultsScroll)
    assert search_results_list is not None, 'Search results list should be visible'
    assert search_results_list.work_item_search_results is not None, (
        'Search results should be populated'
    )

    search_results = search_results_list.work_item_search_results
    assert search_results.work_items is not None, 'Search results should have work_items'
    assert len(search_results.work_items) == 1, (
        f'Expected 1 work item in results, got {len(search_results.work_items)}'
    )

    work_item = search_results.work_items[0]
    assert work_item.key == 'EXAMPLE-2', (
        f'Expected work item key "EXAMPLE-2", got "{work_item.key}"'
    )
    assert work_item.summary == 'CLONE - Original Work Item Summary', (
        f'Expected summary "CLONE - Original Work Item Summary", got "{work_item.summary}"'
    )


class TestCloneWorkItem:
    """Test work item clone."""

    def test_clone_work_item_and_search(
        self, snap_compare, mock_configuration, mock_jira_api_with_clone_work_item, mock_user_info
    ):
        config = mock_configuration
        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=clone_and_search_work_item)
