from datetime import datetime

from httpx import Response
import respx
from textual.widgets import TextArea

from gojeera.app import JiraApp
from gojeera.components.screens.comment_screen import CommentScreen
from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.work_item.work_item_comments import (
    CommentsScrollView,
    WorkItemCommentsWidget,
)
from gojeera.internal.models.jira import JiraUser
from gojeera.internal.models.work_items import WorkItemComment
from gojeera.widgets.markdown.gojeera_markdown import (
    ExtendedMarkdownParagraph,
    get_attachment_reference_filename,
)

from .test_comment_screen import with_comment_snapshot_assertion
from .test_helpers import (
    accept_confirmation,
    find_markdown_paragraph_containing_text,
    focus_work_item_tab,
    navigate_to_comments_tab,
    wait_for_screen_to_settle,
    wait_for_worker_idle,
    wait_until,
)


def _find_attachment_offset(paragraph: ExtendedMarkdownParagraph, filename: str) -> tuple[int, int]:
    return next(
        (x, y)
        for y in range(paragraph.size.height)
        for x in range(paragraph.size.width)
        if get_attachment_reference_filename(paragraph.get_style_at(x, y)) == filename
    )


def _build_rendered_comment(*, comment_id: str, body: dict, rendered_body: str) -> dict:
    return {
        'id': comment_id,
        'created': '2026-04-05T17:32:00.000+0000',
        'updated': '2026-04-05T17:32:00.000+0000',
        'author': {
            'accountId': 'user-1',
            'active': True,
            'displayName': 'Vadim Khitrin',
            'emailAddress': 'vadim@example.com',
        },
        'body': body,
        'renderedBody': rendered_body,
    }


def _adf_doc(*content: dict) -> dict:
    return {
        'type': 'doc',
        'version': 1,
        'content': list(content),
    }


def _media_file_node(file_id: str, **attrs: str) -> dict:
    return {
        'type': 'media',
        'attrs': {
            'id': file_id,
            'type': 'file',
            **attrs,
        },
    }


def _mock_rendered_comments(*comments: dict) -> None:
    respx.get(
        url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-1/comment\?.*expand=renderedBody.*'
    ).mock(return_value=Response(200, json={'comments': list(comments)}))


def _assert_rendered_comments_snapshot(
    snap_compare,
    mock_configuration,
    mock_user_info,
    rendered_comment: dict,
) -> None:
    _mock_rendered_comments(rendered_comment)

    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

    assert snap_compare(
        app,
        terminal_size=(120, 40),
        run_before=open_comments_tab_with_fetched_inline_file,
    )


def _build_rendered_comments_snapshot_test(rendered_comment: dict):
    def decorator(_):
        def test_case(
            self,
            snap_compare,
            mock_configuration,
            mock_user_info,
            mock_jira_search_with_results,
            mock_jira_api_with_search_results,
        ):
            _assert_rendered_comments_snapshot(
                snap_compare,
                mock_configuration,
                mock_user_info,
                rendered_comment,
            )

        return test_case

    return decorator


INLINE_FILE_RENDERED_COMMENT = _build_rendered_comment(
    comment_id='comment-inline-file',
    body=_adf_doc(
        {
            'type': 'paragraph',
            'content': [
                {'type': 'text', 'text': 'End result:'},
                _media_file_node(
                    'e2efe69b-4f1f-4ee0-a223-b915c960bbb5',
                    localId='b218b489a88a',
                ),
            ],
        }
    ),
    rendered_body=(
        '<p>End result: '
        '<a href="/rest/api/3/attachment/content/74914" '
        'data-media-services-id="e2efe69b-4f1f-4ee0-a223-b915c960bbb5" '
        'data-attachment-name="API Telemetry_2026-03-29-2026-04-05.pdf">'
        'API Telemetry_2026-03-29-2026-04-05.pdf'
        '</a></p>'
    ),
)


MEDIA_GROUP_RENDERED_COMMENT = _build_rendered_comment(
    comment_id='comment-media-group',
    body=_adf_doc(
        {
            'type': 'mediaGroup',
            'content': [
                _media_file_node('attachment-1', collection=''),
                _media_file_node('attachment-2', collection=''),
            ],
        }
    ),
    rendered_body=(
        '<div>'
        '<a href="/rest/api/3/attachment/content/20001" '
        'data-media-services-id="attachment-1" '
        'data-attachment-name="rollout-diagram.png">'
        'rollout-diagram.png'
        '</a>'
        '<a href="/rest/api/3/attachment/content/20002" '
        'data-media-services-id="attachment-2" '
        'data-attachment-name="field-notes.pdf">'
        'field-notes.pdf'
        '</a>'
        '</div>'
    ),
)


async def open_comments_tab_and_verify(pilot):
    await navigate_to_comments_tab(pilot, 'ENG-3')

    comments_scroll = pilot.app.screen.query_one(CommentsScrollView)
    comments_scroll.focus()
    await pilot.pause()


