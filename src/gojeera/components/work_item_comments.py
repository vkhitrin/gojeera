from datetime import datetime
from typing import TYPE_CHECKING, cast
import webbrowser

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import (
    Center,
    Horizontal,
    Vertical,
    VerticalGroup,
    VerticalScroll,
)
from textual.reactive import Reactive, reactive
from textual.widgets import LoadingIndicator, Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.comment_screen import CommentScreen
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.config import CONFIGURATION
from gojeera.models import WorkItemComment
from gojeera.utils.urls import build_external_url_for_comment
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown

if TYPE_CHECKING:
    from gojeera.app import JiraApp


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
            url = build_external_url_for_comment(
                self._work_item_key,
                self._comment_id,
                cast('JiraApp', self.app),  # noqa: F821
            )
            if url:
                webbrowser.open(url)
                self.notify('Opening comment in browser', title=self._work_item_key)
            else:
                self.notify(
                    'Unable to build comment URL', severity='warning', title=self._work_item_key
                )
        else:
            self.notify(
                'Comment information not available', severity='warning', title=self._work_item_key
            )

    def handle_edit_result(self, result: str | None) -> None:
        if result and result.strip():
            if self._work_item_key and self._comment_id:
                self.run_worker(self.update_comment(self._work_item_key, self._comment_id, result))

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
            if CONFIGURATION.get().fetch_comments_on_delete:
                response = await application.api.get_comments(work_item_key)
                if not response.success or not (result := response.result):
                    self._update_comments_after_delete()
                else:
                    current = self.parent
                    while current is not None:
                        if isinstance(current, WorkItemCommentsWidget):
                            current.comments = result
                            break
                        current = current.parent
            else:
                self._update_comments_after_delete()

    async def update_comment(self, work_item_key: str, comment_id: str, message: str) -> None:
        """Update a comment associated with the work item.

        Args:
            work_item_key: the key of the work item whose comment we want to update.
            comment_id: the ID of the comment we want to update.
            message: the new message content in markdown format.

        Returns:
            `None`
        """
        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.update_comment(
            work_item_key, comment_id, message
        )
        if not response.success:
            self.notify(
                f'Failed to update the comment: {response.error}',
                severity='error',
                title=work_item_key,
            )
        else:
            self.notify('Comment updated successfully', title=work_item_key)

            response = await application.api.get_comments(work_item_key)
            if response.success and (result := response.result):
                current = self.parent
                while current is not None:
                    if isinstance(current, WorkItemCommentsWidget):
                        current.comments = result
                        break
                    current = current.parent


class CommentsScrollView(VerticalScroll):
    """Custom VerticalScroll with vim-style navigation."""

    DEFAULT_CSS = """
    CommentsScrollView {
        height: 1fr;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding('j', 'cursor_down', 'Next comment', show=False),
        Binding('k', 'cursor_up', 'Previous comment', show=False),
        Binding('down', 'cursor_down', 'Next comment', show=False),
        Binding('up', 'cursor_up', 'Previous comment', show=False),
        Binding(
            'ctrl+o',
            'open_comment_in_browser',
            'Open in browser',
        ),
        Binding('e', 'edit_comment', 'Edit comment'),
        Binding('d', 'delete_comment', 'Delete comment'),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected_index: int = 0

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

    def reset_selection(self) -> None:
        self._selected_index = 0
        self._update_selection()


class WorkItemCommentsWidget(Vertical, can_focus=False):
    """A container for displaying the comments of a work item using VerticalScroll."""

    comments: Reactive[list[WorkItemComment] | None] = reactive(None)
    displayed_count: Reactive[int] = reactive(0)

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
    def loading_container(self) -> Center:
        return self.query_one(
            '.tab-loading-container',
            expect_type=Center,
        )

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
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True

            yield CommentsScrollView(id='comments-scroll-view')

    def on_mount(self) -> None:
        self.loading_container.can_focus = False
        self.content_container.can_focus = False

    def show_loading(self) -> None:
        with self.app.batch_update():
            self.loading_container.display = True
            self.content_container.display = False

    def hide_loading(self) -> None:
        with self.app.batch_update():
            self.loading_container.display = False
            self.content_container.display = True

    def save_comment(self, content: str | None) -> None:
        if content and content.strip():
            self.run_worker(self.add_comment_to_work_item(content))

    def action_add_comment(self) -> None:
        if self.work_item_key:
            self.app.push_screen(
                CommentScreen(mode='new', work_item_key=self.work_item_key), self.save_comment
            )

    async def add_comment_to_work_item(self, content: str) -> None:
        """Adds a comment to the work item and retrieves the list comments if the comment was added successfully.

        Args:
            content: the message of the comment.

        Return:
            `None`
        """
        if not self.work_item_key:
            return

        if message := content.strip():
            application = cast('JiraApp', self.app)  # noqa: F821
            response: APIControllerResponse = await application.api.add_comment(
                self.work_item_key, message
            )
            if not response.success:
                self.notify(
                    f'Failed to add the comment: {response.error}',
                    severity='error',
                    title=self.work_item_key,
                )
            else:
                self.notify('Comment added successfully', title=self.work_item_key)
                response = await application.api.get_comments(self.work_item_key)
                if response.success:
                    self.comments = response.result or []

    async def watch_comments(self, items: list[WorkItemComment] | None) -> None:
        """Watch for changes to comments."""

        scroll_view = self.comments_scroll_view

        if not items:
            with self.app.batch_update():
                for container in scroll_view.query(CommentContainer):
                    await container.remove()
                self.loading_container.display = False
                self.content_container.display = True
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

        with self.app.batch_update():
            for container in scroll_view.query(CommentContainer):
                await container.remove()

            items.sort(key=lambda x: x.updated or 0, reverse=True)

            for comment in items:
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

                if content := comment.get_body(base_url=base_url):
                    markdown_widget = GojeeraMarkdown(content, classes='comment-body')
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
                    comment_body=comment.get_body(base_url=base_url) or '',
                    comment_author_id=comment.author.account_id if comment.author else None,
                    id=f'comment-{comment.id}',
                )

                comment_container.compose_add_child(inner_container)

                await scroll_view.mount(comment_container)

            self.hide_loading()

        scroll_view.reset_selection()

        self.displayed_count = len(items)
