from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from gojeera.utils.ui.card_scroll import make_card_content_strip
from gojeera.utils.ui.scroll_geometry import (
    build_scrollbar_aware_layout,
)
from gojeera.widgets.layout.card_scroll_view_mixin import (
    OVERFLOW_SCROLLBAR_CSS,
    CardScrollViewMixin,
)


@dataclass(slots=True)
class Record:
    key: str
    title: str
    meta: str = ''
    footer: str = ''
    payload: Any = None


@dataclass(slots=True)
class RecordRowLayout:
    record: Record
    y: int
    height: int
    meta_lines: list[str]
    title_lines: list[str]
    footer_lines: list[str]


class RecordList(CardScrollViewMixin, ScrollView):
    jump_mode: ClassVar[str | None] = 'focus'
    CARD_PADDING = 1

    COMPONENT_CLASSES = {
        'record-list--card',
        'record-list--card-selected',
        'record-list--card-hover',
        'record-list--text',
        'record-list--text-active',
    }

    DEFAULT_CSS = """
    RecordList {
        width: 100%;
        height: 1fr;
        background: transparent;
        margin: 0;
        padding: 0;
        overflow-x: hidden;
        overflow-y: scroll;
        scrollbar-gutter: stable;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
    }

    RecordList.-overflowing {
__OVERFLOW_SCROLLBAR_CSS__
    }

    RecordList > .record-list--text {
        text-style: none;
    }

    RecordList > .record-list--text-active {
        color: $primary-lighten-2;
        text-style: none;
    }
    """.replace('__OVERFLOW_SCROLLBAR_CSS__', OVERFLOW_SCROLLBAR_CSS)

    BINDINGS = [
        Binding('j', 'cursor_down', 'Next item', show=False),
        Binding('k', 'cursor_up', 'Previous item', show=False),
        Binding('down', 'cursor_down', 'Next item', show=False),
        Binding('up', 'cursor_up', 'Previous item', show=False),
        Binding('g', 'first_item', 'First item', show=False),
        Binding('G', 'last_item', 'Last item', show=False),
        Binding('enter', 'invoke_selected', 'Open', show=False),
    ]

    class _RowMessage(Message):
        def __init__(self, row: Record, index: int) -> None:
            super().__init__()
            self.row = row
            self.index = index

        @property
        def control(self) -> 'RecordList':
            return cast('RecordList', self._sender)

    class RowHighlighted(_RowMessage):
        pass

    class RowInvoked(_RowMessage):
        pass

    def __init__(self, *, widget_id: str, classes: str | None = None):
        super().__init__(id=widget_id, classes=classes)
        self.can_focus = False
        self._records: list[Record] = []
        self._selected_index: int | None = None
        self._hovered_index: int | None = None
        self._is_active = False
        self._rows: list[RecordRowLayout] = []
        self._row_starts: list[int] = []
        self._layout_width = 1
        self._card_style: Style | None = None
        self._card_selected_style: Style | None = None
        self._card_hover_style: Style | None = None
        self._text_style: Style | None = None
        self._text_active_style: Style | None = None
        self._pending_initial_render = False
        self._initial_render_attempts = 0
        self._skip_next_resize_rebuild = False
        self._initial_render_scheduled = False

    @property
    def selected_record(self) -> Record | None:
        if self._selected_index is not None and 0 <= self._selected_index < len(self._records):
            return self._records[self._selected_index]
        return None

    @property
    def selected_payload(self) -> Any | None:
        record = self.selected_record
        return None if record is None else record.payload

    def on_mount(self) -> None:
        self._cache_component_styles()
        if self._records:
            self._pending_initial_render = True
            self._initial_render_attempts = 0
            self._schedule_initial_render()

    def clear_records(self) -> None:
        if not self.is_mounted:
            self._records = []
            self._selected_index = None
            self._hovered_index = None
            self.can_focus = False
            return
        self._clear_mounted_records()

    def set_records(self, records: list[Record]) -> None:
        next_records = list(records)
        next_selected_index = 0 if self._is_active and next_records else None
        if not self.is_mounted:
            self._records = next_records
            self._selected_index = next_selected_index
            self._hovered_index = None
            self.can_focus = bool(next_records)
            return
        if not next_records:
            self._clear_mounted_records()
            return

        with self.app.batch_update():
            self._records = next_records
            self._selected_index = next_selected_index
            self._hovered_index = None
            self.can_focus = True
            self._pending_initial_render = True
            self._initial_render_attempts = 0
            self._reset_render_state(refresh=False)
        self._schedule_initial_render()

    def _clear_mounted_records(self) -> None:
        with self.app.batch_update():
            self._records = []
            self._selected_index = None
            self._hovered_index = None
            self.can_focus = False
            self._pending_initial_render = False
            self._initial_render_attempts = 0
            self._initial_render_scheduled = False
            self.display = True
            self._reset_render_state(refresh=True)

    def focus_record_by_key(self, key: str) -> bool:
        for index, record in enumerate(self._records):
            if record.key == key:
                self.select_index(index, scroll_into_view=True, focus=True)
                return True
        return False

    def _cache_component_styles(self) -> None:
        self._card_style = self.get_component_rich_style('record-list--card', partial=True)
        self._card_selected_style = self.get_component_rich_style(
            'record-list--card-selected', partial=True
        )
        self._card_hover_style = self.get_component_rich_style(
            'record-list--card-hover', partial=True
        )
        text_style = self.get_component_styles('record-list--text')
        text_active_style = self.get_component_styles('record-list--text-active')

        self._text_style = text_style.partial_rich_style
        self._text_active_style = text_active_style.partial_rich_style

    def _reset_render_state(self, *, refresh: bool) -> None:
        self._layout_width = max(1, self.size.width)
        self._reset_card_scroll_state(refresh=refresh)

    def _schedule_initial_render(self) -> None:
        if self._initial_render_scheduled:
            return
        self._initial_render_scheduled = True
        self.call_after_refresh(self._run_scheduled_initial_render)

    def _run_scheduled_initial_render(self) -> None:
        self._initial_render_scheduled = False
        self._complete_initial_render()

    def _validate_layout_after_initial_render(self) -> None:
        if not self.is_mounted or self._pending_initial_render:
            return

        width, rows, virtual_height = self._build_layout_for_records(
            self._records,
            base_width=self._safe_render_width(),
        )
        if width == self.virtual_size.width and virtual_height == self.virtual_size.height:
            return

        self._skip_next_resize_rebuild = False
        self._commit_layout(width, rows, virtual_height, reset_scroll=False)

    def _actual_render_width(self) -> int:
        return max(
            0,
            self.scrollable_content_region.width or self.content_region.width or self.size.width,
        )

    def _safe_render_width(self) -> int:
        render_width = self._actual_render_width()
        if render_width > 1:
            return render_width
        if self.parent is not None:
            parent = self.parent if isinstance(self.parent, ScrollView) else None
            if parent is not None:
                parent_width = (
                    parent.scrollable_content_region.width
                    or parent.content_region.width
                    or parent.size.width
                )
                if parent_width > 1:
                    return parent_width
            parent_width = self._parent_content_width()
            if parent_width > 1:
                return parent_width
        return 0

    def _content_width(self, width: int) -> int:
        return max(1, width - ((self.CARD_PADDING * 2) + 1))

    def _wrap(self, text: str, width: int) -> list[str]:
        return self._wrap_text(' '.join(part for part in text.splitlines() if part).strip(), width)

    def _compose_record_line(self, record: Record) -> str:
        return ' • '.join(part for part in (record.meta, record.title, record.footer) if part)

    def _build_rows_for_records(
        self, records: list[Record], width: int
    ) -> tuple[list[RecordRowLayout], int]:
        content_width = self._content_width(width)
        rows: list[RecordRowLayout] = []
        y = 0

        for index, record in enumerate(records):
            title_lines = self._wrap(self._compose_record_line(record), content_width)
            content_height = len(title_lines)
            height = content_height
            rows.append(
                RecordRowLayout(
                    record=record,
                    y=y,
                    height=height,
                    meta_lines=[],
                    title_lines=title_lines,
                    footer_lines=[],
                )
            )
            y += height
            if index < len(records) - 1:
                y += 1

        return rows, y

    def _build_layout_for_current_geometry(self) -> tuple[int, list[RecordRowLayout], int]:
        return self._build_layout_for_records(self._records, base_width=self._safe_render_width())

    def _build_pending_initial_layout(self) -> tuple[int, list[RecordRowLayout], int]:
        return self._build_layout_for_records(self._records, base_width=self._safe_render_width())

    def _build_layout_for_records(
        self, records: list[Record], *, base_width: int | None = None
    ) -> tuple[int, list[RecordRowLayout], int]:
        return build_scrollbar_aware_layout(
            base_width=max(
                1,
                base_width if base_width is not None else self._safe_render_width(),
            ),
            container_height=self._container_height(),
            scrollbar_size_vertical=self.scrollbar_size_vertical,
            build_rows_for_width=lambda width: self._build_rows_for_records(records, width),
        )

    def _commit_layout(
        self,
        width: int,
        rows: list[RecordRowLayout],
        virtual_height: int,
        *,
        reset_scroll: bool = False,
    ) -> None:
        self._layout_width = max(1, width)
        self._rows = rows
        self._row_starts = [row.y for row in rows]
        self.virtual_size = Size(width, virtual_height)
        self._update_vertical_overflow(virtual_height)
        self._scroll_update(self.virtual_size)
        if reset_scroll:
            self.scroll_to(y=0, animate=False, force=True, immediate=True)
        self.refresh()

    def _apply_layout(
        self,
        width: int,
        rows: list[RecordRowLayout],
        virtual_height: int,
        *,
        force_scroll_to_top: bool = False,
    ) -> None:
        self._commit_layout(
            width,
            rows,
            virtual_height,
            reset_scroll=force_scroll_to_top,
        )

    def _rebuild_rows(self, *, reset_scroll: bool = False) -> None:
        if not self._records:
            self._reset_render_state(refresh=True)
            return
        width, rows, virtual_height = self._build_layout_for_current_geometry()
        self._commit_layout(width, rows, virtual_height, reset_scroll=reset_scroll)

    def _complete_initial_render(self) -> None:
        self._initial_render_scheduled = False
        if not self._pending_initial_render:
            return
        if not self._records:
            self._pending_initial_render = False
            self._initial_render_attempts = 0
            return

        render_width = self._safe_render_width()
        if render_width <= 1:
            self._initial_render_attempts += 1
            if self._initial_render_attempts < 4:
                self._schedule_initial_render()
            return

        width, rows, virtual_height = self._build_layout_for_records(
            self._records,
            base_width=render_width,
        )
        with self.app.batch_update():
            self._finalize_initial_layout(width, rows, virtual_height)
            if self._selected_index is not None:
                self._post_highlight()
        self.call_after_refresh(self._validate_layout_after_initial_render)

    def _update_vertical_overflow(self, virtual_height: int) -> None:
        self._update_vertical_overflow_class(virtual_height)

    def _refresh_scrollbars(self) -> None:
        super()._refresh_scrollbars()
        self._hide_horizontal_scrollbar()

    def _update_selection(self) -> None:
        self.refresh()

    def _post_highlight(self) -> None:
        if selected := self.selected_record:
            selected_index = self._selected_index
            if selected_index is not None:
                self.post_message(self.RowHighlighted(selected, selected_index))

    def _invoke_selected(self) -> None:
        if selected := self.selected_record:
            selected_index = self._selected_index
            if selected_index is not None:
                self.post_message(self.RowInvoked(selected, selected_index))

    def select_index(
        self, index: int, *, scroll_into_view: bool = True, focus: bool = False
    ) -> bool:
        if not self._records or not 0 <= index < len(self._records):
            return False
        previous_index = self._selected_index
        self._selected_index = index
        if previous_index != index:
            self._update_selection()
            self._post_highlight()
        if scroll_into_view:
            self._scroll_to_index(index)
        if focus:
            self.focus()
        return True

    def _is_active_index(self, index: int) -> bool:
        return (self._is_active and self._selected_index == index) or self._hovered_index == index

    def _card_style_for_index(self, index: int) -> Style:
        if self._is_active and self._selected_index == index:
            return self._card_selected_style or self.rich_style
        if self._hovered_index == index:
            return self._card_hover_style or self.rich_style
        return self._card_style or self.rich_style

    def _text_style_for_index(self, index: int) -> Style:
        if self._is_active_index(index):
            return self._text_active_style or self.rich_style
        return self._text_style or self.rich_style

    def _make_content_strip(
        self, text: str, text_style: Style, background_style: Style, width: int
    ) -> Strip:
        return make_card_content_strip(
            card_padding=self.CARD_PADDING,
            content_width=self._content_width(width),
            text=text,
            text_style=text_style,
            background_style=background_style,
            base_style=self.rich_style,
            total_width=width,
        )

    def _blank_card_content_width(self, width: int) -> int:
        return self._content_width(width)

    def render_line(self, y: int) -> Strip:
        width = self._layout_width if self._rows else self._render_width()
        if self._pending_initial_render or not self._rows:
            return Strip.blank(width, self.rich_style)

        document_y = y + self.scroll_offset.y
        row_index = self._row_index_at_y(document_y)
        if row_index is None:
            return Strip.blank(width, self.rich_style)

        row = self._rows[row_index]
        local_y = document_y - row.y
        background_style = self._card_style_for_index(row_index)
        if local_y < len(row.title_lines):
            return self._make_content_strip(
                row.title_lines[local_y],
                self._text_style_for_index(row_index),
                background_style,
                width,
            )
        return Strip.blank(width, self.rich_style)

    def action_cursor_down(self) -> None:
        if self._records:
            current_index = -1 if self._selected_index is None else self._selected_index
            self.select_index(min(current_index + 1, len(self._records) - 1))

    def action_cursor_up(self) -> None:
        if self._records:
            current_index = (
                len(self._records) if self._selected_index is None else self._selected_index
            )
            self.select_index(max(current_index - 1, 0))

    def action_first_item(self) -> None:
        if self._records:
            self.select_index(0)

    def action_last_item(self) -> None:
        if self._records:
            self.select_index(len(self._records) - 1)

    def action_invoke_selected(self) -> None:
        self._invoke_selected()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        event.prevent_default()

    async def on_click(self, event: events.Click) -> None:
        clicked_y = event.y + self.scroll_offset.y
        index = self._row_index_at_y(clicked_y)
        if index is None:
            return
        self.select_index(index, focus=True)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._update_hovered_index(event.y + self.scroll_offset.y)

    def on_leave(self, _: events.Leave) -> None:
        self._clear_hovered_index()

    def on_focus(self) -> None:
        self._is_active = True
        if self._selected_index is None and self._records:
            self.select_index(0, scroll_into_view=True, focus=False)
        else:
            self._update_selection()

    def on_blur(self) -> None:
        self._is_active = False
        self._hovered_index = None
        self._update_selection()
