from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import textwrap
from typing import TYPE_CHECKING, ClassVar, cast

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.reactive import Reactive, reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widget import Widget

from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem, JiraWorkItemSearchResponse
from gojeera.utils.urls import build_external_url_for_work_item

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


@dataclass(slots=True)
class SearchResultRow:
    work_item: JiraWorkItem
    y: int
    height: int
    meta_lines: list[str]
    summary_lines: list[str]
    footer_lines: list[str]

    @property
    def work_item_key(self) -> str:
        return self.work_item.key


class WorkItemSearchResultsScroll(ScrollView):
    """A VerticalScroll widget that displays work item search results."""

    CARD_PADDING = 1

    COMPONENT_CLASSES = {
        'search-result--card',
        'search-result--card-selected',
        'search-result--card-loaded',
        'search-result--card-hover',
        'search-result--meta',
        'search-result--meta-active',
        'search-result--summary',
        'search-result--summary-strong',
        'search-result--footer',
        'search-result--footer-active',
    }

    DEFAULT_CSS = """
    WorkItemSearchResultsScroll {
        background: transparent;
        overflow-x: hidden;
        overflow-y: auto;
        scrollbar-size-horizontal: 0;

        &:dark {
            & > .search-result--card-hover {
                background: $surface-lighten-1;
                color: $text;
            }

            & > .search-result--card-selected {
                background: $surface-lighten-1;
            }

            & > .search-result--card-loaded {
                background: $surface-lighten-1;
            }

            & > .search-result--summary,
            & > .search-result--summary-strong {
                color: $accent;
            }
        }

        &:light {
            & > .search-result--card-hover {
                background: $panel;
                color: $text;
            }

            & > .search-result--card-selected,
            & > .search-result--card-loaded {
                background: $panel;
                color: $text;
            }

            & > .search-result--meta,
            & > .search-result--meta-active {
                color: $panel-darken-3;
            }

            & > .search-result--footer,
            & > .search-result--footer-active {
                color: $panel-darken-3;
            }
        }
    }

    WorkItemSearchResultsScroll > .search-result--card {
        background: $surface;
    }

    WorkItemSearchResultsScroll.-overflowing {
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface-lighten-1;
        scrollbar-background-active: $surface-lighten-1;
        scrollbar-color: $primary-darken-2;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $primary-lighten-1;
    }

    WorkItemSearchResultsScroll > .search-result--meta {
        color: $text;
        text-style: none;
    }

    WorkItemSearchResultsScroll > .search-result--meta-active {
        color: $text;
        text-style: none;
    }

    WorkItemSearchResultsScroll > .search-result--summary {
        color: $accent-darken-1;
    }

    WorkItemSearchResultsScroll > .search-result--summary-strong {
        color: $accent-darken-1;
        text-style: bold;
    }

    WorkItemSearchResultsScroll > .search-result--footer {
        color: $text;
    }

    WorkItemSearchResultsScroll > .search-result--footer-active {
        color: $text;
        text-style: none;
    }
    """

    jump_mode: ClassVar[str | None] = 'focus'
    work_item_search_results: Reactive[JiraWorkItemSearchResponse | None] = reactive(
        None, always_update=True
    )

    BINDINGS = [
        Binding('j', 'cursor_down', 'Next item', show=False),
        Binding('k', 'cursor_up', 'Previous item', show=False),
        Binding('g', 'first_item', 'First item', show=False),
        Binding('G', 'last_item', 'Last item', show=False),
        Binding('down', 'cursor_down', 'Next item', show=False),
        Binding('up', 'cursor_up', 'Previous item', show=False),
        Binding('enter', 'select_work_item', 'Select item', show=False),
        Binding(
            key='p',
            action='previous_work_items_page',
            description='Previous Page',
            show=False,
        ),
        Binding(
            key='n',
            action='next_work_items_page',
            description='Next Page',
            show=False,
        ),
        Binding(
            key='ctrl+o',
            action='open_work_item_in_browser',
            description='Browse',
            show=True,
            tooltip='Open item in the browser',
        ),
        Binding(
            key='ctrl+b',
            action='clone_work_item',
            description='Clone',
            show=True,
            tooltip='Clone the selected work item',
        ),
        Binding(
            key='ctrl+y',
            action='copy_work_item_key',
            description='Copy Key',
            show=True,
            tooltip='Copy the work item key',
        ),
        Binding(
            key='ctrl+u',
            action='copy_work_item_url',
            description='Copy URL',
            show=True,
            tooltip='Copy the work item URL',
        ),
    ]

    def __init__(self):
        super().__init__(id='work_item_search_results')

        self.token_by_page: dict[int, str] = {}
        self.page = 1
        self.pending_page: int | None = None
        self.total_pages = 1
        self.current_work_item_key: str | None = None
        self.loaded_work_item_key: str | None = None
        self._selected_index: int = 0
        self._rows: list[SearchResultRow] = []
        self._row_starts: list[int] = []
        self._work_items: list[JiraWorkItem] = []
        self._hovered_index: int | None = None
        self._pending_initial_render = False
        self._initial_render_attempts = 0
        self._pending_theme_refresh = False
        self._skip_next_resize_rebuild = False
        self._card_style = None
        self._card_selected_style = None
        self._card_loaded_style = None
        self._card_hover_style = None
        self._meta_style = None
        self._meta_active_style = None
        self._summary_style = None
        self._summary_strong_style = None
        self._footer_style = None
        self._footer_active_style = None

        self.display = False

    @property
    def work_item_containers(self) -> list[SearchResultRow]:
        return self._rows

    @property
    def selected_work_item(self) -> SearchResultRow | None:
        if self._rows and 0 <= self._selected_index < len(self._rows):
            return self._rows[self._selected_index]
        return None

    @property
    def is_pending_initial_render(self) -> bool:
        return self._pending_initial_render

    def _base_card_width(self) -> int:
        available_width = (
            self.scrollable_content_region.width or self.content_region.width or self.size.width
        )
        if available_width <= 0 and self.parent is not None:
            parent = cast(Widget, self.parent)
            available_width = parent.content_region.width or parent.size.width
        if available_width <= 0 and self.screen is not None:
            available_width = max(1, self.screen.size.width // 4)
        return max(1, available_width)

    def _container_height(self) -> int:
        container_height = 0
        if self.parent is not None:
            parent = cast(Widget, self.parent)
            container_height = parent.content_region.height or parent.size.height
        if container_height <= 0:
            container_height = self.container_size.height or self.size.height
        if container_height <= 0 and self.screen is not None:
            container_height = self.screen.size.height
        return max(0, container_height)

    def _card_content_width(self, card_width: int) -> int:
        return max(1, card_width - ((self.CARD_PADDING * 2) + 1))

    def _render_width(self) -> int:
        return max(
            1,
            self.scrollable_content_region.width or self.content_region.width or self.size.width,
        )

    def on_resize(self) -> None:
        if self._pending_initial_render:
            self._finalize_initial_render()
            return
        if self._skip_next_resize_rebuild:
            self._skip_next_resize_rebuild = False
            return
        self._rebuild_rows()

    def on_mount(self) -> None:
        self.watch(self.app, 'theme', self._handle_theme_change, init=False)

    def _handle_theme_change(self, _old_theme: str, _new_theme: str) -> None:
        self._pending_theme_refresh = True
        self.refresh()
        self.call_after_refresh(self._apply_theme_change)

    def _apply_theme_change(self) -> None:
        if not self._pending_theme_refresh:
            return
        self._pending_theme_refresh = False
        if self._pending_initial_render:
            self.refresh()
            return
        if self._work_items:
            self._rebuild_rows()
            return
        self._cache_component_styles()
        self.refresh()

    def _update_selection(self) -> None:
        selected = self.selected_work_item
        self.current_work_item_key = selected.work_item_key if selected else None
        self.refresh()

    def _cache_component_styles(self) -> None:
        self._card_style = self.get_component_rich_style('search-result--card', partial=True)
        self._card_selected_style = self.get_component_rich_style(
            'search-result--card-selected', partial=True
        )
        self._card_loaded_style = self.get_component_rich_style(
            'search-result--card-loaded', partial=True
        )
        self._card_hover_style = self.get_component_rich_style(
            'search-result--card-hover', partial=True
        )

        meta_style = self.get_component_styles('search-result--meta')
        meta_active_style = self.get_component_styles('search-result--meta-active')
        summary_style = self.get_component_styles('search-result--summary')
        summary_strong_style = self.get_component_styles('search-result--summary-strong')
        footer_style = self.get_component_styles('search-result--footer')
        footer_active_style = self.get_component_styles('search-result--footer-active')

        self._meta_style = Style(color=meta_style.color.rich_color)
        self._meta_active_style = Style(color=meta_active_style.color.rich_color)
        self._summary_style = summary_style.partial_rich_style
        self._summary_strong_style = summary_strong_style.partial_rich_style
        self._footer_style = Style(color=footer_style.color.rich_color)
        self._footer_active_style = Style(color=footer_active_style.color.rich_color)

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if not self.is_mounted:
            return
        self._cache_component_styles()
        self.refresh()

    def _wrap_text(self, text: str, width: int) -> list[str]:
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

    def _build_footer_lines(self, priority: str, author: str, width: int) -> list[str]:
        parts = [part for part in (priority, author) if part]
        if not parts:
            return []
        return self._wrap_text(' • '.join(parts), width)

    def _build_rows_for_width(self, card_width: int) -> tuple[list[SearchResultRow], int]:
        content_width = self._card_content_width(card_width)
        rows: list[SearchResultRow] = []
        y = 0

        for index, work_item in enumerate(self._work_items):
            meta = f'[{work_item.work_item_type_name}] {work_item.key}'
            summary = work_item.cleaned_summary(
                CONFIGURATION.get().search_results_truncate_work_item_summary
            )
            meta_lines = self._wrap_text(meta, content_width)
            summary_lines = self._wrap_text(summary, content_width)
            priority = work_item.priority_name or ''
            if work_item.status_name:
                priority = (
                    f'{priority} • {work_item.status_name}' if priority else work_item.status_name
                )
            author = work_item.assignee_display_name or ''
            footer_lines = self._build_footer_lines(priority, author, content_width)
            height = (
                self.CARD_PADDING
                + len(meta_lines)
                + len(summary_lines)
                + len(footer_lines)
                + self.CARD_PADDING
            )

            rows.append(
                SearchResultRow(
                    work_item=work_item,
                    y=y,
                    height=height,
                    meta_lines=meta_lines,
                    summary_lines=summary_lines,
                    footer_lines=footer_lines,
                )
            )
            y += height
            if index < len(self._work_items) - 1:
                y += 1

        return rows, y

    def _build_layout_for_current_geometry(self) -> tuple[int, list[SearchResultRow], int]:
        card_width = self._base_card_width()
        rows, virtual_height = self._build_rows_for_width(card_width)

        if (
            self.scrollbar_size_vertical > 0
            and virtual_height > self._container_height() > 0
            and card_width > self.scrollbar_size_vertical
        ):
            card_width = max(1, card_width - self.scrollbar_size_vertical)
            rows, virtual_height = self._build_rows_for_width(card_width)
        return card_width, rows, virtual_height

    def _estimated_initial_card_width_from_screen(self) -> int:
        if self.screen is None:
            return max(1, self._base_card_width() - 1)

        estimated_pane_width = max(1, (self.screen.size.width * 25) // 100)
        return max(1, estimated_pane_width - 2)

    def _build_initial_layout_for_current_geometry(self) -> tuple[int, list[SearchResultRow], int]:
        card_width = self._estimated_initial_card_width_from_screen()
        rows, virtual_height = self._build_rows_for_width(card_width)
        return card_width, rows, virtual_height

    def _rebuild_rows(self) -> None:
        card_width, rows, virtual_height = self._build_layout_for_current_geometry()

        self._rows = rows
        self._row_starts = [row.y for row in rows]
        self._cache_component_styles()
        self.virtual_size = Size(card_width, virtual_height)
        self._update_vertical_overflow(virtual_height)
        self._scroll_update(self.virtual_size)
        self.refresh()

    def _finalize_initial_render(self) -> None:
        if not self._pending_initial_render:
            return
        if not self._work_items:
            self._pending_initial_render = False
            self._initial_render_attempts = 0
            return

        self.display = True
        self.refresh()
        self.call_after_refresh(self._complete_initial_render)

    def _complete_initial_render(self) -> None:
        if not self._pending_initial_render:
            return
        if not self._work_items:
            self._pending_initial_render = False
            self._initial_render_attempts = 0
            return

        self._initial_render_attempts += 1
        render_width = self._render_width()
        content_width = self.content_region.width
        scrollable_width = self.scrollable_content_region.width
        if self._initial_render_attempts < 4 and (
            content_width <= 0 or scrollable_width <= 0 or render_width <= 1
        ):
            self.refresh()
            self.call_after_refresh(self._complete_initial_render)
            return

        card_width, rows, virtual_height = self._build_initial_layout_for_current_geometry()

        self._rows = rows
        self._row_starts = [row.y for row in rows]
        self._cache_component_styles()
        self.virtual_size = Size(card_width, virtual_height)
        self._update_vertical_overflow(virtual_height)
        self._scroll_update(self.virtual_size)
        self.scroll_to(y=0, animate=False, force=True, immediate=True)
        self._pending_initial_render = False
        self._initial_render_attempts = 0
        self._skip_next_resize_rebuild = True
        self.refresh()
        self._finish_search_state(results_loaded=True)

    def _update_vertical_overflow(self, virtual_height: int) -> None:
        container_height = self._container_height()
        is_overflowing = virtual_height > container_height > 0
        self.set_class(is_overflowing, '-overflowing')

    def _reset_render_state(self) -> None:
        self._rows = []
        self._row_starts = []
        self.virtual_size = Size(max(1, self.size.width), 0)
        self._update_vertical_overflow(0)
        self._scroll_update(self.virtual_size)
        self.scroll_to(y=0, animate=False, force=True, immediate=True)
        self.display = False

    def _finish_search_state(
        self, *, results_loaded: bool, displayed_count: int | None = None
    ) -> None:
        from gojeera.widgets.work_items_container import WorkItemsContainer

        work_items_container = self.parent.parent if self.parent else None
        if isinstance(work_items_container, WorkItemsContainer):
            work_items_container.results_loaded = results_loaded
            if displayed_count is not None:
                work_items_container.displayed_count = displayed_count
            work_items_container.hide_loading()
        cast('MainScreen', self.screen).unified_search_bar.search_in_progress = False

    def _refresh_scrollbars(self) -> None:
        super()._refresh_scrollbars()
        self.show_horizontal_scrollbar = False
        if self._horizontal_scrollbar is not None:
            self.horizontal_scrollbar.display = False

    def _row_index_at_y(self, y: int) -> int | None:
        if not self._rows:
            return None
        index = bisect_right(self._row_starts, y) - 1
        if index < 0:
            return None
        row = self._rows[index]
        return index if y < row.y + row.height else None

    def _scroll_to_index(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        viewport_height = self.container_size.height or self.size.height
        if viewport_height <= 0:
            return
        viewport_top = self.scroll_offset.y
        viewport_bottom = viewport_top + viewport_height
        row_bottom = row.y + row.height

        if row.y < viewport_top:
            self.scroll_to(y=row.y, animate=False, force=True, immediate=True)
        elif row_bottom > viewport_bottom:
            self.scroll_to(
                y=max(0, row_bottom - viewport_height),
                animate=False,
                force=True,
                immediate=True,
            )

    def scroll_to_index(self, index: int) -> None:
        self._scroll_to_index(index)

    def _card_style_for_index(self, index: int):
        if index == self._selected_index:
            return self._card_selected_style
        if self._hovered_index == index:
            return self._card_hover_style
        if self._rows[index].work_item_key == self.loaded_work_item_key:
            return self._card_loaded_style
        return self._card_style

    def _meta_style_for_index(self, index: int):
        return (
            self._meta_active_style
            if index == self._selected_index or self._hovered_index == index
            else self._meta_style
        )

    def _summary_style_for_index(self, index: int):
        if (
            index == self._selected_index
            or self._hovered_index == index
            or self._rows[index].work_item_key == self.loaded_work_item_key
        ):
            return self._summary_strong_style
        return self._summary_style

    def _footer_style_for_index(self, index: int):
        return (
            self._footer_active_style
            if index == self._selected_index or self._hovered_index == index
            else self._footer_style
        )

    def _make_content_strip(self, text: str, text_style, background_style, width: int) -> Strip:
        content_width = self._card_content_width(width)
        content = text
        text_width = cell_len(text)
        if text_width < content_width:
            content = f'{text}{" " * (content_width - text_width)}'
        return Strip(
            [
                Segment(' ' * self.CARD_PADDING, background_style),
                Segment(content, background_style + text_style),
                Segment(' ' * self.CARD_PADDING, background_style),
                Segment(' ', self.rich_style),
            ],
            width,
        )

    def _make_blank_card_strip(self, background_style, width: int) -> Strip:
        content_width = self._card_content_width(width)
        return Strip(
            [
                Segment(' ' * self.CARD_PADDING, background_style),
                Segment(' ' * content_width, background_style),
                Segment(' ' * self.CARD_PADDING, background_style),
                Segment(' ', self.rich_style),
            ],
            width,
        )

    def render_line(self, y: int) -> Strip:
        width = self._render_width()
        base_style = self.rich_style
        if self._pending_initial_render or not self._rows:
            return Strip.blank(width, base_style)
        document_y = y + self.scroll_offset.y
        row_index = self._row_index_at_y(document_y)
        if row_index is None:
            return Strip.blank(width, base_style)

        row = self._rows[row_index]
        local_y = document_y - row.y
        background_style = self._card_style_for_index(row_index)
        content_strip: Strip

        if local_y < self.CARD_PADDING:
            return self._make_blank_card_strip(background_style, width)

        local_y -= self.CARD_PADDING

        meta_end = len(row.meta_lines)
        if local_y < meta_end:
            content_strip = self._make_content_strip(
                row.meta_lines[local_y],
                self._meta_style_for_index(row_index),
                background_style,
                width,
            )
        else:
            summary_start = meta_end
            summary_end = summary_start + len(row.summary_lines)
            if summary_start <= local_y < summary_end:
                content_strip = self._make_content_strip(
                    row.summary_lines[local_y - summary_start],
                    self._summary_style_for_index(row_index),
                    background_style,
                    width,
                )
            else:
                footer_start = summary_end
                footer_end = footer_start + len(row.footer_lines)
                if footer_start <= local_y < footer_end:
                    content_strip = self._make_content_strip(
                        row.footer_lines[local_y - footer_start],
                        self._footer_style_for_index(row_index),
                        background_style,
                        width,
                    )
                else:
                    content_strip = self._make_blank_card_strip(background_style, width)

        return content_strip

    def action_cursor_down(self) -> None:
        if self._rows:
            self._selected_index = min(self._selected_index + 1, len(self._rows) - 1)
            self._update_selection()
            self._scroll_to_index(self._selected_index)

    def action_cursor_up(self) -> None:
        if self._rows:
            self._selected_index = max(self._selected_index - 1, 0)
            self._update_selection()
            self._scroll_to_index(self._selected_index)

    def action_first_item(self) -> None:
        if self._rows:
            self._selected_index = 0
            self._update_selection()
            self._scroll_to_index(self._selected_index)

    def action_last_item(self) -> None:
        if self._rows:
            self._selected_index = len(self._rows) - 1
            self._update_selection()
            self._scroll_to_index(self._selected_index)

    def reset_selection(self) -> None:
        self._selected_index = 0
        self._update_selection()

    async def clear_results(self) -> None:
        self._work_items = []
        self._reset_render_state()
        self.token_by_page = {}
        self.page = 1
        self.pending_page = None
        self.total_pages = 1
        self.current_work_item_key = None
        self.loaded_work_item_key = None
        self._selected_index = 0
        self._hovered_index = None
        self._initial_render_attempts = 0
        self._skip_next_resize_rebuild = False
        self._finish_search_state(results_loaded=False)
        self.refresh()

    def prepare_for_search(self) -> None:
        self._reset_render_state()
        self._pending_initial_render = True
        self._initial_render_attempts = 0
        self._skip_next_resize_rebuild = False
        self.refresh()

    def scroll_to_top(self, animate: bool = False) -> None:
        self.scroll_home(animate=animate)

    def reset_viewport(self) -> None:
        self._selected_index = 0
        self._hovered_index = None
        self.current_work_item_key = self._work_items[0].key if self._work_items else None
        self.scroll_to(y=0, animate=False, force=True, immediate=True)
        self.refresh()

    async def action_select_work_item(self) -> None:
        if selected := self.selected_work_item:
            await self._select_work_item(selected.work_item_key)
        else:
            return

    async def watch_work_item_search_results(
        self, response: JiraWorkItemSearchResponse | None = None
    ) -> None:
        from gojeera.widgets.work_items_container import WorkItemsContainer

        if response is None:
            with self.app.batch_update():
                self._work_items = []
                self._reset_render_state()
                self._finish_search_state(results_loaded=False, displayed_count=0)
            return

        if not response.work_items:
            with self.app.batch_update():
                self._work_items = []
                self._reset_render_state()
                self._finish_search_state(results_loaded=False, displayed_count=0)
            return

        with self.app.batch_update():
            if response.next_page_token:
                next_page = self.page + 1
                self.token_by_page[next_page] = response.next_page_token

            self._work_items = list(response.work_items)
            self._rows = []
            self._row_starts = []
            self.virtual_size = Size(max(1, self.size.width), 0)
            self._update_vertical_overflow(0)
            self._scroll_update(self.virtual_size)
            self.scroll_to(y=0, animate=False, force=True, immediate=True)
            self._selected_index = 0
            self._hovered_index = None
            self.current_work_item_key = self._work_items[0].key if self._work_items else None
            self.display = False
            self._pending_initial_render = True
            self.call_after_refresh(self._finalize_initial_render)

            if self.parent and isinstance(self.parent.parent, WorkItemsContainer):
                self.parent.parent.displayed_count = len(self._work_items)

    def mark_loaded_work_item(self, work_item_key: str) -> None:
        self.loaded_work_item_key = work_item_key
        self.refresh()

    def clear_loaded_work_item(self) -> None:
        self.loaded_work_item_key = None
        self.refresh()

    async def update_work_item_in_list(self, updated_work_item: JiraWorkItem) -> None:
        for index, work_item in enumerate(self._work_items):
            if work_item.key == updated_work_item.key:
                self._work_items[index] = updated_work_item
                self._rebuild_rows()
                break

    async def on_click(self, event: events.Click) -> None:
        clicked_y = event.y + self.scroll_offset.y
        index = self._row_index_at_y(clicked_y)
        if index is None:
            return
        self._selected_index = index
        self._update_selection()
        self._scroll_to_index(index)
        await self._select_work_item(self._rows[index].work_item_key)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        hovered_y = event.y + self.scroll_offset.y
        hovered_index = self._row_index_at_y(hovered_y)
        if hovered_index != self._hovered_index:
            self._hovered_index = hovered_index
            self.refresh()

    def on_leave(self, _: events.Leave) -> None:
        if self._hovered_index is not None:
            self._hovered_index = None
            self.refresh()

    async def _select_work_item(self, work_item_key: str) -> None:
        from gojeera.app import MainScreen

        screen = cast(MainScreen, self.screen)
        if (
            screen.current_loaded_work_item_key == work_item_key
            or screen._active_work_item_load_key == work_item_key
        ):
            return

        self.current_work_item_key = work_item_key

        self.mark_loaded_work_item(work_item_key)

        screen.run_worker(screen.fetch_work_items(work_item_key), exclusive=True, group='work-item')

    def action_open_work_item_in_browser(self) -> None:
        if self.current_work_item_key:
            if url := build_external_url_for_work_item(
                self.current_work_item_key,
                cast('JiraApp', self.app),
            ):
                self.notify('Opening Work Item in the browser...', title='Search Results')
                self.app.open_url(url)

    def action_clone_work_item(self) -> None:
        if not self.current_work_item_key:
            self.notify('No work item selected', severity='warning', title='Search Results')
            return

        from gojeera.app import MainScreen

        screen = cast(MainScreen, self.screen)
        self.run_worker(screen.clone_work_item(self.current_work_item_key))

    def action_copy_work_item_key(self) -> None:
        if self.current_work_item_key:
            self.app.copy_to_clipboard(self.current_work_item_key)
            self.notify('Key copied to clipboard', title=self.current_work_item_key)

    def action_copy_work_item_url(self) -> None:
        if self.current_work_item_key:
            if url := build_external_url_for_work_item(
                self.current_work_item_key,
                cast('JiraApp', self.app),
            ):
                self.app.copy_to_clipboard(url)
                self.notify('URL copied to clipboard', title=self.current_work_item_key)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        from gojeera.widgets.work_items_container import WorkItemsContainer

        work_items_container = self.parent.parent if self.parent else None
        is_loading = isinstance(work_items_container, WorkItemsContainer) and (
            work_items_container.is_loading
        )

        if is_loading and action in {'previous_work_items_page', 'next_work_items_page'}:
            return False

        if action == 'previous_work_items_page':
            return self.page > 1
        if action == 'next_work_items_page':
            if self.token_by_page.get(self.page + 1):
                return True
            return self.page < self.total_pages
        return True

    def action_previous_work_items_page(self):
        if self.page > 1:
            requested_page = self.page - 1
            next_page_token = self.token_by_page.get(requested_page)
            self.pending_page = requested_page

            self.scroll_to_top(animate=False)

            from gojeera.app import MainScreen

            screen = cast(MainScreen, self.screen)
            screen.begin_search_request(page_number=requested_page)
            self.run_worker(
                screen.search_work_items(
                    next_page_token,
                    page=requested_page,
                    use_active_search=True,
                ),
                exclusive=True,
                group='search',
            )
            self.refresh_bindings()

    def action_next_work_items_page(self):
        requested_page = self.page + 1
        next_page_token = self.token_by_page.get(requested_page)
        self.pending_page = requested_page

        self.scroll_to_top(animate=False)

        from gojeera.app import MainScreen

        screen = cast(MainScreen, self.screen)
        screen.begin_search_request(page_number=requested_page)
        self.run_worker(
            screen.search_work_items(
                next_page_token,
                page=requested_page,
                use_active_search=True,
            ),
            exclusive=True,
            group='search',
        )
        self.refresh_bindings()
