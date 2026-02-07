"""Middle panel component for work item details (Summary, Attachments, etc.)."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import Reactive, reactive
from textual.widgets import Static, TabPane

from gojeera.components.work_item_attachments import WorkItemAttachmentsWidget
from gojeera.components.work_item_comments import WorkItemCommentsWidget
from gojeera.components.work_item_related_work_items import RelatedWorkItemsWidget
from gojeera.components.work_item_subtasks import WorkItemChildWorkItemsWidget
from gojeera.components.work_item_summary import WorkItemInfoContainer
from gojeera.components.work_item_web_links import WorkItemRemoteLinksWidget
from gojeera.models import JiraWorkItem
from gojeera.widgets.extended_tabbed_content import ExtendedTabbedContent


class WorkItemBreadcrumb(Static, can_focus=False):
    """A label widget to display work item breadcrumb (Parent / Work Item)."""

    DEFAULT_CSS = """
    WorkItemBreadcrumb {
        height: auto;
        padding: 0;
        color: $text-muted;
        text-style: bold;
        background: $background;
    }
    """

    def __init__(self):
        super().__init__('', id='work-item-breadcrumb', markup=False)
        self.can_focus = False


class WorkItemInformation(Vertical):
    """A container with tabs for Summary, Attachments, Subtasks, etc."""

    DEFAULT_CSS = """
    WorkItemInformation {
        scrollbar-size: 0 0;
    }
    """

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)

    def __init__(self, **kwargs):
        super().__init__(id='work-item-information-container', **kwargs)

    def compose(self) -> ComposeResult:
        yield WorkItemBreadcrumb()
        with ExtendedTabbedContent(id='tabs-information'):
            with TabPane(
                title='Summary',
                classes='summary-description-container',
                id='tab-summary',
            ):
                yield WorkItemInfoContainer()
            with TabPane(title='Attachments', id='tab-attachments'):
                yield WorkItemAttachmentsWidget()
            with TabPane(title='Subtasks', id='tab-subtasks'):
                yield WorkItemChildWorkItemsWidget()
            with TabPane(title='Related Items', id='tab-related'):
                yield RelatedWorkItemsWidget()
            with TabPane(title='Web Links', id='tab-links'):
                yield WorkItemRemoteLinksWidget()
            with TabPane(title='Comments', id='tab-comments'):
                yield WorkItemCommentsWidget()

    @property
    def breadcrumb_widget(self) -> WorkItemBreadcrumb:
        return self.query_one(WorkItemBreadcrumb)

    def watch_work_item(self, work_item: JiraWorkItem | None) -> None:
        if work_item is None:
            self.breadcrumb_widget.update('')
            return

        parts = []

        if work_item.project and work_item.project.name:
            parts.append(work_item.project.name)

        if work_item.parent_key and work_item.parent_key.strip():
            parent_text = work_item.parent_key.strip()
            if work_item.parent_work_item_type:
                parent_text = f'[{work_item.parent_work_item_type}] {parent_text}'
            parts.append(parent_text)

        work_item_text = work_item.key
        if work_item.work_item_type and work_item.work_item_type.name:
            work_item_text = f'[{work_item.work_item_type.name}] {work_item.key}'
        parts.append(work_item_text)

        breadcrumb_text = ' / '.join(parts)

        self.breadcrumb_widget.update(breadcrumb_text)
