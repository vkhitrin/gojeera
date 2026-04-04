import asyncio

from textual.widgets import TextArea
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.work_item_comments import CommentsScrollView

from .test_helpers import load_work_item_from_search, wait_until


async def open_comments_tab(pilot):
    await load_work_item_from_search(pilot, 'ENG-3')

    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: pilot.app.screen is not None, timeout=2.0)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.1)

    for _ in range(5):
        await pilot.press('right')
        await asyncio.sleep(0.1)

    await asyncio.sleep(0.3)


async def open_add_comment_screen(pilot):
    await open_comments_tab(pilot)

    await pilot.press('ctrl+n')
    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: isinstance(pilot.app.screen, CommentScreen), timeout=2.0)

    assert isinstance(pilot.app.screen, CommentScreen)
    assert pilot.app.screen.mode == 'new'

    textarea = pilot.app.screen.query_one(TextArea)
    textarea.focus()
    await wait_until(lambda: textarea.has_focus, timeout=1.0)


async def fill_comment_and_verify_save_enabled(pilot):
    await open_add_comment_screen(pilot)

    textarea = pilot.app.screen.query_one(TextArea)
    test_comment = 'This is a test comment with some content.'
    textarea.insert(test_comment)
    await asyncio.sleep(0.3)

    save_button = pilot.app.screen.save_button
    assert not save_button.disabled


async def open_edit_comment_screen(pilot):
    await open_comments_tab(pilot)

    comments_scroll = pilot.app.screen.query_one(CommentsScrollView)
    comments_scroll.focus()
    await asyncio.sleep(0.1)

    await pilot.press('e')
    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: isinstance(pilot.app.screen, CommentScreen), timeout=2.0)

    assert isinstance(pilot.app.screen, CommentScreen)
    assert pilot.app.screen.mode == 'edit'

    textarea = pilot.app.screen.query_one(TextArea)
    textarea.focus()
    await wait_until(lambda: textarea.has_focus, timeout=1.0)


class TestCommentScreen:
    def test_add_comment_screen_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_add_comment_screen)

    def test_add_comment_screen_with_text(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=fill_comment_and_verify_save_enabled,
        )

    def test_edit_comment_screen_with_existing_text(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_edit_comment_screen)
