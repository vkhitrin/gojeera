import logging
from typing import TYPE_CHECKING

from textual import on
from textual.binding import Binding
from textual.containers import Center, Container, VerticalGroup, VerticalScroll
from textual.widgets import TabbedContent
from textual.widgets._tabbed_content import ContentTab, ContentTabs

if TYPE_CHECKING:
    from gojeera.app import MainScreen


logger = logging.getLogger('gojeera')


class ExtendedTabbedContent(TabbedContent):
    """Custom TabbedContent that handles Tab navigation in a custom manner."""

    BINDINGS = [
        Binding(
            key='ctrl+e',
            action='edit_work_item_info',
            description='Edit Info',
            tooltip='Edit summary and description',
            show=True,
        ),
        Binding(
            key='ctrl+l',
            action='view_worklog',
            description='Worklog',
            tooltip='View work logs',
            show=True,
        ),
        Binding(
            key='ctrl+t',
            action='log_work',
            description='Log Work',
            tooltip='Log work time',
            show=True,
        ),
        Binding(
            key='ctrl+n',
            action='add_attachment',
            description='New Attachment',
            tooltip='Attach file to work item',
            show=True,
        ),
        Binding(
            key='ctrl+n',
            action='new_work_item_subtask',
            description='New Subtask',
            tooltip='Create a new subtask',
            show=True,
        ),
        Binding(
            key='ctrl+n',
            action='link_work_item',
            description='Link Work Item',
            tooltip='Link to another work item',
            show=True,
        ),
        Binding(
            key='ctrl+n',
            action='add_remote_link',
            description='New Web Link',
            tooltip='Add a new remote link',
            show=True,
        ),
        Binding(
            key='ctrl+n',
            action='add_comment',
            description='New Comment',
            tooltip='Add a new comment',
            show=True,
        ),
    ]

    @on(TabbedContent.TabActivated)
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self.screen.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'edit_work_item_info':
            return self.active == 'tab-summary'
        if action == 'add_attachment':
            return self.active == 'tab-attachments'
        if action == 'new_work_item_subtask':
            return self.active == 'tab-subtasks'
        if action == 'link_work_item':
            return self.active == 'tab-related'
        if action == 'add_remote_link':
            return self.active == 'tab-links'
        if action == 'add_comment':
            return self.active == 'tab-comments'
        return True

    async def action_edit_work_item_info(self) -> None:
        if self.active == 'tab-summary':
            from gojeera.components.work_item_summary import WorkItemInfoContainer

            info_container = self.query_one(WorkItemInfoContainer)
            await info_container.action_edit_work_item_info()

    async def action_add_attachment(self) -> None:
        if self.active == 'tab-attachments':
            from gojeera.components.work_item_attachments import WorkItemAttachmentsWidget

            attachments_widget = self.query_one(WorkItemAttachmentsWidget)
            await attachments_widget.action_add_attachment()

    async def action_new_work_item_subtask(self) -> None:
        if self.active == 'tab-subtasks':
            from typing import cast

            from gojeera.components.new_work_item_screen import AddWorkItemScreen
            from gojeera.components.work_item_subtasks import WorkItemChildWorkItemsWidget

            screen = cast('MainScreen', self.screen)  # noqa: F821
            subtasks_widget = self.query_one(WorkItemChildWorkItemsWidget)

            project_key = None
            if (
                screen.work_item_info_container.work_item
                and screen.work_item_info_container.work_item.project
            ):
                project_key = screen.work_item_info_container.work_item.project.key

            from gojeera.app import JiraApp

            app = cast(JiraApp, self.app)
            reporter_account_id = app.user_info.account_id if app.user_info else None

            await self.app.push_screen(
                AddWorkItemScreen(
                    project_key=project_key,
                    reporter_account_id=reporter_account_id,
                    parent_work_item_key=subtasks_widget.work_item_key,
                ),
                callback=screen.new_work_item,
            )

    async def action_link_work_item(self) -> None:
        if self.active == 'tab-related':
            from gojeera.components.work_item_related_work_items import RelatedWorkItemsWidget

            links_widget = self.query_one(RelatedWorkItemsWidget)
            await links_widget.action_link_work_item()

    async def action_add_remote_link(self) -> None:
        if self.active == 'tab-links':
            from gojeera.components.work_item_web_links import WorkItemRemoteLinksWidget

            remote_links_widget = self.query_one(WorkItemRemoteLinksWidget)
            await remote_links_widget.action_add_remote_link()

    def action_add_comment(self) -> None:
        if self.active == 'tab-comments':
            from gojeera.components.work_item_comments import WorkItemCommentsWidget

            comments_widget = self.query_one(WorkItemCommentsWidget)
            comments_widget.action_add_comment()

    def action_view_worklog(self) -> None:
        from gojeera.components.work_item_fields import WorkItemFields

        try:
            work_item_fields_widget = self.screen.query_one(WorkItemFields)
            work_item_fields_widget.action_view_worklog()
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def action_log_work(self) -> None:
        from gojeera.components.work_item_fields import WorkItemFields

        try:
            work_item_fields_widget = self.screen.query_one(WorkItemFields)
            work_item_fields_widget.action_log_work()
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def action_focus_content(self) -> None:
        focused = self.screen.focused

        if focused and isinstance(focused, (ContentTab, ContentTabs)):
            active_pane = self.get_pane(self.active)
            if active_pane:
                for child in active_pane.walk_children():
                    if isinstance(child, (Container, VerticalScroll, VerticalGroup, Center)):
                        continue

                    can_focus = getattr(child, 'can_focus', False)
                    focusable = getattr(child, 'focusable', False)

                    if can_focus and focusable:
                        if hasattr(child, 'focus') and callable(getattr(child, 'focus', None)):
                            child.focus()  # type: ignore[call-non-callable]

                        if hasattr(child, 'scroll_visible') and callable(
                            getattr(child, 'scroll_visible', None)
                        ):
                            child.scroll_visible()  # type: ignore[call-non-callable]
                        return

        self.screen.focus_next()

    def action_focus_previous_or_tabs(self) -> None:
        focused = self.screen.focused

        if focused:
            active_pane = self.get_pane(self.active)
            if active_pane and focused in active_pane.walk_children():
                first_focusable = None
                for child in active_pane.walk_children():
                    can_focus = getattr(child, 'can_focus', False)
                    focusable = getattr(child, 'focusable', False)

                    if can_focus and focusable:
                        first_focusable = child
                        break

                if focused == first_focusable:
                    content_tabs = self.query_one(ContentTabs)
                    content_tabs.focus()
                    return

        self.screen.focus_previous()
