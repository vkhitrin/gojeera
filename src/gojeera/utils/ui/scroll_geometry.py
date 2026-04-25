from __future__ import annotations

import textwrap
from typing import Callable, TypeVar, cast

from rich.cells import cell_len
from textual.scroll_view import ScrollView
from textual.widget import Widget

RowsT = TypeVar('RowsT')


def render_width_for_scroll_view(view: ScrollView) -> int:
    return max(
        1,
        view.scrollable_content_region.width or view.content_region.width or view.size.width,
    )


def container_height_for_scroll_view(view: ScrollView) -> int:
    container_height = 0
    if view.parent is not None:
        parent = cast(Widget, view.parent)
        container_height = parent.content_region.height or parent.size.height
    if container_height <= 0:
        container_height = view.container_size.height or view.size.height
    if container_height <= 0 and view.screen is not None:
        container_height = view.screen.size.height
    return max(0, container_height)


def wrap_text_cell_aware(text: str, width: int) -> list[str]:
    width = max(1, width)
    wrapped_lines: list[str] = []

    def split_by_cell_width(value: str) -> list[str]:
        if not value:
            return ['']
        chunks: list[str] = []
        current = ''
        for char in value:
            if current and cell_len(current + char) > width:
                chunks.append(current.rstrip())
                current = '' if char.isspace() else char
            else:
                current += char
        chunks.append(current.rstrip())
        return chunks or ['']

    def normalize_line(value: str) -> list[str]:
        normalized = value.rstrip().lstrip()
        if not normalized:
            return ['']
        if cell_len(normalized) <= width:
            return [normalized]
        return [chunk.lstrip() for chunk in split_by_cell_width(normalized)]

    for paragraph in text.splitlines() or ['']:
        initial_lines = textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=True,
            replace_whitespace=False,
            drop_whitespace=False,
        ) or ['']

        for line in initial_lines:
            wrapped_lines.extend(normalize_line(line))

    return wrapped_lines or ['']


def build_scrollbar_aware_layout(
    *,
    base_width: int,
    container_height: int,
    scrollbar_size_vertical: int,
    reserve_vertical_scrollbar: bool = False,
    build_rows_for_width: Callable[[int], tuple[RowsT, int]],
) -> tuple[int, RowsT, int]:
    width = max(1, base_width)
    if (
        reserve_vertical_scrollbar
        and scrollbar_size_vertical > 0
        and width > scrollbar_size_vertical
    ):
        width = max(1, width - scrollbar_size_vertical)
    rows, virtual_height = build_rows_for_width(width)

    if (
        not reserve_vertical_scrollbar
        and scrollbar_size_vertical > 0
        and virtual_height > container_height > 0
        and width > scrollbar_size_vertical
    ):
        width = max(1, width - scrollbar_size_vertical)
        rows, virtual_height = build_rows_for_width(width)

    return width, rows, virtual_height


def update_vertical_overflow_class(
    view: ScrollView,
    *,
    virtual_height: int,
    container_height: int,
) -> None:
    is_overflowing = virtual_height > container_height > 0
    if view.has_class('-overflowing') != is_overflowing:
        view.set_class(is_overflowing, '-overflowing')
