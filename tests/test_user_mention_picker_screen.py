"""Tests for user_mention_picker_screen.py component."""

import asyncio

from gojeera.app import JiraApp
from gojeera.components.screens.comment_screen import CommentScreen
from gojeera.components.screens.user_mention_picker_screen import UserMentionPickerScreen
from gojeera.internal.jira.factories import WorkItemFactory

from .test_helpers import open_add_comment_screen, wait_until


def create_open_user_mention_picker_via_full_flow_with_users(mock_jira_users):
    """Factory to create helper that opens user mention picker via complete user flow with users."""

    async def open_user_mention_picker_via_full_flow_with_users(pilot):
        """Complete flow: Search work item → Comments tab → Add Comment → Insert Mention."""
        await open_add_comment_screen(pilot)

        comment_screen = pilot.app.screen
        assert isinstance(comment_screen, CommentScreen)

        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        comment_screen.action_insert_mention()
        await wait_until(lambda: isinstance(pilot.app.screen, UserMentionPickerScreen), timeout=2.0)

        screen = pilot.app.screen
        assert isinstance(screen, UserMentionPickerScreen)

        notifications = list(pilot.app._notifications)
        assert len(notifications) == 0, (
            f'Expected no notifications, but found {len(notifications)} notification(s)'
        )
        assert screen.insert_button.disabled, 'Insert button should be disabled initially'

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
        first_user = WorkItemFactory.build_required_jira_user(mock_jira_users[0])
        screen.user_select.value = (first_user.account_id, first_user.display_name)
        await wait_until(lambda: not screen.insert_button.disabled)

        # Verify Insert button is enabled after selection
        assert not screen.insert_button.disabled, (
            'Insert button should be enabled after user selection'
        )
        assert screen.user_select.value == (first_user.account_id, first_user.display_name), (
            f'Expected selected value to be first user tuple, got {screen.user_select.value}'
        )

        # Snapshot a stable post-selection state without the focused type-to-search cursor.
        screen.set_focus(screen.insert_button)
        await asyncio.sleep(0.1)

    return open_user_mention_picker_via_full_flow_with_selection


def create_insert_mention_and_return_to_comment_screen(mock_jira_users):
    """Factory to create helper that inserts a mention and returns to CommentScreen for snapshot."""

    async def insert_mention_and_return_to_comment_screen(pilot):
        """Complete flow: navigate → insert mention → dismiss → back on CommentScreen with mention inserted."""
        open_with_users = create_open_user_mention_picker_via_full_flow_with_users(mock_jira_users)
        await open_with_users(pilot)

        picker_screen = pilot.app.screen
        assert isinstance(picker_screen, UserMentionPickerScreen)

        # Select the first user
        first_user = WorkItemFactory.build_required_jira_user(mock_jira_users[0])
        picker_screen.user_select.value = (first_user.account_id, first_user.display_name)
        await wait_until(lambda: not picker_screen.insert_button.disabled)

        # Click the Insert button to dismiss the screen and insert the mention
        await pilot.click('#user-mention-button-insert')

        # Wait for worker to complete the insertion
        await pilot.app.workers.wait_for_complete()
        await wait_until(lambda: isinstance(pilot.app.screen, CommentScreen), timeout=2.0)

        # Verify we're back on the CommentScreen
        assert isinstance(pilot.app.screen, CommentScreen), (
            f'Expected CommentScreen after dismissal, got {type(pilot.app.screen)}'
        )

        inserted_mention = (
            f'[@{first_user.display_name}]('
            f'https://example.atlassian.acme.net/jira/people/{first_user.account_id})'
        )
        await wait_until(
            lambda: inserted_mention in pilot.app.screen.comment_field.text, timeout=2.0
        )

    return insert_mention_and_return_to_comment_screen


def with_user_mention_snapshot(run_before_factory):
    def decorator(_):
        def wrapper(
            self,
            snap_compare,
            mock_configuration,
            mock_user_info,
            mock_jira_users,
            mock_jira_api_with_search_results,
        ):
            self._assert_user_mention_snapshot(
                snap_compare,
                mock_configuration,
                mock_user_info,
                mock_jira_users,
                run_before_factory,
            )

        return wrapper

    return decorator


class TestUserMentionPickerScreen:
    """Snapshot tests to verify UserMentionPickerScreen via complete user navigation flow."""

    def _assert_user_mention_snapshot(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_users,
        run_before_factory,
    ) -> None:
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=run_before_factory(mock_jira_users),
        )

    @with_user_mention_snapshot(create_open_user_mention_picker_via_full_flow_with_users)
    def test_user_mention_initial_state(self):
        """Snapshot: User Mention Picker via full flow (Search → Comments → Add Comment → Insert Mention)."""

    @with_user_mention_snapshot(create_open_user_mention_picker_via_full_flow_with_selection)
    def test_user_mention_picker_with_selection(self):
        """Snapshot: User Mention Picker via full flow with user selected (Insert button enabled)."""

    @with_user_mention_snapshot(create_insert_mention_and_return_to_comment_screen)
    def test_user_mention_insert_user_mention(self):
        """Snapshot: CommentScreen after mention inserted (verify mention text in textarea)."""
