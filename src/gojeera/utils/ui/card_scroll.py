from __future__ import annotations

from bisect import bisect_right
from typing import Any

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.scroll_view import ScrollView
from textual.strip import Strip


def make_card_content_strip(
    *,
    card_padding: int,
    content_width: int,
    text: str,
    text_style: Style,
    background_style: Style,
    base_style: Style,
    total_width: int,
) -> Strip:
    text_width = cell_len(text)
    fill_width = max(0, content_width - text_width)
    return Strip(
        [
            Segment(' ' * card_padding, background_style),
            Segment(text, background_style + text_style),
            Segment(' ' * fill_width, background_style),
            Segment(' ' * card_padding, background_style),
            Segment(' ', base_style),
        ],
        total_width,
    )


def make_blank_card_strip(
    *,
    card_padding: int,
    content_width: int,
    background_style: Style,
    base_style: Style,
    total_width: int,
) -> Strip:
    return Strip(
        [
            Segment(' ' * card_padding, background_style),
            Segment(' ' * content_width, background_style),
            Segment(' ' * card_padding, background_style),
            Segment(' ', base_style),
        ],
        total_width,
    )


def row_index_at_y(row_starts: list[int], rows: list[Any], y: int) -> int | None:
    if not rows:
        return None
    index = bisect_right(row_starts, y) - 1
    if index < 0:
        return None
    row = rows[index]
    return index if y < row.y + row.height else None


def scroll_to_row(scroll_view: ScrollView, *, row_y: int, row_height: int) -> None:
    viewport_height = scroll_view.container_size.height or scroll_view.size.height
    if viewport_height <= 0:
        return
    viewport_top = scroll_view.scroll_offset.y
    viewport_bottom = viewport_top + viewport_height
    row_bottom = row_y + row_height
    if row_y < viewport_top:
        scroll_view.scroll_to(y=row_y, animate=False, force=True, immediate=True)
    elif row_bottom > viewport_bottom:
        scroll_view.scroll_to(
            y=max(0, row_bottom - viewport_height),
            animate=False,
            force=True,
            immediate=True,
        )
