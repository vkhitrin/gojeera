from __future__ import annotations

from typing import Any, cast

from rich.style import Style
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from gojeera.utils.ui.card_scroll import make_blank_card_strip, row_index_at_y, scroll_to_row
from gojeera.utils.ui.scroll_geometry import (
    container_height_for_scroll_view,
    render_width_for_scroll_view,
    update_vertical_overflow_class,
    wrap_text_cell_aware,
)

OVERFLOW_SCROLLBAR_CSS = """
    scrollbar-background: $surface;
    scrollbar-background-hover: $surface-lighten-1;
    scrollbar-background-active: $surface-lighten-1;
    scrollbar-color: $primary-darken-2;
    scrollbar-color-hover: $primary;
    scrollbar-color-active: $primary-lighten-1;
"""


class CardScrollViewMixin:
    CARD_PADDING: int
    rich_style: Style
    _pending_initial_render: bool
    _skip_next_resize_rebuild: bool
    _initial_render_attempts: int
    _row_starts: list[int]
    _rows: list[Any]
    _hovered_index: int | None

    def _complete_initial_render(self) -> None: ...

    def _rebuild_rows(self) -> None: ...

    def _cache_component_styles(self) -> None: ...

    def _build_pending_initial_layout(self) -> tuple[int, list[Any], int]:
        raise NotImplementedError

    def _blank_card_content_width(self, width: int) -> int:
        del width
        raise NotImplementedError

    def _apply_layout(
        self,
        width: int,
        rows: list[Any],
        virtual_height: int,
        *,
        force_scroll_to_top: bool = False,
    ) -> None:
        del width, rows, virtual_height, force_scroll_to_top
        raise NotImplementedError

    def _container_height(self) -> int:
        return container_height_for_scroll_view(cast(ScrollView, self))

    def _render_width(self) -> int:
        return render_width_for_scroll_view(cast(ScrollView, self))

    def _make_blank_card_strip(self, background_style: Style, width: int) -> Strip:
        return make_blank_card_strip(
            card_padding=self.CARD_PADDING,
            content_width=self._blank_card_content_width(width),
            background_style=background_style,
            base_style=self.rich_style,
            total_width=width,
        )

    def _wrap_text(self, text: str, width: int) -> list[str]:
        return wrap_text_cell_aware(text, width)

    def _update_vertical_overflow_class(self, virtual_height: int) -> None:
        update_vertical_overflow_class(
            cast(ScrollView, self),
            virtual_height=virtual_height,
            container_height=self._container_height(),
        )

    def _row_index_at_y(self, y: int) -> int | None:
        return row_index_at_y(self._row_starts, self._rows, y)

    def _scroll_to_index(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        scroll_to_row(cast(ScrollView, self), row_y=row.y, row_height=row.height)

    def _update_hovered_index(self, y: int) -> None:
        hovered_index = self._row_index_at_y(y)
        if hovered_index != self._hovered_index:
            self._hovered_index = hovered_index
            cast(ScrollView, self).refresh()

    def _clear_hovered_index(self) -> None:
        if self._hovered_index is not None:
            self._hovered_index = None
            cast(ScrollView, self).refresh()

    def _hide_horizontal_scrollbar(self) -> None:
        view = cast(ScrollView, self)
        view.show_horizontal_scrollbar = False
        if view._horizontal_scrollbar is not None:
            view.horizontal_scrollbar.display = False

    def _reset_card_scroll_state(
        self,
        *,
        refresh: bool = False,
        hide: bool = False,
    ) -> None:
        view = cast(ScrollView, self)
        self._rows = []
        self._row_starts = []
        view.virtual_size = Size(max(1, view.size.width), 0)
        self._update_vertical_overflow_class(0)
        view._scroll_update(view.virtual_size)
        view.scroll_to(y=0, animate=False, force=True, immediate=True)
        if hide:
            view.display = False
        if refresh:
            view.refresh()

    def on_resize(self) -> None:
        if self._pending_initial_render:
            self._complete_initial_render()
            return
        if self._skip_next_resize_rebuild:
            self._skip_next_resize_rebuild = False
            return
        self._rebuild_rows()

    def notify_style_update(self) -> None:
        view = cast(ScrollView, self)
        ScrollView.notify_style_update(view)
        if not view.is_mounted:
            return
        self._cache_component_styles()
        view.refresh()

    def _parent_content_width(self) -> int:
        view = cast(ScrollView, self)
        if view.parent is None:
            return 0

        parent_content_region = getattr(view.parent, 'content_region', None)
        parent_size = getattr(view.parent, 'size', None)
        return (parent_content_region.width if parent_content_region is not None else 0) or (
            parent_size.width if parent_size is not None else 0
        )

    def _continue_initial_render(
        self,
        *,
        has_content: bool,
        retry_callback: Any,
    ) -> bool:
        view = cast(ScrollView, self)

        if not has_content:
            self._pending_initial_render = False
            self._initial_render_attempts = 0
            return False

        self._initial_render_attempts += 1
        render_width = self._render_width()
        content_width = view.content_region.width
        scrollable_width = view.scrollable_content_region.width
        if self._initial_render_attempts < 4 and (
            content_width <= 0 or scrollable_width <= 0 or render_width <= 1
        ):
            view.call_after_refresh(retry_callback)
            return False

        return True

    def _finalize_initial_layout(
        self,
        width: int,
        rows: list[Any],
        virtual_height: int,
    ) -> None:
        view = cast(ScrollView, self)
        self._apply_layout(
            width,
            rows,
            virtual_height,
            force_scroll_to_top=True,
        )
        self._pending_initial_render = False
        self._initial_render_attempts = 0
        self._skip_next_resize_rebuild = True
        view.display = True
        view.refresh()

    def _complete_initial_render_with(
        self,
        *,
        has_content: bool,
        retry_callback: Any,
        after_finalize: Any | None = None,
    ) -> None:
        if not self._pending_initial_render:
            return
        if not self._continue_initial_render(
            has_content=has_content,
            retry_callback=retry_callback,
        ):
            return

        width, rows, virtual_height = self._build_pending_initial_layout()
        self._finalize_initial_layout(width, rows, virtual_height)
        if after_finalize is not None:
            after_finalize()
