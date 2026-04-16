from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import Reactive, reactive
from textual.widgets import ContentSwitcher

from gojeera.components.work_item_attachments import WorkItemAttachmentsWidget
from gojeera.components.work_item_comments import WorkItemCommentsWidget
from gojeera.components.work_item_description import (
    WorkItemInfoContainer,
    WorkItemSummary,
)
from gojeera.components.work_item_related_work_items import RelatedWorkItemsWidget
from gojeera.components.work_item_subtasks import WorkItemChildWorkItemsWidget
from gojeera.components.work_item_web_links import WorkItemRemoteLinksWidget
from gojeera.models import JiraWorkItem
from gojeera.widgets.work_item_breadcrumb import WorkItemBreadcrumb


class WorkItemInformation(Container):
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

    def compose(self) -> ComposeResult:
        with ContentSwitcher(id='work-item-information-switcher', initial='pane-description'):
            with Vertical(id='pane-description', classes='summary-description-container'):
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

    @property
    def breadcrumb_widget(self) -> WorkItemBreadcrumb:
        return self.screen.query_one(WorkItemBreadcrumb)

    @property
    def header_summary_widget(self) -> WorkItemSummary:
        return self.screen.query_one('#details-work-item-summary', WorkItemSummary)

    @property
    def content_switcher(self) -> ContentSwitcher:
        return self.query_one('#work-item-information-switcher', ContentSwitcher)

    @staticmethod
    def pane_id_for_tab(tab_id: str) -> str:
        return f'pane-{tab_id.removeprefix("tab-")}'

    def set_active_tab(self, tab_id: str) -> None:
        self.content_switcher.current = self.pane_id_for_tab(tab_id)

    def get_active_pane(self):
        return self.query_one(f'#{self.content_switcher.current}')

    def watch_work_item(self, work_item: JiraWorkItem | None) -> None:
        self.breadcrumb_widget.set_work_item(work_item)

        if work_item is None:
            self.header_summary_widget.update('')
            self.header_summary_widget.display = False
            return

        self.header_summary_widget.update(work_item.summary)
        self.header_summary_widget.display = True
