from itertools import zip_longest
import logging
from types import MethodType
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, VerticalGroup, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import ContentSwitcher, TabbedContent, TabPane
from textual.widgets._tabbed_content import ContentTab, ContentTabs, Tab
from textual.widgets._tabs import Underline

if TYPE_CHECKING:
    from gojeera.app import MainScreen


logger = logging.getLogger('gojeera')


def _highlight_active_full_width(self: ContentTabs, animate: bool = True) -> None:
    """Move the underline bar to span the full active tab region, including padding."""
    underline = self.query_one(Underline)
    try:
        self.query_one('#tabs-list > Tab.-active')
    except NoMatches:
        object.__setattr__(underline, 'show_highlight', False)
        object.__setattr__(underline, 'highlight_start', 0)
        object.__setattr__(underline, 'highlight_end', 0)
        return

    object.__setattr__(underline, 'show_highlight', True)

    def move_underline(animate: bool) -> None:
        try:
            active_tab = self.query_one('#tabs-list > Tab.-active')
        except NoMatches:
            return

        start, end = active_tab.virtual_region.column_span
        if animate:
            underline.animate(
                'highlight_start',
                start,
                duration=0.3,
                level='basic',
            )
            underline.animate(
                'highlight_end',
                end,
                duration=0.3,
                level='basic',
            )
        else:
            object.__setattr__(underline, 'highlight_start', start)
            object.__setattr__(underline, 'highlight_end', end)

    if animate and self.app.animation_level != 'none':
        self.set_timer(
            0.02,
            lambda: self.call_after_refresh(move_underline, True),
        )
    else:
        self.call_after_refresh(move_underline, False)


