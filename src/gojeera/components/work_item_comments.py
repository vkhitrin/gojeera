from datetime import datetime
from typing import TYPE_CHECKING, cast
import webbrowser

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import (
    Horizontal,
    Vertical,
    VerticalGroup,
    VerticalScroll,
)
from textual.css.query import NoMatches
from textual.reactive import Reactive, reactive
from textual.widget import MountError
from textual.widgets import Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.models import Attachment, WorkItemComment
from gojeera.utils.adf_helpers import convert_adf_to_markdown
from gojeera.utils.urls import build_external_url_for_attachment, build_external_url_for_work_item
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown

if TYPE_CHECKING:
    from gojeera.app import JiraApp


def _merge_uploaded_attachments_into_widget(widget, uploaded_attachments: list[Attachment]) -> None:
    if not uploaded_attachments:
        return

    from gojeera.components.work_item_attachments import WorkItemAttachmentsWidget

    attachments_widget = widget.screen.query_one(WorkItemAttachmentsWidget)
    current_attachments = attachments_widget.attachments or []
    attachments_widget.attachments = current_attachments + uploaded_attachments


def _apply_comment_result_to_collection(
    current_comments: list[WorkItemComment] | None,
    comment: WorkItemComment,
    mode: str,
) -> list[WorkItemComment]:
    existing_comments = current_comments or []
    if mode == 'edit':
        return [comment if item.id == comment.id else item for item in existing_comments]
    return [comment, *existing_comments]


def _apply_comment_body_override(
    comment: WorkItemComment, comment_body_markdown: str | None
) -> WorkItemComment:
    if not comment_body_markdown:
        return comment
    return WorkItemComment(
        id=comment.id,
        author=comment.author,
        created=comment.created,
        updated=comment.updated,
        update_author=comment.update_author,
        body=comment_body_markdown,
        rendered_body=None,
    )


def _build_media_attachment_details(
    attachments: list[Attachment] | None,
) -> dict[str, tuple[str, str | None]]:
    details: dict[str, tuple[str, str | None]] = {}
    for attachment in attachments or []:
        if not attachment.id or not attachment.filename:
            continue
        resolved = (
            attachment.filename,
            build_external_url_for_attachment(attachment.id, attachment.filename),
        )
        details[attachment.id] = resolved
        details[attachment.filename] = resolved
    return details


