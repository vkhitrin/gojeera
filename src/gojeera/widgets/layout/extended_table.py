from __future__ import annotations

from collections.abc import Iterable
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

    def replace_rows(
        self,
        rows: Iterable[Iterable[Any]],
        *,
        row_styles: Iterable[Style | None] | None = None,
    ) -> list[RowKey]:
        """Replace all rows in one UI update and optionally apply per-row styles."""

        with self.app.batch_update():
            self.clear()
            row_keys = self._add_styled_rows(rows, row_styles)
        return row_keys

    def append_rows(
        self,
        rows: Iterable[Iterable[Any]],
        *,
        row_styles: Iterable[Style | None] | None = None,
    ) -> list[RowKey]:
        """Append rows in one UI update and optionally apply per-row styles."""

        with self.app.batch_update():
            row_keys = self._add_styled_rows(rows, row_styles)
        return row_keys

    def _add_styled_rows(
        self,
        rows: Iterable[Iterable[Any]],
        row_styles: Iterable[Style | None] | None,
    ) -> list[RowKey]:
        row_keys = self.add_rows(rows)
        if row_styles is not None:
            for row_key, row_style in zip(row_keys, row_styles, strict=True):
                if row_style is not None:
                    self._row_styles[row_key] = row_style
        self.refresh()
        return row_keys

    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        row_style = super()._get_row_style(row_index, base_style)
        if row_index < 0:
            return row_style

        row_key = self._row_locations.get_key(row_index)
        if row_key is not None and row_key in self._row_styles:
            return row_style + self._row_styles[row_key]

        return row_style
