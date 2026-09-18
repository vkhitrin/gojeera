from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import Reactive, reactive
from textual.widgets import ContentSwitcher

from gojeera.utils.ui.runtime import request_bindings_refresh

if TYPE_CHECKING:
    from gojeera.components.work_item.work_item_development import WorkItemDevelopmentWidget
    from gojeera.components.work_item.work_item_fields import WorkItemFields
    from gojeera.components.work_item.work_item_history import WorkItemHistoryWidget
    from gojeera.components.work_item.work_item_summary import WorkItemSummary
    from gojeera.components.work_item.work_item_web_links import WorkItemRemoteLinksWidget
    from gojeera.internal.models.work_items import JiraWorkItem
    from gojeera.widgets.work_item.work_item_breadcrumb import WorkItemBreadcrumb


class WorkItemInformation(Container, can_focus=True):
    """The middle content area controlled by the shared tab row."""

    DEFAULT_CSS = """
    WorkItemInformation {
        height: 1fr;
        width: 100%;
        scrollbar-size: 0 0;
        layout: vertical;
    }
    """

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)

    def __init__(self, **kwargs):
        super().__init__(id='work-item-information-container', **kwargs)
        self._history_widget: WorkItemHistoryWidget | None = None
        self._development_widget: WorkItemDevelopmentWidget | None = None
        self._remote_links_widget: WorkItemRemoteLinksWidget | None = None

    def compose(self) -> ComposeResult:
        from gojeera.components.work_item.work_item_attachments import (
            WorkItemAttachmentsWidget,
        )
        from gojeera.components.work_item.work_item_comments import WorkItemCommentsWidget
        from gojeera.components.work_item.work_item_description import WorkItemInfoContainer
        from gojeera.components.work_item.work_item_development import WorkItemDevelopmentWidget
        from gojeera.components.work_item.work_item_history import WorkItemHistoryWidget
        from gojeera.components.work_item.work_item_related_work_items import RelatedWorkItemsWidget
        from gojeera.components.work_item.work_item_subtasks import WorkItemChildWorkItemsWidget
        from gojeera.components.work_item.work_item_web_links import WorkItemRemoteLinksWidget

        with ContentSwitcher(id='work-item-information-switcher', initial='pane-description'):
            with Vertical(id='pane-description', classes='work-item-tab-pane'):
                yield WorkItemInfoContainer()
            with Vertical(id='pane-attachments', classes='work-item-tab-pane'):
                yield WorkItemAttachmentsWidget()
            with Vertical(id='pane-subtasks', classes='work-item-tab-pane'):
                yield WorkItemChildWorkItemsWidget()
            with Vertical(id='pane-related', classes='work-item-tab-pane'):
                yield RelatedWorkItemsWidget()
            with Vertical(id='pane-links', classes='work-item-tab-pane'):
                yield WorkItemRemoteLinksWidget()
            with Vertical(id='pane-comments', classes='work-item-tab-pane'):
                yield WorkItemCommentsWidget()
            with Vertical(id='pane-development', classes='work-item-tab-pane'):
                yield WorkItemDevelopmentWidget()
            with Vertical(id='pane-history', classes='work-item-tab-pane'):
                yield WorkItemHistoryWidget()

    @property
    def breadcrumb_widget(self) -> WorkItemBreadcrumb:
        return cast('WorkItemBreadcrumb', self.screen.query_one('#work-item-breadcrumb'))

    @property
    def header_summary_widget(self) -> WorkItemSummary:
        return cast('WorkItemSummary', self.screen.query_one('#details-work-item-summary'))

    @property
    def fields_widget(self) -> WorkItemFields:
        return cast('WorkItemFields', self.screen.query_one('#work-item-fields-container'))

    @property
    def content_switcher(self) -> ContentSwitcher:
        return self.query_one('#work-item-information-switcher', ContentSwitcher)

    @property
    def history_widget(self) -> WorkItemHistoryWidget:
        if self._history_widget is None:
            self._history_widget = cast(
                'WorkItemHistoryWidget', self.query_one('#work_item_history')
            )
        return self._history_widget

    @property
    def development_widget(self) -> WorkItemDevelopmentWidget:
        if self._development_widget is None:
            self._development_widget = cast(
                'WorkItemDevelopmentWidget', self.query_one('#work-item-development')
            )
        return self._development_widget

    @property
    def remote_links_widget(self) -> WorkItemRemoteLinksWidget:
        if self._remote_links_widget is None:
            self._remote_links_widget = cast(
                'WorkItemRemoteLinksWidget', self.query_one('#work_item_remote_links')
            )
        return self._remote_links_widget

    @staticmethod
    def pane_id_for_tab(tab_id: str) -> str:
        return f'pane-{tab_id.removeprefix("tab-")}'

    def set_active_tab(self, tab_id: str) -> None:
        self.content_switcher.current = self.pane_id_for_tab(tab_id)
        load_detail_tab = getattr(self.app, 'load_work_item_detail_tab_if_needed', None)
        if load_detail_tab is not None:
            load_detail_tab(tab_id)
        if tab_id == 'tab-history':
            self.history_widget.load_if_needed()
        elif tab_id == 'tab-development':
            self.development_widget.load_if_needed()
        elif tab_id == 'tab-links':
            self.remote_links_widget.load_if_needed()

    def get_active_pane(self):
        return self.query_one(f'#{self.content_switcher.current}')

    def on_focus(self) -> None:
        self._request_bindings_refresh()

    def action_view_worklog(self) -> None:
        self.fields_widget.action_view_worklog()

    def action_log_work(self) -> None:
        self.fields_widget.action_log_work()

    def watch_work_item(self, work_item: JiraWorkItem | None) -> None:
        self._request_bindings_refresh()
        self.breadcrumb_widget.set_work_item(work_item)

        if work_item is None:
            self.header_summary_widget.update('')
            self.header_summary_widget.display = False
            return

        self.header_summary_widget.update(work_item.summary)
        self.header_summary_widget.display = True

    def _request_bindings_refresh(self) -> None:
        request_bindings_refresh(self)