class CommentContainer(Vertical, can_focus=False):
    """A container representing a single comment."""

    DEFAULT_CSS = """
    CommentContainer {
        height: auto;
        padding: 0 1;
        margin: 0;
        background: transparent;
        color: $foreground;
        opacity: 0.5;
    }
    
    CommentContainer.-selected {
        background: transparent;
        color: $foreground;
        opacity: 1.0;
    }

    CommentContainer > Vertical {
        height: auto;
        padding: 0;
        margin: 0;
        background: transparent;
    }
    """

    def __init__(self, *args, **kwargs):
        self._work_item_key: str | None = kwargs.pop('work_item_key', None)
        self._comment_id: str | None = kwargs.pop('comment_id', None)
        self._comment_body: str = kwargs.pop('comment_body', '')
        self._comment_author_id: str | None = kwargs.pop('comment_author_id', None)
        super().__init__(*args, **kwargs)

    async def on_click(self, event) -> None:
        event.stop()

        parent = self.parent
        if isinstance(parent, CommentsScrollView):
            containers = parent.comment_containers
            for i, container in enumerate(containers):
                if container._comment_id == self._comment_id:
                    parent._selected_index = i
                    parent._update_selection()
                    break

    async def action_delete_comment(self) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821
        current_user_id = application.user_info.account_id if application.user_info else None

        if not self._work_item_key:
            return

        if not current_user_id:
            self.notify(
                'Unable to determine current user',
                severity='error',
                title=self._work_item_key,
            )
            return

        if not (self._comment_author_id and current_user_id == self._comment_author_id):
            self.notify(
                'You can only delete your own comments',
                severity='warning',
                title=self._work_item_key,
            )
            return

        await self.app.push_screen(
            ConfirmationScreen('Are you sure you want to delete the comment?'),
            callback=self.handle_delete_choice,
        )

    async def action_edit_comment(self) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821
        current_user_id = application.user_info.account_id if application.user_info else None

        if not self._work_item_key:
            return

        if not current_user_id:
            self.notify(
                'Unable to determine current user',
                severity='error',
                title=self._work_item_key,
            )
            return

        if not (self._comment_author_id and current_user_id == self._comment_author_id):
            self.notify(
                'You can only edit your own comments', severity='warning', title=self._work_item_key
            )
            return

        if self._comment_id:
            await self.app.push_screen(
                CommentScreen(
                    mode='edit',
                    work_item_key=self._work_item_key,
                    comment_id=self._comment_id,
                    initial_text=self._comment_body,
                ),
                callback=self.handle_edit_result,
            )
        else:
            self.notify(
                'Comment information not available', severity='warning', title=self._work_item_key
            )

    def action_open_comment_in_browser(self) -> None:
        if not self._work_item_key:
            return

        if self._comment_id:
            url = build_external_url_for_work_item(
                self._work_item_key,
                cast('JiraApp', self.app),  # noqa: F821
                focused_comment_id=self._comment_id,
            )
            if url:
                webbrowser.open_new_tab(url)
                self.notify('Opening comment in browser', title=self._work_item_key)
            else:
                self.notify(
                    'Unable to build comment URL', severity='warning', title=self._work_item_key
                )
        else:
            self.notify(
                'Comment information not available', severity='warning', title=self._work_item_key
            )

    def handle_edit_result(self, result: dict[str, object] | str | None) -> None:
        if not isinstance(result, dict):
            return

        comment = result.get('comment')
        comment_body_markdown = result.get('comment_body_markdown')
        uploaded_attachments = cast(list[Attachment], result.get('uploaded_attachments') or [])
        if not isinstance(comment, WorkItemComment):
            return
        if comment_body_markdown is not None and not isinstance(comment_body_markdown, str):
            comment_body_markdown = str(comment_body_markdown)
        comment = _apply_comment_body_override(comment, comment_body_markdown)

        _merge_uploaded_attachments_into_widget(self, uploaded_attachments)
        if uploaded_attachments and self._work_item_key:
            self.notify(
                f'Uploaded {len(uploaded_attachments)} clipboard attachment(s)',
                title=self._work_item_key,
            )
        self.notify('Comment updated successfully', title=self._work_item_key or '')

        current = self.parent
        while current is not None:
            if isinstance(current, WorkItemCommentsWidget):
                current.comments = _apply_comment_result_to_collection(
                    current.comments,
                    comment,
                    'edit',
                )
                break
            current = current.parent

    def handle_delete_choice(self, result: bool | None) -> None:
        if result:
            if self._work_item_key and self._comment_id:
                self.run_worker(self.delete_comment(self._work_item_key, self._comment_id))

    def _update_comments_after_delete(self) -> None:
        current = self.parent
        while current is not None:
            if isinstance(current, WorkItemCommentsWidget):
                if current.comments:
                    updated_comments: list[WorkItemComment] = []
                    for comment in current.comments:
                        if comment.id == self._comment_id:
                            continue
                        updated_comments.append(comment)
                    current.comments = updated_comments
                break
            current = current.parent

    async def delete_comment(self, work_item_key: str, comment_id: str) -> None:
        """Delete a comment associated with the work item.

        Args:
            work_item_key: the key of the work item whose comment we want to remove.
            comment_id: the ID of the comment we want to remove.

        Returns:
            `None`
        """
        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.delete_comment(
            work_item_key, comment_id
        )
        if not response.success:
            self.notify(
                f'Failed to delete the comment: {response.error}',
                severity='error',
                title=work_item_key,
            )
        else:
            self.notify('Comment deleted successfully', title=work_item_key)
            self._update_comments_after_delete()


