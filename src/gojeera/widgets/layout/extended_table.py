from __future__ import annotations

from typing import Any

from rich.style import Style
from textual.binding import Binding
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey
from typing_extensions import Self


class ExtendedTable(DataTable):
    """Data table with vim-style row navigation."""

    BINDINGS = [
        Binding('h', 'cursor_left', 'Scroll left', show=False),
        Binding('j', 'cursor_down', 'Next row', show=False),
        Binding('k', 'cursor_up', 'Previous row', show=False),
        Binding('l', 'cursor_right', 'Scroll right', show=False),
        *DataTable.BINDINGS,
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._row_styles: dict[RowKey, Style] = {}

    def clear(self, columns: bool = False) -> Self:
        self._row_styles.clear()
        return super().clear(columns)

    def set_row_style(self, row_key: RowKey | str, style: Style) -> None:
        resolved_row_key = row_key if isinstance(row_key, RowKey) else RowKey(row_key)
        self._row_styles[resolved_row_key] = style
        self.refresh()

    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        row_style = super()._get_row_style(row_index, base_style)
        if row_index < 0:
            return row_style

        row_key = self._row_locations.get_key(row_index)
        if row_key in self._row_styles:
            return row_style + self._row_styles[row_key]

        return row_style