async def create_comment_and_verify(pilot):
    await navigate_to_comments_tab(pilot, 'ENG-3')
    comments_widget = pilot.app.screen.query_one(WorkItemCommentsWidget)
    initial_count = comments_widget.displayed_count

    await pilot.press('ctrl+n')
    await wait_until(lambda: isinstance(pilot.app.screen, CommentScreen), timeout=3.0)

    screen = pilot.app.screen
    assert isinstance(screen, CommentScreen)
    assert screen.mode == 'new'

    textarea = screen.query_one(TextArea)
    textarea.focus()
    await wait_until(lambda: textarea.has_focus, timeout=3.0)

    test_comment = 'This is a new test comment added via the UI.'
    textarea.insert(test_comment)
    await wait_until(lambda: not screen.save_button.disabled, timeout=3.0)

    assert not screen.save_button.disabled, 'Save button should be enabled'
    screen.save_button.press()

    await wait_until(lambda: not isinstance(pilot.app.screen, CommentScreen), timeout=3.0)
    await wait_for_screen_to_settle(pilot)

    assert not isinstance(pilot.app.screen, CommentScreen)
    comments_widget = pilot.app.screen.query_one(WorkItemCommentsWidget)
    await wait_until(lambda: comments_widget.displayed_count == initial_count + 1, timeout=3.0)
    await wait_for_worker_idle(pilot)


async def delete_comment_and_verify(pilot):
    await focus_work_item_tab(
        pilot,
        work_item_key='ENG-3',
        right_presses=5,
        step_delay=0.1,
        final_delay=0.5,
    )

    comments_widget = pilot.app.screen.query_one(WorkItemCommentsWidget)
    initial_count = comments_widget.displayed_count

    assert initial_count > 0, 'Should have at least one comment to delete'

    comments_scroll = pilot.app.screen.query_one(CommentsScrollView)
    comments_scroll.focus()
    await pilot.pause()

    await pilot.press('ctrl+d')
    await wait_until(lambda: isinstance(pilot.app.screen, ConfirmationScreen), timeout=3.0)
    await accept_confirmation(pilot)

    assert not isinstance(pilot.app.screen, ConfirmationScreen)

    comments_widget = pilot.app.screen.query_one(WorkItemCommentsWidget)
    await wait_until(lambda: comments_widget.displayed_count == initial_count - 1, timeout=3.0)
    new_count = comments_widget.displayed_count

    assert new_count == initial_count - 1, f'Expected {initial_count - 1} comments, got {new_count}'
    assert new_count == 0, f'Expected 0 comments after deletion, got {new_count}'


async def open_comments_tab_and_hover_attachment_tooltip(pilot):
    await focus_work_item_tab(
        pilot,
        work_item_key='ENG-1',
        right_presses=5,
        step_delay=0.1,
        final_delay=0.3,
    )

    comments_widget = pilot.app.screen.query_one(WorkItemCommentsWidget)
    comments_widget.comments = [
        WorkItemComment(
            id='comment-with-attachment',
            author=JiraUser(
                account_id='user-1',
                active=True,
                display_name='Rook Hydra',
                email='rook.hydra@acme.example.com',
            ),
            created=datetime(2026, 2, 5, 11, 23),
            updated=datetime(2026, 2, 5, 11, 23),
            body=_adf_doc(
                {
                    'type': 'paragraph',
                    'content': [{'type': 'text', 'text': 'Attached file:'}],
                },
                {
                    'type': 'mediaSingle',
                    'content': [_media_file_node('attachment-1', alt='image-20260205-112310.png')],
                },
            ),
        )
    ]
    await pilot.pause(0.5)

    attachment_paragraph = find_markdown_paragraph_containing_text(
        pilot.app.screen,
        'image-20260205-112310.png',
    )
    link_offset = _find_attachment_offset(attachment_paragraph, 'image-20260205-112310.png')
    await pilot.hover(attachment_paragraph, offset=link_offset)
    await pilot.pause(1.0)


async def open_comments_tab_with_fetched_inline_file(pilot):
    await focus_work_item_tab(
        pilot,
        work_item_key='ENG-1',
        right_presses=5,
        step_delay=0.1,
        final_delay=0.5,
    )


class TestWorkItemComments:
    @with_comment_snapshot_assertion(open_comments_tab_and_verify)
    def test_comments_display(self): ...

    def test_delete_comment(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_comment_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=delete_comment_and_verify)

    def test_create_comment(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_comment_creation,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=create_comment_and_verify)

    @with_comment_snapshot_assertion(
        open_comments_tab_and_hover_attachment_tooltip,
        configure_app=lambda app: setattr(app, '_disable_tooltips', False),
    )
    def test_attachment_tooltip_snapshot(self): ...

    @_build_rendered_comments_snapshot_test(INLINE_FILE_RENDERED_COMMENT)
    def test_fetched_comments_use_rendered_body_for_inline_file_snapshot(self): ...

    @_build_rendered_comments_snapshot_test(MEDIA_GROUP_RENDERED_COMMENT)
    def test_fetched_comments_use_rendered_body_for_media_group_snapshot(self): ...