class ExtendedTabbedContent(TabbedContent):
    """Custom TabbedContent that handles Tab navigation in a custom manner."""

    can_focus = True

    DEFAULT_CSS = """
    ExtendedTabbedContent > ContentTabs ContentTab {
        background: transparent;
        color: $text-muted;
    }

    ExtendedTabbedContent > ContentTabs ContentTab.-badged {
        padding: 0 0 0 1;
    }

    ExtendedTabbedContent > ContentTabs ContentTab:hover,
    ExtendedTabbedContent > ContentTabs ContentTab:focus {
        background: $primary-muted;
        color: $text-primary;
        text-style: bold;
    }

    ExtendedTabbedContent > ContentTabs:focus ContentTab.-active {
        background: $primary-muted;
        color: $text-primary;
        text-style: bold;
    }

    ExtendedTabbedContent > ContentTabs .underline--bar {
        color: $primary;
    }
    """

    BINDINGS = [
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

    def __init__(self, *titles: str, external_content: bool = False, **kwargs) -> None:
        super().__init__(*titles, **kwargs)
        self.external_content = external_content
        self._external_information_panel = None
        self._tab_base_labels: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        pane_content = [
            self._set_id(
                (
                    content
                    if isinstance(content, TabPane)
                    else TabPane(title or self.render_str(f'Tab {index}'), content)
                ),
                self._generate_tab_id(),
            )
            for index, (title, content) in enumerate(zip_longest(self.titles, self._tab_content), 1)
        ]
        tabs = [
            ContentTab(
                content._title,
                content.id or '',
                disabled=content.disabled,
            )
            for content in pane_content
        ]

        content_tabs = ContentTabs(*tabs, active=self._initial or None, tabbed_content=self)
        object.__setattr__(
            content_tabs,
            '_highlight_active',
            MethodType(_highlight_active_full_width, content_tabs),
        )
        yield content_tabs

        with ContentSwitcher(initial=self._initial or None):
            yield from pane_content

    @property
    def tabs_widget(self) -> ContentTabs:
        return self.query_one(ContentTabs)

    @property
    def information_panel(self):
        from gojeera.components.work_item_information import WorkItemInformation

        if self._external_information_panel is None:
            self._external_information_panel = self.screen.query_one(WorkItemInformation)
        return self._external_information_panel

    @property
    def work_item_fields_widget(self):
        from gojeera.components.work_item_fields import WorkItemFields

        return self.screen.query_one(WorkItemFields)

    @property
    def tab_count(self) -> int:
        return self.tabs_widget.tab_count

    def get_tab(self, pane_id: str | TabPane) -> Tab:
        target_id = pane_id.id if isinstance(pane_id, TabPane) else pane_id
        return self.tabs_widget.get_content_tab(target_id)

    @staticmethod
    def _label_text(label: object) -> str:
        if isinstance(label, str):
            return label
        plain = getattr(label, 'plain', None)
        if isinstance(plain, str):
            return plain
        return str(label)

    def _tab_base_label(self, tab_id: str) -> str:
        if tab_id not in self._tab_base_labels:
            self._tab_base_labels[tab_id] = self._label_text(self.get_tab(tab_id).label)
        return self._tab_base_labels[tab_id]

    def set_tab_badge(self, tab_id: str, badge: int | None) -> None:
        tab = self.get_tab(tab_id)
        base_label = self._tab_base_label(tab_id)
        if badge is not None and badge > 0:
            tab.add_class('-badged')
            tab.label = f'{base_label}[bold $text-primary] {badge} [/]'
        else:
            tab.remove_class('-badged')
            tab.label = base_label

    def hide_tab(self, tab_id: str) -> None:
        self.tabs_widget.hide(tab_id)
        if self.active == tab_id:
            visible_tabs = self.visible_tab_ids()
            if visible_tabs:
                self.active = visible_tabs[0]

    def show_tab(self, tab_id: str) -> None:
        self.tabs_widget.show(tab_id)

    def visible_tab_ids(self) -> list[str]:
        return [
            pane.id
            for pane in self.query(TabPane)
            if pane.id and self.get_tab(pane.id) is not None and self.get_tab(pane.id).display
        ]

    def _sync_external_content(self, active: str) -> None:
        if not self.external_content:
            return

        try:
            active_pane_id = self.information_panel.pane_id_for_tab(active)
            if self.information_panel.content_switcher.current != active_pane_id:
                self.information_panel.set_active_tab(active)
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def _watch_active(self, active: str) -> None:
        super()._watch_active(active)
        self._sync_external_content(active)

    def on_focus(self) -> None:
        self.screen.refresh_bindings()

    def on_descendant_focus(self) -> None:
        self.screen.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'edit_work_item_info':
            return self.active == 'tab-description'
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
        if self.active == 'tab-description':
            from gojeera.components.work_item_description import WorkItemInfoContainer

            info_container = self.screen.query_one(WorkItemInfoContainer)
            await info_container.action_edit_work_item_info()

    async def action_add_attachment(self) -> None:
        if self.active == 'tab-attachments':
            from gojeera.components.work_item_attachments import WorkItemAttachmentsWidget

            attachments_widget = self.screen.query_one(WorkItemAttachmentsWidget)
            await attachments_widget.action_add_attachment()

    async def action_new_work_item_subtask(self) -> None:
        if self.active == 'tab-subtasks':
            from typing import cast

            from gojeera.components.new_work_item_screen import AddWorkItemScreen

            screen = cast('MainScreen', self.screen)  # noqa: F821

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
                    parent_work_item=screen.work_item_info_container.work_item,
                ),
                callback=screen.new_work_item,
            )

    async def action_link_work_item(self) -> None:
        if self.active == 'tab-related':
            from gojeera.components.work_item_related_work_items import RelatedWorkItemsWidget

            links_widget = self.screen.query_one(RelatedWorkItemsWidget)
            await links_widget.action_link_work_item()

    async def action_add_remote_link(self) -> None:
        if self.active == 'tab-links':
            from gojeera.components.work_item_web_links import WorkItemRemoteLinksWidget

            remote_links_widget = self.screen.query_one(WorkItemRemoteLinksWidget)
            await remote_links_widget.action_add_remote_link()

    def action_add_comment(self) -> None:
        if self.active == 'tab-comments':
            from gojeera.components.work_item_comments import WorkItemCommentsWidget

            comments_widget = self.screen.query_one(WorkItemCommentsWidget)
            comments_widget.action_add_comment()

    def action_view_worklog(self) -> None:
        try:
            self.work_item_fields_widget.action_view_worklog()
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def action_log_work(self) -> None:
        try:
            self.work_item_fields_widget.action_log_work()
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def action_focus_content(self) -> None:
        focused = self.screen.focused

        if focused is self or (focused and isinstance(focused, (ContentTab, ContentTabs))):
            active_pane = self.get_pane(self.active)
            if self.external_content:
                try:
                    active_pane = self.information_panel.get_active_pane()
                except Exception as e:
                    logger.debug(f'Exception occurred: {e}')
            if active_pane:
                for child in active_pane.walk_children():
                    if isinstance(child, (Container, VerticalScroll, VerticalGroup, Center)):
                        continue

                    can_focus = getattr(child, 'can_focus', False)
                    focusable = getattr(child, 'focusable', False)

                    if can_focus and focusable:
                        focus = getattr(child, 'focus', None)
                        if callable(focus):
                            focus()

                        scroll_visible = getattr(child, 'scroll_visible', None)
                        if callable(scroll_visible):
                            scroll_visible()
                        return

        self.screen.focus_next()

    def action_focus_previous_or_tabs(self) -> None:
        focused = self.screen.focused

        if focused:
            active_pane = self.get_pane(self.active)
            if self.external_content:
                try:
                    active_pane = self.information_panel.get_active_pane()
                except Exception as e:
                    logger.debug(f'Exception occurred: {e}')
            if active_pane and focused in active_pane.walk_children():
                first_focusable = None
                for child in active_pane.walk_children():
                    can_focus = getattr(child, 'can_focus', False)
                    focusable = getattr(child, 'focusable', False)

                    if can_focus and focusable:
                        first_focusable = child
                        break

                if focused == first_focusable:
                    self.tabs_widget.focus()
                    return

        self.screen.focus_previous()
