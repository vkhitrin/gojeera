"""Tests for panel_picker_screen.py component."""

import asyncio

from textual.widgets import TextArea
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.panel_picker_screen import PanelPickerScreen


async def navigate_to_comments_tab(pilot):
    """Navigate to work item and open Comments tab."""
    # Open search and select work item
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.3)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    # Wait for workers to complete
    await pilot.app.workers.wait_for_complete()

    # Navigate to Comments tab (5x right from Summary)
    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.1)

    for _ in range(5):
        await pilot.press('right')
        await asyncio.sleep(0.1)

    await asyncio.sleep(0.3)


async def open_add_comment_screen(pilot):
    """Navigate to Comments tab and open Add Comment screen."""
    await navigate_to_comments_tab(pilot)

    # Trigger add comment action (ctrl+n)
    await pilot.press('ctrl+n')
    await asyncio.sleep(0.3)

    # Wait for workers
    await pilot.app.workers.wait_for_complete()

    # Verify CommentScreen is pushed
    assert isinstance(pilot.app.screen, CommentScreen)
    assert pilot.app.screen.mode == 'new'

    # Focus the textarea
    textarea = pilot.app.screen.query_one(TextArea)
    textarea.focus()
    await asyncio.sleep(0.3)


def create_open_panel_picker_via_full_flow():
    """Factory to create helper that opens panel picker via complete user flow."""

    async def open_panel_picker_via_full_flow(pilot):
        """Complete flow: Search work item → Comments tab → Add Comment → Insert Panel."""
        # Navigate through complete user flow
        await open_add_comment_screen(pilot)

        # Now on CommentScreen with textarea focused
        comment_screen = pilot.app.screen
        assert isinstance(comment_screen, CommentScreen)

        # Wait for workers to complete before triggering insert panel
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        # Trigger Insert Panel action (simulates command palette invocation)
        # This now runs in a worker (non-blocking)
        comment_screen.action_insert_alert()

        # Wait for screen to be pushed (but DON'T wait for worker to complete
        # because it's blocked on push_screen_wait waiting for modal dismiss)
        await asyncio.sleep(1.0)

        # Verify PanelPickerScreen is displayed
        assert isinstance(pilot.app.screen, PanelPickerScreen), (
            f'Expected PanelPickerScreen, got {type(pilot.app.screen)}'
        )
        screen = pilot.app.screen

        # Verify no error notifications are present
        notifications = list(pilot.app._notifications)
        assert len(notifications) == 0, (
            f'Expected no notifications, but found {len(notifications)} notification(s)'
        )

        # Verify Insert button is disabled initially
        assert screen.insert_button.disabled is True, 'Insert button should be disabled initially'

    return open_panel_picker_via_full_flow


def create_open_panel_picker_via_full_flow_with_selection():
    """Factory to create helper that opens panel picker via complete flow and selects a panel type."""
    open_with_panel = create_open_panel_picker_via_full_flow()

    async def open_panel_picker_via_full_flow_with_selection(pilot):
        """Complete flow with panel selection."""
        await open_with_panel(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, PanelPickerScreen)

        # Simulate panel selection by setting the select value
        # Use the first alert type (Note)
        first_alert = screen.ALERT_TYPES[0]  # ('Note', ('[!NOTE]', 'Note'))
        screen.alert_select.value = first_alert[1]  # ('[!NOTE]', 'Note')
        await asyncio.sleep(0.1)

        # Verify Insert button is enabled after selection
        assert screen.insert_button.disabled is False, (
            'Insert button should be enabled after panel selection'
        )
        assert screen.alert_select.value == first_alert[1], (
            f'Expected selected value to be first alert tuple, got {screen.alert_select.value}'
        )

    return open_panel_picker_via_full_flow_with_selection


def create_insert_panel_and_return_to_comment_screen():
    """Factory to create helper that inserts a panel and returns to CommentScreen for snapshot."""

    async def insert_panel_and_return_to_comment_screen(pilot):
        """Complete flow: navigate → insert panel → dismiss → back on CommentScreen with panel inserted."""
        # Navigate through complete user flow
        await open_add_comment_screen(pilot)

        # Now on CommentScreen with textarea focused
        comment_screen = pilot.app.screen
        assert isinstance(comment_screen, CommentScreen)

        # Wait for workers to complete before triggering insert panel
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        # Trigger Insert Panel action
        comment_screen.action_insert_alert()

        # Wait for PanelPickerScreen to be displayed
        await asyncio.sleep(1.0)

        # Verify PanelPickerScreen is displayed
        assert isinstance(pilot.app.screen, PanelPickerScreen), (
            f'Expected PanelPickerScreen, got {type(pilot.app.screen)}'
        )
        picker_screen = pilot.app.screen

        # Select the first panel type (Note)
        first_alert = picker_screen.ALERT_TYPES[0]  # ('Note', ('[!NOTE]', 'Note'))
        picker_screen.alert_select.value = first_alert[1]  # ('[!NOTE]', 'Note')
        await asyncio.sleep(0.2)

        # Click the Insert button to dismiss the screen and insert the panel
        await pilot.click('#alert-button-insert')
        await asyncio.sleep(0.3)

        # Wait for worker to complete the insertion
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        # Verify we're back on the CommentScreen
        assert isinstance(pilot.app.screen, CommentScreen), (
            f'Expected CommentScreen after dismissal, got {type(pilot.app.screen)}'
        )

    return insert_panel_and_return_to_comment_screen


class TestPanelPickerScreen:
    """Snapshot tests to verify PanelPickerScreen via complete user navigation flow."""

    def test_panel_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_api_with_search_results,
    ):
        """Snapshot: Panel Picker via full flow (Search → Comments → Add Comment → Insert Panel)."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        open_panel = create_open_panel_picker_via_full_flow()
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_panel)

    def test_panel_picker_with_selection(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_api_with_search_results,
    ):
        """Snapshot: Panel Picker via full flow with panel selected (Insert button enabled)."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        open_with_selection = create_open_panel_picker_via_full_flow_with_selection()
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_with_selection)

    def test_panel_insert_panel(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_api_with_search_results,
    ):
        """Snapshot: CommentScreen after panel inserted (verify panel text in textarea)."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        insert_panel = create_insert_panel_and_return_to_comment_screen()
        assert snap_compare(app, terminal_size=(120, 40), run_before=insert_panel)
