from textual.widgets import Static


class WorkItemSummary(Static, can_focus=False):
    """A widget to display the work item summary."""

    DEFAULT_CSS = """
    WorkItemSummary {
        border: none;
        text-style: bold;
        color: $accent;
        padding: 0 1 1 1;
        width: 100%;
        content-align: left middle;
        background: transparent;
    }
    """

    def __init__(self, widget_id: str = 'work_item_description_summary'):
        super().__init__('', id=widget_id, markup=False)
        self.can_focus = False
