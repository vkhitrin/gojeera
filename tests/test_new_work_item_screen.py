import asyncio

from textual.widgets import Button

from gojeera.app import JiraApp
from gojeera.components.new_work_item_screen import AddWorkItemScreen
from gojeera.components.unified_search import UnifiedSearchBar
from gojeera.components.work_item_result import WorkItemSearchResultsScroll
from gojeera.utils.widgets_factory_utils import DynamicFieldWrapper
from gojeera.widgets.selection import SelectionWidget

from .test_helpers import wait_for_mount


async def open_new_work_item_screen(pilot):
    """Open the new work item screen."""
    await wait_for_mount(pilot)
    # Press ctrl+n to open new work item screen
    await pilot.press('ctrl+n')
    await asyncio.sleep(0.5)  # Wait for screen to render


async def open_and_select_project(pilot):
    """Open new work item screen and select a project."""
    await open_new_work_item_screen(pilot)
    # Focus on project selector and open it
    await pilot.press('tab')  # Tab to project selector
    await asyncio.sleep(0.2)
    await pilot.press('enter')  # Open dropdown
    await asyncio.sleep(0.3)
    await pilot.press('down', 'enter')  # Select first project
    await asyncio.sleep(0.5)


async def fill_required_fields(pilot):
    """Open new work item screen and fill required fields."""
    await open_and_select_project(pilot)

    # Select work item type
    await pilot.press('tab')  # Tab to type selector
    await asyncio.sleep(0.2)
    await pilot.press('enter')  # Open dropdown
    await asyncio.sleep(0.3)
    await pilot.press('down', 'enter')  # Select first type
    await asyncio.sleep(1.0)  # Wait longer for create metadata to load
    await pilot.app.workers.wait_for_complete()  # Wait for create metadata API call

    # Reporter should be auto-selected to current user, so skip it
    await pilot.press('tab')  # Tab past reporter selector
    await asyncio.sleep(0.2)

    # Skip assignee (optional)
    await pilot.press('tab')
    await asyncio.sleep(0.2)

    # Fill summary
    await pilot.press('tab')  # Tab to summary field
    await asyncio.sleep(0.2)
    await pilot.press(*'Test work item summary')
    await asyncio.sleep(0.3)

    # Navigate to description field to blur summary and trigger validation
    await pilot.press('tab')
    await asyncio.sleep(0.3)

    # Directly interact with Priority field (required dynamic field)
    # Get the screen - it's a modal screen, so use screen instead of query_one
    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    # Find the priority widget through the dynamic fields container
    priority_widget = None
    for wrapper in screen.dynamic_fields_container.query(DynamicFieldWrapper):
        selection_widgets = wrapper.query(SelectionWidget)
        for widget in selection_widgets:
            if hasattr(widget, 'field_id') and widget.field_id == 'priority':
                priority_widget = widget
                break
        if priority_widget:
            break

    assert priority_widget is not None, 'Priority widget not found'

    priority_widget.value = '1'  # Set to 'Highest' (id='1')
    await asyncio.sleep(0.3)

    # Trigger validation and update save button state
    screen.save_button.disabled = not screen._validate_required_fields()
    await asyncio.sleep(0.3)

    # Verify all required fields are filled before snapshot
    pending_fields = screen._get_pending_dynamic_fields()
    assert len(pending_fields) == 0, f'Required fields still pending: {pending_fields}'


async def fill_and_save_work_item(pilot):
    """Fill required fields and press the Save button."""
    await fill_required_fields(pilot)

    # Get the screen and press Save button
    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    # Verify save button is enabled
    assert not screen.save_button.disabled, 'Save button should be enabled before pressing'

    # Press the Save button
    screen.save_button.press()

    # Wait for save operation and screen dismissal
    await asyncio.sleep(1.5)

    # Screen should be dismissed back to MainScreen
    assert not isinstance(pilot.app.screen, AddWorkItemScreen), (
        f'Expected to return to MainScreen, but still on {type(pilot.app.screen)}'
    )


async def fill_save_and_search_work_item(pilot):
    """Fill required fields, save, open unified search, and search for the created work item."""
    await fill_and_save_work_item(pilot)

    # Open unified search with Ctrl+J
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.3)

    # Verify unified search bar is visible
    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    assert search_bar is not None, 'Unified search bar should be visible'
    assert search_bar.search_mode == 'basic', f'Expected basic mode, got {search_bar.search_mode}'

    # Get the work item key input and focus it directly
    work_item_input = search_bar.query_one('#basic-work-item-key')
    work_item_input.focus()
    await asyncio.sleep(0.2)

    # Type the work item key
    for char in 'EXAMPLE-2':
        await pilot.press(char)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    # Verify the input is valid
    assert not work_item_input.has_class('-invalid'), (
        f'Expected valid work item key but input has -invalid class. Value: "{work_item_input.value}"'
    )

    # Press the search button directly
    search_button = search_bar.query_one('#unified-search-button', Button)
    search_button.press()
    await asyncio.sleep(1.5)  # Wait for search to complete and results to load

    # Verify search results appear
    search_results_list = pilot.app.screen.query_one(WorkItemSearchResultsScroll)
    assert search_results_list is not None, 'Search results list should be visible'
    assert search_results_list.work_item_search_results is not None, (
        'Search results should be populated'
    )

    # Verify the newly created work item appears in results
    search_results = search_results_list.work_item_search_results
    assert search_results.work_items is not None, 'Search results should have work_items'
    assert len(search_results.work_items) == 1, (
        f'Expected 1 work item in results, got {len(search_results.work_items)}'
    )

    work_item = search_results.work_items[0]
    assert work_item.key == 'EXAMPLE-2', (
        f'Expected work item key "EXAMPLE-2", got "{work_item.key}"'
    )
    assert work_item.summary == 'Test work item summary', (
        f'Expected summary "Test work item summary", got "{work_item.summary}"'
    )


class TestNewWorkItemScreen:
    """Snapshot tests to verify new work item screen display and interactions."""

    def test_new_work_item_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_with_new_work_item, mock_user_info
    ):
        """Snapshot: New work item screen in initial state."""
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_new_work_item_screen)

    def test_new_work_item_all_required_filled(
        self, snap_compare, mock_configuration, mock_jira_api_with_new_work_item, mock_user_info
    ):
        """Snapshot: New work item screen with all required fields filled."""
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_required_fields)

    def test_new_work_item_save_and_search(
        self, snap_compare, mock_configuration, mock_jira_api_with_new_work_item, mock_user_info
    ):
        """Snapshot: After saving new work item and searching for it, results appear."""
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_save_and_search_work_item)
