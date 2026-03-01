import asyncio

from textual.widgets import Button, TextArea
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.work_item_comments import CommentsScrollView, WorkItemCommentsWidget


async def open_comments_tab_and_verify(pilot):

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

    comments_scroll = pilot.app.screen.query_one(CommentsScrollView)
    comments_scroll.focus()
    await asyncio.sleep(0.3)


async def create_comment_and_verify(pilot):

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

    await pilot.press('ctrl+n')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    assert isinstance(screen, CommentScreen)
    assert screen.mode == 'new'

    textarea = screen.query_one(TextArea)
    textarea.focus()
    await asyncio.sleep(0.1)

    test_comment = 'This is a new test comment added via the UI.'
    textarea.insert(test_comment)
    await asyncio.sleep(0.2)

    assert not screen.save_button.disabled, 'Save button should be enabled'
    screen.save_button.press()

    await asyncio.sleep(1.5)

    assert not isinstance(pilot.app.screen, CommentScreen)

    await asyncio.sleep(1.0)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.3)


async def delete_comment_and_verify(pilot):

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

    await asyncio.sleep(0.5)

    comments_widget = pilot.app.screen.query_one(WorkItemCommentsWidget)
    initial_count = comments_widget.displayed_count

    assert initial_count > 0, 'Should have at least one comment to delete'

    comments_scroll = pilot.app.screen.query_one(CommentsScrollView)
    comments_scroll.focus()
    await asyncio.sleep(0.2)

    await pilot.press('d')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    assert isinstance(screen, ConfirmationScreen), (
        f'Expected ConfirmationScreen, got {type(screen)}'
    )

    screen.query_one('#confirmation-button-accept', Button).press()
    await asyncio.sleep(1.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(1.0)

    assert not isinstance(pilot.app.screen, ConfirmationScreen)

    comments_widget = pilot.app.screen.query_one(WorkItemCommentsWidget)
    new_count = comments_widget.displayed_count

    assert new_count == initial_count - 1, f'Expected {initial_count - 1} comments, got {new_count}'
    assert new_count == 0, f'Expected 0 comments after deletion, got {new_count}'


class TestWorkItemComments:
    def test_comments_display(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_comments_tab_and_verify)

    def test_delete_comment_and_verify_in_list(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_comment_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=delete_comment_and_verify)

    def test_create_comment_and_verify_in_list(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_comment_creation,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=create_comment_and_verify)
