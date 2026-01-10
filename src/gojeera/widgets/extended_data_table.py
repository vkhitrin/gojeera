"""Common DataTable widgets with vim-style navigation."""

from textual.binding import Binding
from textual.widgets import DataTable


class ExtendedDataTable(DataTable):
    """A DataTable with vim-style navigation keybindings and textual-jumper support."""

    can_focus = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.jump_mode = 'focus'

    BINDINGS = [
        Binding(
            key='j',
            action='cursor_down',
            description='Down',
            show=False,
            tooltip='Move down',
        ),
        Binding(
            key='k',
            action='cursor_up',
            description='Up',
            show=False,
            tooltip='Move up',
        ),
        Binding(
            key='g',
            action='jump_to_first',
            description='First',
            show=False,
            tooltip='Jump to first',
        ),
        Binding(
            key='G',
            action='jump_to_last',
            description='Last',
            show=False,
            tooltip='Jump to last',
        ),
    ]

    def action_cursor_down(self) -> None:
        if self.row_count > 0:
            super().action_cursor_down()

    def action_cursor_up(self) -> None:
        if self.row_count > 0:
            super().action_cursor_up()

    def action_jump_to_first(self) -> None:
        if self.row_count > 0:
            self.move_cursor(row=0)

    def action_jump_to_last(self) -> None:
        if self.row_count > 0:
            self.move_cursor(row=self.row_count - 1)
