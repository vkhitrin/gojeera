"""Tests for user_mention_picker_screen.py component."""

import asyncio

from textual.widgets import TextArea
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.user_mention_picker_screen import UserMentionPickerScreen
from gojeera.models import JiraUser


def convert_user_fixture_to_jira_user(user_data: dict) -> JiraUser:
    """Convert user fixture data to JiraUser object.

    Args:
        user_data: User data from fixture with keys: accountId, displayName, emailAddress, active

    Returns:
        JiraUser object
    """
    return JiraUser(
        account_id=str(user_data.get('accountId', '')),
        active=bool(user_data.get('active', True)),
        display_name=str(user_data.get('displayName', '')),
        email=user_data.get('emailAddress'),
    )


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


def create_open_user_mention_picker_via_full_flow_with_users(mock_jira_users):
    """Factory to create helper that opens user mention picker via complete user flow with users."""

    async def open_user_mention_picker_via_full_flow_with_users(pilot):
        """Complete flow: Search work item → Comments tab → Add Comment → Insert Mention."""
        # Navigate through complete user flow
        # Note: user/assignable/search endpoint is already mocked in mock_jira_api_with_search_results fixture
        await open_add_comment_screen(pilot)

        # Now on CommentScreen with textarea focused
        comment_screen = pilot.app.screen
        assert isinstance(comment_screen, CommentScreen)

        # Wait for workers to complete before triggering insert mention
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        # Trigger Insert Mention action (simulates command palette invocation)
        # This now runs in a worker (non-blocking)
        comment_screen.action_insert_mention()

        # Wait for screen to be pushed (but DON'T wait for worker to complete
        # because it's blocked on push_screen_wait waiting for modal dismiss)
        await asyncio.sleep(1.0)

        # Verify UserMentionPickerScreen is displayed
        assert isinstance(pilot.app.screen, UserMentionPickerScreen), (
            f'Expected UserMentionPickerScreen, got {type(pilot.app.screen)}'
        )
        screen = pilot.app.screen

        # Verify no error notifications are present
        notifications = list(pilot.app._notifications)
        assert len(notifications) == 0, (
            f'Expected no notifications, but found {len(notifications)} notification(s)'
        )

        # Verify Insert button is disabled initially
        assert screen.insert_button.disabled is True, 'Insert button should be disabled initially'

        # Verify users are loaded
        assert len(screen._all_users) > 0, 'Users should be loaded'

    return open_user_mention_picker_via_full_flow_with_users


def create_open_user_mention_picker_via_full_flow_with_selection(mock_jira_users):
    """Factory to create helper that opens user mention picker via complete flow and selects a user."""
    open_with_users = create_open_user_mention_picker_via_full_flow_with_users(mock_jira_users)

    async def open_user_mention_picker_via_full_flow_with_selection(pilot):
        """Complete flow with user selection."""
        await open_with_users(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, UserMentionPickerScreen)

        # Simulate user selection by setting the select value
        # Use the first user from the fixture
        first_user = convert_user_fixture_to_jira_user(mock_jira_users[0])
        screen.user_select.value = (first_user.account_id, first_user.display_name)
        await asyncio.sleep(0.1)

        # Verify Insert button is enabled after selection
        assert screen.insert_button.disabled is False, (
            'Insert button should be enabled after user selection'
        )
        assert screen.user_select.value == (first_user.account_id, first_user.display_name), (
            f'Expected selected value to be first user tuple, got {screen.user_select.value}'
        )

    return open_user_mention_picker_via_full_flow_with_selection


def create_insert_mention_and_return_to_comment_screen(mock_jira_users):
    """Factory to create helper that inserts a mention and returns to CommentScreen for snapshot."""

    async def insert_mention_and_return_to_comment_screen(pilot):
        """Complete flow: navigate → insert mention → dismiss → back on CommentScreen with mention inserted."""
        # Navigate through complete user flow
        await open_add_comment_screen(pilot)

        # Now on CommentScreen with textarea focused
        comment_screen = pilot.app.screen
        assert isinstance(comment_screen, CommentScreen)

        # Wait for workers to complete before triggering insert mention
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        # Trigger Insert Mention action
        comment_screen.action_insert_mention()

        # Wait for UserMentionPickerScreen to be displayed
        await asyncio.sleep(1.0)

        # Verify UserMentionPickerScreen is displayed
        assert isinstance(pilot.app.screen, UserMentionPickerScreen), (
            f'Expected UserMentionPickerScreen, got {type(pilot.app.screen)}'
        )
        picker_screen = pilot.app.screen

        # Select the first user
        first_user = convert_user_fixture_to_jira_user(mock_jira_users[0])
        picker_screen.user_select.value = (first_user.account_id, first_user.display_name)
        await asyncio.sleep(0.2)

        # Click the Insert button to dismiss the screen and insert the mention
        await pilot.click('#user-mention-button-insert')
        await asyncio.sleep(0.3)

        # Wait for worker to complete the insertion
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        # Verify we're back on the CommentScreen
        assert isinstance(pilot.app.screen, CommentScreen), (
            f'Expected CommentScreen after dismissal, got {type(pilot.app.screen)}'
        )

    return insert_mention_and_return_to_comment_screen


class TestUserMentionPickerScreen:
    """Snapshot tests to verify UserMentionPickerScreen via complete user navigation flow."""

    def test_user_mention_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_users,
        mock_jira_api_with_search_results,
    ):
        """Snapshot: User Mention Picker via full flow (Search → Comments → Add Comment → Insert Mention)."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        open_with_users = create_open_user_mention_picker_via_full_flow_with_users(mock_jira_users)
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_with_users)

    def test_user_mention_picker_with_selection(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_users,
        mock_jira_api_with_search_results,
    ):
        """Snapshot: User Mention Picker via full flow with user selected (Insert button enabled)."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        open_with_selection = create_open_user_mention_picker_via_full_flow_with_selection(
            mock_jira_users
        )
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_with_selection)

    def test_user_mention_insert_user_mention(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_users,
        mock_jira_api_with_search_results,
    ):
        """Snapshot: CommentScreen after mention inserted (verify mention text in textarea)."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        insert_mention = create_insert_mention_and_return_to_comment_screen(mock_jira_users)
        assert snap_compare(app, terminal_size=(120, 40), run_before=insert_mention)
