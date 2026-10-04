from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey
from typing_extensions import Self


@dataclass(slots=True)
class TableRecord:
    key: str
    cells: tuple[str, ...]
    payload: Any = None


class ExtendedTable(DataTable):
    """Data table with vim navigation, selection-only clicks and optional model payloads."""

    jump_mode: ClassVar[str | None] = 'focus'

    class NearEnd(Message):
        @property
        def control(self) -> ExtendedTable:
            assert isinstance(self._sender, ExtendedTable)
            return self._sender

    BINDINGS = [
        Binding('h', 'cursor_left', 'Scroll left', show=False),
        Binding('j', 'cursor_down', 'Next row', show=False),
        Binding('k', 'cursor_up', 'Previous row', show=False),
        Binding('l', 'cursor_right', 'Scroll right', show=False),
        Binding('g', 'scroll_top', 'First row', show=False),
        Binding('G', 'scroll_bottom', 'Last row', show=False),
        *DataTable.BINDINGS,
    ]

    def __init__(
        self,
        *args: Any,
        columns: Sequence[str] | None = None,
        disable_empty: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._column_labels = columns
        self._disable_empty = disable_empty
        self._row_styles: dict[RowKey, Style] = {}
        self._records: dict[str, TableRecord] = {}
        self._near_end_count: int | None = None
        self._mouse_selecting = False
        if disable_empty:
            self.can_focus = False

    def on_mount(self) -> None:
        if self._column_labels is not None:
            self.add_columns(*self._column_labels)

    async def _on_click(self, event: events.Click) -> None:
        # Keep DataTable's hit testing, header events and scrolling, but reserve
        # row activation for Enter rather than clicks on the highlighted row.
        event.prevent_default()
        self._mouse_selecting = True
        try:
            await super()._on_click(event)
        finally:
            self._mouse_selecting = False

    def _post_selected_message(self) -> None:
        if not self._mouse_selecting:
            super()._post_selected_message()

    @property
    def selected_payload(self) -> Any:
        if not self.row_count:
            return None
        key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
        record = self._records.get(key or '')
        return record.payload if record else None

    def clear(self, columns: bool = False) -> Self:
        self._row_styles.clear()
        self._records.clear()
        self._near_end_count = None
        if self._disable_empty:
            self.can_focus = False
        return super().clear(columns)

    def clear_records(self) -> None:
        self.clear()

    def set_records(self, records: Sequence[TableRecord]) -> None:
        selected_key = None
        if self.row_count:
            selected_key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
        with self.app.batch_update():
            self.clear_records()
            self.append_records(records)
            if selected_key in self._records:
                self.focus_record_by_key(selected_key)

    def append_records(self, records: Sequence[TableRecord]) -> None:
        with self.app.batch_update():
            for record in records:
                self.add_row(*(Text(cell) for cell in record.cells), key=record.key, height=None)
                self._records[record.key] = record
            if self._disable_empty:
                self.can_focus = bool(self.row_count)

    def focus_record_by_key(self, key: str) -> bool:
        if key not in self._records:
            return False
        self.move_cursor(row=self.get_row_index(key))
        return True

    def select_index(
        self, index: int, *, scroll_into_view: bool = True, focus: bool = False
    ) -> None:
        self.move_cursor(row=index, scroll=scroll_into_view)
        if focus:
            self.focus()

    def _notify_near_end(self) -> None:
        if not self.row_count or self._near_end_count == self.row_count:
            return
        viewport_height = max(1, self.scrollable_content_region.height)
        if self.max_scroll_y - self.scroll_y <= viewport_height:
            self._near_end_count = self.row_count
            self.post_message(self.NearEnd())

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        self._notify_near_end()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._notify_near_end()

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
        row_keys = [self.add_row(*row, height=None) for row in rows]
        if self._disable_empty:
            self.can_focus = bool(self.row_count)
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
