import asyncio

from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.new_work_item_screen import AddWorkItemScreen


async def open_add_subtask_screen(pilot):
    """Navigate to work item and open Add Work Item screen as a subtask."""
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')  # Trigger search
    await asyncio.sleep(0.5)
    await pilot.press('enter')  # Select first work item (EXAMPLE-19539)
    await asyncio.sleep(0.8)  # Wait for work item to load

    # Navigate to Subtasks tab

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)
    await pilot.press('right')  # Move to Attachments tab
    await asyncio.sleep(0.2)
    await pilot.press('right')  # Move to Subtasks tab
    await asyncio.sleep(0.5)  # Wait for subtasks to load

    # Trigger new subtask action (ctrl+n when Subtasks tab is active)
    await pilot.press('ctrl+n')  # Open Add Work Item screen as subtask

    # Wait for the AddWorkItemScreen to fully load

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    # Wait for all background workers to complete (fetch projects, types, users)
    await pilot.app.workers.wait_for_complete()

    # Give UI additional time to update and process after workers complete
    await asyncio.sleep(1.0)

    # NOTE: (vkhitrin) revisit this test!
    # Force a UI refresh to ensure all updates are processed
    # This is needed because the worker may complete before the UI is fully ready,
    # so calling the lazy load again ensures the cached data is applied to the UI
    screen._lazy_load_work_item_types()
    await asyncio.sleep(0.5)

    # Verify parent work item key is set
    assert screen._parent_work_item_key == 'EXAMPLE-19539', (
        f'Expected parent work item key to be EXAMPLE-19539, got {screen._parent_work_item_key}'
    )

    # Verify that issue type was auto-selected to Sub-task (ID 10002)
    work_item_type_value = screen.work_item_type_selector.value
    assert work_item_type_value == '10002', (
        f'Expected Sub-task issue type (10002) to be auto-selected, '
        f'got {work_item_type_value}. '
        f'Types fetched for project: {screen._types_fetched_for_project}'
    )

    # Verify reporter was auto-selected to the current user
    reporter_value = screen.reporter_selector.value
    assert reporter_value == '555000:11111111-1111-1111-1111-111111111111', (
        f'Expected reporter to be auto-selected to test user account ID, got {reporter_value}'
    )

    # Verify Save button is disabled (no summary yet)
    assert screen.save_button.disabled, (
        'Expected Save button to be disabled initially (missing summary)'
    )


async def fill_required_fields_and_verify_save_enabled(pilot):
    """Fill required fields and verify Save button becomes enabled."""
    await open_add_subtask_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    # Verify Save button starts as disabled
    assert screen.save_button.disabled, 'Expected Save button to be disabled before filling summary'

    # Fill in the summary field (the only remaining required field)
    summary_field = screen.summary_field
    summary_field.focus()
    await asyncio.sleep(0.1)

    # Type a summary
    await pilot.press(*'Test subtask summary')
    await asyncio.sleep(0.2)

    # Blur the field to trigger validation
    await pilot.press('tab')
    await asyncio.sleep(0.3)

    # Verify Save button is now enabled
    assert not screen.save_button.disabled, (
        f'Expected Save button to be enabled after filling summary. '
        f'Summary value: "{screen.summary_field.value}"'
    )


class TestNewSubtaskScreen:
    """Snapshot tests to verify AddWorkItemScreen appearance when creating subtasks."""

    def test_new_subtask_screen_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        """Snapshot: Add Work Item screen opened from Subtasks tab (creating a subtask).

        Verifies:
        - Parent work item key is set
        - Issue type is auto-selected to Sub-task
        - Reporter is auto-selected to current user
        - Save button is disabled (no summary yet)
        """
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_add_subtask_screen)

    def test_new_subtask_screen_with_filled_fields(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        """Snapshot: Add Work Item screen with all required fields filled.

        Verifies:
        - Required fields (project, issue type, reporter, summary) are filled
        - Save button becomes enabled after filling summary
        """
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=fill_required_fields_and_verify_save_enabled,
        )
