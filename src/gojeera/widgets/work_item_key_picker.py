from __future__ import annotations

from textual.message import Message

from gojeera.widgets.extended_input import ExtendedInput


class WorkItemKeyInput(ExtendedInput):
    """Input widget for entering a Jira work item key."""

    class Activated(Message):
        def __init__(self, input_widget: 'WorkItemKeyInput') -> None:
            self.input_widget = input_widget
            super().__init__()

    def __init__(self, placeholder: str = 'Type a work item key') -> None:
        super().__init__(
            placeholder=placeholder,
            type='text',
        )
        self.compact = True

    def on_click(self) -> None:
        self.post_message(self.Activated(self))
