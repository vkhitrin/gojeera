"""Tests for decision_picker_screen.py component."""

import asyncio

from textual.widgets import TextArea
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.decision_picker_screen import DecisionPickerScreen


async def navigate_to_comments_tab(pilot):
    """Navigate to work item and open Comments tab."""
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.3)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()

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

    await pilot.press('ctrl+n')
    await asyncio.sleep(0.3)

    await pilot.app.workers.wait_for_complete()

    assert isinstance(pilot.app.screen, CommentScreen)
    assert pilot.app.screen.mode == 'new'

    textarea = pilot.app.screen.query_one(TextArea)
    textarea.focus()
    await asyncio.sleep(0.3)


def create_open_decision_picker_via_full_flow():

    async def open_decision_picker_via_full_flow(pilot):

        await open_add_comment_screen(pilot)

        comment_screen = pilot.app.screen
        assert isinstance(comment_screen, CommentScreen)

        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        comment_screen.action_insert_decision()

        await asyncio.sleep(1.0)

        assert isinstance(pilot.app.screen, DecisionPickerScreen), (
            f'Expected DecisionPickerScreen, got {type(pilot.app.screen)}'
        )
        screen = pilot.app.screen

        notifications = list(pilot.app._notifications)
        assert len(notifications) == 0, (
            f'Expected no notifications, but found {len(notifications)} notification(s)'
        )

        assert screen.insert_button.disabled is True, 'Insert button should be disabled initially'

    return open_decision_picker_via_full_flow


def create_open_decision_picker_via_full_flow_with_selection():
    open_with_decision = create_open_decision_picker_via_full_flow()

    async def open_decision_picker_via_full_flow_with_selection(pilot):
        """Complete flow with decision selection."""
        await open_with_decision(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, DecisionPickerScreen)

        first_decision = screen.DECISION_TYPES[0]
        screen.decision_select.value = first_decision[1]
        await asyncio.sleep(0.1)

        assert screen.insert_button.disabled is False, (
            'Insert button should be enabled after decision selection'
        )
        assert screen.decision_select.value == first_decision[1], (
            f'Expected selected value to be first decision tuple, got {screen.decision_select.value}'
        )

    return open_decision_picker_via_full_flow_with_selection


def create_insert_decision_and_return_to_comment_screen():

    async def insert_decision_and_return_to_comment_screen(pilot):
        """Complete flow: navigate → insert decision → dismiss → back on CommentScreen with decision inserted."""

        await open_add_comment_screen(pilot)

        comment_screen = pilot.app.screen
        assert isinstance(comment_screen, CommentScreen)

        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        comment_screen.action_insert_decision()

        await asyncio.sleep(1.0)

        assert isinstance(pilot.app.screen, DecisionPickerScreen), (
            f'Expected DecisionPickerScreen, got {type(pilot.app.screen)}'
        )
        picker_screen = pilot.app.screen

        first_decision = picker_screen.DECISION_TYPES[0]
        picker_screen.decision_select.value = first_decision[1]
        await asyncio.sleep(0.2)

        await pilot.click('#decision-button-insert')
        await asyncio.sleep(0.3)

        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        assert isinstance(pilot.app.screen, CommentScreen), (
            f'Expected CommentScreen after dismissal, got {type(pilot.app.screen)}'
        )

    return insert_decision_and_return_to_comment_screen


class TestDecisionPickerScreen:
    def test_decision_screen_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        open_decision = create_open_decision_picker_via_full_flow()
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_decision)

    def test_decision_screen_picker_with_selection(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        open_with_selection = create_open_decision_picker_via_full_flow_with_selection()
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_with_selection)

    def test_decision_insert_decision(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        insert_decision = create_insert_decision_and_return_to_comment_screen()
        assert snap_compare(app, terminal_size=(120, 40), run_before=insert_decision)