class CommentsScrollView(VerticalScroll):
    """Custom VerticalScroll with vim-style navigation."""

    DEFAULT_CSS = """
    CommentsScrollView {
        height: 1fr;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding(
            'ctrl+n',
            'new_comment',
            'New comment',
            tooltip='Add a comment to the loaded work item',
            priority=True,
        ),
        Binding('j', 'cursor_down', 'Next comment', show=False),
        Binding('k', 'cursor_up', 'Previous comment', show=False),
        Binding('down', 'cursor_down', 'Next comment', show=False),
        Binding('up', 'cursor_up', 'Previous comment', show=False),
        Binding(
            'ctrl+o',
            'open_comment_in_browser',
            'Open in browser',
        ),
        Binding('ctrl+e', 'edit_comment', 'Edit comment'),
        Binding('ctrl+d', 'delete_comment', 'Delete comment'),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected_index: int = 0

    def _get_comments_widget(self) -> 'WorkItemCommentsWidget | None':
        current = self.parent
        while current is not None:
            if isinstance(current, WorkItemCommentsWidget):
                return current
            current = current.parent
        return None

    @property
    def comment_containers(self) -> list[CommentContainer]:
        return list(self.query(CommentContainer))

    @property
    def selected_comment(self) -> CommentContainer | None:
        containers = self.comment_containers
        if containers and 0 <= self._selected_index < len(containers):
            return containers[self._selected_index]
        return None

    def _update_selection(self) -> None:
        containers = self.comment_containers
        for i, container in enumerate(containers):
            if i == self._selected_index:
                container.add_class('-selected')
            else:
                container.remove_class('-selected')

    def action_cursor_down(self) -> None:
        containers = self.comment_containers
        if containers:
            self._selected_index = min(self._selected_index + 1, len(containers) - 1)
            self._update_selection()

            if selected := self.selected_comment:
                self.scroll_to_widget(selected, animate=False)

    def action_cursor_up(self) -> None:
        containers = self.comment_containers
        if containers:
            self._selected_index = max(self._selected_index - 1, 0)
            self._update_selection()

            if selected := self.selected_comment:
                self.scroll_to_widget(selected, animate=False)

    def action_open_comment_in_browser(self) -> None:
        if selected := self.selected_comment:
            selected.action_open_comment_in_browser()

    async def action_edit_comment(self) -> None:
        if selected := self.selected_comment:
            await selected.action_edit_comment()

    async def action_delete_comment(self) -> None:
        if selected := self.selected_comment:
            await selected.action_delete_comment()

    def action_new_comment(self) -> None:
        widget = self._get_comments_widget()
        if widget is not None:
            widget.action_add_comment()

    def reset_selection(self) -> None:
        self._selected_index = 0
        self._update_selection()


class WorkItemCommentsWidget(Vertical, can_focus=False):
    """A container for displaying the comments of a work item using VerticalScroll."""

    DEFAULT_CSS = """
    WorkItemCommentsWidget {
        width: 100%;
        height: 1fr;
    }

    WorkItemCommentsWidget > .tab-content-container {
        width: 100%;
        height: 1fr;
    }
    """

    comments: Reactive[list[WorkItemComment] | None] = reactive(None)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(id='work_item_comments')
        self._work_item_key = None
        self._last_comment_ids: set[tuple[str, datetime | None]] | None = None

    @property
    def help_anchor(self) -> str:
        return '#comments'

    @property
    def work_item_key(self):
        return self._work_item_key

    @work_item_key.setter
    def work_item_key(self, value: str | None):
        self._work_item_key = value

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one(
            '.tab-content-container',
            expect_type=VerticalGroup,
        )

    @property
    def comments_scroll_view(self) -> CommentsScrollView:
        return self.query_one(CommentsScrollView)

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True

            yield CommentsScrollView(id='comments-scroll-view')

    def on_mount(self) -> None:
        self.content_container.can_focus = False

    def show_loading(self) -> None:
        self.is_loading = True

    def hide_loading(self) -> None:
        self.is_loading = False

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading

    def save_comment(self, result: dict[str, object] | str | None) -> None:
        if not isinstance(result, dict):
            return

        comment = result.get('comment')
        comment_body_markdown = result.get('comment_body_markdown')
        uploaded_attachments = cast(list[Attachment], result.get('uploaded_attachments') or [])
        if not isinstance(comment, WorkItemComment):
            return
        if comment_body_markdown is not None and not isinstance(comment_body_markdown, str):
            comment_body_markdown = str(comment_body_markdown)
        comment = _apply_comment_body_override(comment, comment_body_markdown)

        _merge_uploaded_attachments_into_widget(self, uploaded_attachments)
        if uploaded_attachments and self.work_item_key:
            self.notify(
                f'Uploaded {len(uploaded_attachments)} clipboard attachment(s)',
                title=self.work_item_key,
            )
        if self.work_item_key:
            self.notify('Comment added successfully', title=self.work_item_key)
        self.comments = _apply_comment_result_to_collection(self.comments, comment, 'new')

    def action_add_comment(self) -> None:
        if self.work_item_key:
            self.app.push_screen(
                CommentScreen(mode='new', work_item_key=self.work_item_key), self.save_comment
            )

    async def watch_comments(self, items: list[WorkItemComment] | None) -> None:
        """Watch for changes to comments."""

        if not self.is_attached:
            return

        try:
            scroll_view = self.comments_scroll_view
        except NoMatches:
            return

        if not scroll_view.is_attached:
            return

        if not items:
            with self.app.batch_update():
                for container in scroll_view.query(CommentContainer):
                    await container.remove()
                self.is_loading = False
                self.displayed_count = 0
                self._last_comment_ids = None
            return

        current_comment_fingerprint = {
            (comment.id, comment.updated or comment.created) for comment in items
        }

        if (
            self._last_comment_ids is not None
            and self._last_comment_ids == current_comment_fingerprint
        ):
            return

        self._last_comment_ids = current_comment_fingerprint

        attachments_widget = getattr(self.screen, 'work_item_attachments_widget', None)
        media_attachment_details = _build_media_attachment_details(
            getattr(attachments_widget, 'attachments', None)
        )

        with self.app.batch_update():
            for container in scroll_view.query(CommentContainer):
                await container.remove()

            items.sort(key=lambda x: x.updated or 0, reverse=True)

            for comment in items:
                if not self.is_attached or not scroll_view.is_attached:
                    return

                base_url = getattr(getattr(self.app, 'server_info', None), 'base_url', None)

                inner_container = Vertical(classes='comment-item-inner')

                header_row = Horizontal(classes='comment-header-row')

                author_name = comment.author.display_name if comment.author else 'Unknown'
                title_text = Text(author_name, style='bold')
                header_row.compose_add_child(Static(title_text, classes='comment-author'))

                inner_container.compose_add_child(header_row)

                posted_date = comment.created_on() if comment.created else 'Unknown date'
                subtitle_parts = [posted_date]

                if comment.updated and comment.created and comment.updated != comment.created:
                    edited_text = f'(edited {comment.updated_on()})'
                    subtitle_parts.append(edited_text)

                subtitle = ' '.join(subtitle_parts)
                subtitle_text = Text(subtitle, style='dim')
                inner_container.compose_add_child(Static(subtitle_text, classes='comment-metadata'))

                if isinstance(comment.body, str):
                    content = comment.body
                elif comment.body is not None:
                    content = convert_adf_to_markdown(
                        comment.body,
                        base_url,
                        rendered_body=comment.rendered_body,
                        media_attachment_details=media_attachment_details,
                    )
                else:
                    content = ''

                if content:
                    markdown_widget = GojeeraMarkdown(
                        content,
                        classes='comment-body',
                        jira_base_url=base_url,
                    )
                    markdown_widget.can_focus = False
                    inner_container.compose_add_child(markdown_widget)
                else:
                    inner_container.compose_add_child(
                        Static(
                            Text(
                                'Unable to display the comment. Open the link above to view it.',
                                style='bold orange',
                            ),
                            classes='comment-error',
                        )
                    )

                comment_container = CommentContainer(
                    work_item_key=self.work_item_key,
                    comment_id=comment.id,
                    comment_body=content,
                    comment_author_id=comment.author.account_id if comment.author else None,
                    id=f'comment-{comment.id}',
                )

                comment_container.compose_add_child(inner_container)

                try:
                    await scroll_view.mount(comment_container)
                except MountError:
                    return

            self.hide_loading()

        if not self.is_attached or not scroll_view.is_attached:
            return

        scroll_view.reset_selection()

        self.displayed_count = len(items)
