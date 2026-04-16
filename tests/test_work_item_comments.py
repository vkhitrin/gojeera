import asyncio
from datetime import datetime

from httpx import Response
import respx
from textual.widgets import Button, TextArea
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.work_item_comments import CommentsScrollView, WorkItemCommentsWidget
from gojeera.models import JiraUser, WorkItemComment
from gojeera.widgets.gojeera_markdown import (
    ExtendedMarkdownParagraph,
    get_attachment_reference_filename,
    get_markdown_link_href,
)

from .test_helpers import load_work_item_from_search


def _find_link_offset(paragraph: ExtendedMarkdownParagraph, href_substring: str) -> tuple[int, int]:
    return next(
        (x, y)
        for y in range(paragraph.size.height)
        for x in range(paragraph.size.width)
        if (
            (href := get_markdown_link_href(paragraph.get_style_at(x, y))) is not None
            and href_substring in href
        )
    )


def _find_attachment_offset(paragraph: ExtendedMarkdownParagraph, filename: str) -> tuple[int, int]:
    return next(
        (x, y)
        for y in range(paragraph.size.height)
        for x in range(paragraph.size.width)
        if get_attachment_reference_filename(paragraph.get_style_at(x, y)) == filename
    )


async def open_comments_tab_and_verify(pilot):
    await load_work_item_from_search(pilot, 'ENG-3')

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
    await load_work_item_from_search(pilot, 'ENG-3')

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
    await load_work_item_from_search(pilot, 'ENG-3')

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

    await pilot.press('ctrl+d')
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


async def open_comments_tab_and_hover_attachment_tooltip(pilot):
    await load_work_item_from_search(pilot, 'ENG-1')

    await pilot.app.workers.wait_for_complete()

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.1)

    for _ in range(5):
        await pilot.press('right')
        await asyncio.sleep(0.1)

    await asyncio.sleep(0.3)

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
            body={
                'type': 'doc',
                'version': 1,
                'content': [
                    {
                        'type': 'paragraph',
                        'content': [{'type': 'text', 'text': 'Attached file:'}],
                    },
                    {
                        'type': 'mediaSingle',
                        'content': [
                            {
                                'type': 'media',
                                'attrs': {
                                    'type': 'file',
                                    'id': 'attachment-1',
                                    'alt': 'image-20260205-112310.png',
                                },
                            }
                        ],
                    },
                ],
            },
        )
    ]
    await pilot.pause(0.5)

    paragraphs = list(pilot.app.screen.query(ExtendedMarkdownParagraph))
    attachment_paragraph = next(
        paragraph
        for paragraph in paragraphs
        if 'image-20260205-112310.png' in paragraph.content.plain
    )
    link_offset = _find_attachment_offset(attachment_paragraph, 'image-20260205-112310.png')
    await pilot.hover(attachment_paragraph, offset=link_offset)
    await pilot.pause(1.0)


async def open_comments_tab_with_fetched_inline_file(pilot):
    await load_work_item_from_search(pilot, 'ENG-1')

    await pilot.app.workers.wait_for_complete()

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.1)

    for _ in range(5):
        await pilot.press('right')
        await asyncio.sleep(0.1)

    await asyncio.sleep(0.5)


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

    def test_attachment_tooltip_snapshot(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app._disable_tooltips = False

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_comments_tab_and_hover_attachment_tooltip,
        )

    def test_fetched_comments_use_rendered_body_for_inline_file_snapshot(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-1/comment\?.*expand=renderedBody.*'
        ).mock(
            return_value=Response(
                200,
                json={
                    'comments': [
                        {
                            'id': 'comment-inline-file',
                            'created': '2026-04-05T17:32:00.000+0000',
                            'updated': '2026-04-05T17:32:00.000+0000',
                            'author': {
                                'accountId': 'user-1',
                                'active': True,
                                'displayName': 'Vadim Khitrin',
                                'emailAddress': 'vadim@example.com',
                            },
                            'body': {
                                'type': 'doc',
                                'version': 1,
                                'content': [
                                    {
                                        'type': 'paragraph',
                                        'content': [
                                            {'type': 'text', 'text': 'End result:'},
                                            {
                                                'type': 'mediaInline',
                                                'attrs': {
                                                    'id': 'e2efe69b-4f1f-4ee0-a223-b915c960bbb5',
                                                    'type': 'file',
                                                    'localId': 'b218b489a88a',
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                            'renderedBody': (
                                '<p>End result: '
                                '<a href="/rest/api/3/attachment/content/74914" '
                                'data-media-services-id="e2efe69b-4f1f-4ee0-a223-b915c960bbb5" '
                                'data-attachment-name="API Telemetry_2026-03-29-2026-04-05.pdf">'
                                'API Telemetry_2026-03-29-2026-04-05.pdf'
                                '</a></p>'
                            ),
                        }
                    ]
                },
            )
        )

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_comments_tab_with_fetched_inline_file,
        )

    def test_fetched_comments_use_rendered_body_for_media_group_snapshot(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-1/comment\?.*expand=renderedBody.*'
        ).mock(
            return_value=Response(
                200,
                json={
                    'comments': [
                        {
                            'id': 'comment-media-group',
                            'created': '2026-04-05T17:32:00.000+0000',
                            'updated': '2026-04-05T17:32:00.000+0000',
                            'author': {
                                'accountId': 'user-1',
                                'active': True,
                                'displayName': 'Vadim Khitrin',
                                'emailAddress': 'vadim@example.com',
                            },
                            'body': {
                                'type': 'doc',
                                'version': 1,
                                'content': [
                                    {
                                        'type': 'mediaGroup',
                                        'content': [
                                            {
                                                'type': 'media',
                                                'attrs': {
                                                    'id': 'attachment-1',
                                                    'type': 'file',
                                                    'collection': '',
                                                },
                                            },
                                            {
                                                'type': 'media',
                                                'attrs': {
                                                    'id': 'attachment-2',
                                                    'type': 'file',
                                                    'collection': '',
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                            'renderedBody': (
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
                        }
                    ]
                },
            )
        )

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_comments_tab_with_fetched_inline_file,
        )
