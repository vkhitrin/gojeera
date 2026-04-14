from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class WorkItemFooterDetails(Static):
    """Reusable bottom-bar details widget for resolved work items."""

    DEFAULT_CSS = """
    WorkItemFooterDetails {
        width: 100%;
        height: 1;
        padding: 0 2;
        background: $surface;
        color: $text-muted;
    }

    WorkItemFooterDetails.success {
        background: $success-darken-2;
        color: $text;
        text-style: bold;
    }

    WorkItemFooterDetails.warning {
        background: $warning-darken-2;
        color: $text;
        text-style: bold;
    }

    WorkItemFooterDetails.error {
        background: $error-darken-1;
        color: $text;
        text-style: bold;
    }
    """

    def _set_message(self, message: str | Text) -> None:
        self.update(message if isinstance(message, Text) else Text(message))

    def show_searching(self, message: str = 'Looking up work item...') -> None:
        self.show_error(message)

    def show_not_found(self, message: str = 'Work item not found') -> None:
        self.show_error(message)

    def show_resolved(self, summary: str | Text) -> None:
        self.show_success(summary)

    def show_current_parent(self, work_item_key: str) -> None:
        self.show_warning(f'Set to current parent: {work_item_key}')

    def show_prompt(self, message: str | Text) -> None:
        self.show_default(message)

    def show_default(self, message: str | Text) -> None:
        self._set_message(message)
        self.remove_class('success')
        self.remove_class('warning')
        self.remove_class('error')

    def show_success(self, message: str | Text) -> None:
        self._set_message(message)
        self.remove_class('warning')
        self.remove_class('error')
        self.add_class('success')

    def show_warning(self, message: str | Text) -> None:
        self._set_message(message)
        self.remove_class('success')
        self.remove_class('error')
        self.add_class('warning')

    def show_error(self, message: str | Text) -> None:
        self._set_message(message)
        self.remove_class('success')
        self.remove_class('warning')
        self.add_class('error')
