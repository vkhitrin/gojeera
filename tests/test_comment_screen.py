import asyncio

from textual.widgets import TextArea

from gojeera.app import JiraApp
from gojeera.components.screens.comment_screen import CommentScreen
from gojeera.components.work_item.work_item_comments import CommentsScrollView
from gojeera.utils.system import clipboard_attachments as clipboard_attachments_module
from gojeera.widgets.selection.vim_select import VimSelect

from .test_helpers import (
    navigate_to_comments_tab,
    stage_clipboard_upload,
    wait_until,
    with_snapshot_assertion,
)


async def open_comments_tab(pilot):
    await navigate_to_comments_tab(pilot, 'ENG-3')


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

    await pilot.press('ctrl+e')
    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: isinstance(pilot.app.screen, CommentScreen), timeout=2.0)

    assert isinstance(pilot.app.screen, CommentScreen)
    assert pilot.app.screen.mode == 'edit'

    textarea = pilot.app.screen.query_one(TextArea)
    textarea.focus()
    await wait_until(lambda: textarea.has_focus, timeout=1.0)


async def paste_clipboard_attachment_and_verify(pilot):
    await open_add_comment_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, CommentScreen)

    await screen.action_paste_clipboard_attachment()
    await asyncio.sleep(0.3)

    assert '<!-- gojeera:staged-clipboard-attachment -->' in screen.comment_field.text
    assert not screen.save_button.disabled


async def create_comment_with_clipboard_attachment_and_verify(pilot):
    await open_add_comment_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, CommentScreen)

    await screen.action_paste_clipboard_attachment()
    await asyncio.sleep(0.3)

    screen.save_button.press()
    await asyncio.sleep(1.5)

    assert not isinstance(pilot.app.screen, CommentScreen)


def with_comment_snapshot_assertion(run_before, *, configure_app=None):
    return with_snapshot_assertion(run_before, configure_app=configure_app)


class TestCommentScreen:
    @with_comment_snapshot_assertion(open_add_comment_screen)
    def test_add_comment_screen_initial_state(self): ...

    @with_comment_snapshot_assertion(fill_comment_and_verify_save_enabled)
    def test_add_comment_screen_with_text(self): ...

    @with_comment_snapshot_assertion(open_edit_comment_screen)
    def test_edit_comment_screen_with_existing_text(self): ...

    def test_add_comment_screen_with_clipboard_attachment(
        self,
        snap_compare,
        monkeypatch,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
        staged_upload_file,
    ):
        stage_clipboard_upload(monkeypatch, clipboard_attachments_module, staged_upload_file)

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=paste_clipboard_attachment_and_verify,
        )

    def test_create_comment_uploads_clipboard_attachment(
        self,
        snap_compare,
        monkeypatch,
        mock_configuration,
        mock_user_info,
        mock_jira_api_with_comment_creation,
        staged_upload_file,
        mock_attachment_upload,
    ):
        stage_clipboard_upload(monkeypatch, clipboard_attachments_module, staged_upload_file)

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        upload_route = mock_attachment_upload('ENG-3')

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=create_comment_with_clipboard_attachment_and_verify,
        )
        assert upload_route.called
        assert upload_route.call_count == 1
        assert b'filename="clipboard-upload.png"' in upload_route.calls[0].request.content
        comment_create_route = mock_jira_api_with_comment_creation['comment_create_route']
        assert comment_create_route.called
        assert (
            b'https://example.atlassian.acme.net/secure/attachment/66812/clipboard-upload.png'
            in comment_create_route.calls[-1].request.content
        )

    def test_service_desk_comment_visibility_internal_state(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async def open_internal_service_desk_comment(pilot):
            await pilot.app.push_screen(
                CommentScreen(
                    mode='new',
                    work_item_key='SUP-1',
                    work_item_is_service_desk=True,
                ),
            )
            screen = pilot.app.screen
            assert isinstance(screen, CommentScreen)
            assert screen.show_service_desk_visibility_toggle
            assert screen.query_one('#comment-visibility-select', VimSelect).value == 'public'

            screen.query_one('#comment-visibility-select', VimSelect).value = 'internal'
            await pilot.pause()
            assert screen.jsd_public is False

            textarea = screen.query_one(TextArea)
            textarea.insert('Internal service desk note')
            await wait_until(lambda: not screen.save_button.disabled, timeout=3.0)
            assert not screen.save_button.disabled

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_internal_service_desk_comment,
        )
