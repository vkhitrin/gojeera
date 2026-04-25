from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.geometry import Size
from textual.reactive import Reactive, reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip

from gojeera.internal.models.work_items import JiraWorkItem
from gojeera.utils.ui.scroll_geometry import (
    build_scrollbar_aware_layout,
    wrap_text_cell_aware,
)
from gojeera.widgets.layout.card_scroll_view_mixin import CardScrollViewMixin


@dataclass(slots=True)
class PreviewFieldRow:
    label: str
    value_lines: list[str]
    y: int
    height: int


class WorkItemFieldsPreview(CardScrollViewMixin, ScrollView, can_focus=False):
    COMPONENT_CLASSES = {
        'fields-preview--label',
        'fields-preview--value',
    }

    DEFAULT_CSS = """
    WorkItemFieldsPreview {
        background: $surface;
        overflow-x: hidden;
        overflow-y: scroll;
        scrollbar-gutter: stable;
        scrollbar-size-horizontal: 0;
        scrollbar-size-vertical: 1;
        padding: 0 0 1 1;
    }

    WorkItemFieldsPreview > .fields-preview--label {
        color: $text-muted;
        text-style: bold;
    }

    WorkItemFieldsPreview > .fields-preview--value {
        color: $text;
    }
    """

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)

    _WIDE_LAYOUT_THRESHOLD = 150
    _LABEL_MIN_WIDTH = 15
    _LABEL_MAX_WIDTH = 30
    _LABEL_PADDING_RIGHT = 2

    def __init__(self) -> None:
        super().__init__(id='work-item-fields-preview')
        self.can_focus = False
        self._rows: list[PreviewFieldRow] = []
        self._label_style: Style | None = None
        self._value_style: Style | None = None
        self._field_names_by_id: dict[str, str] = {}
        self._pending_initial_render = False
        self._initial_render_attempts = 0
        self._skip_next_resize_rebuild = False
        self.display = False

    def _cache_component_styles(self) -> None:
        self._label_style = self.get_component_styles('fields-preview--label').partial_rich_style
        self._value_style = self.get_component_styles('fields-preview--value').partial_rich_style

    def set_field_names(self, field_names_by_id: dict[str, str]) -> None:
        self._field_names_by_id = dict(field_names_by_id)
        if self.work_item is not None:
            self._rebuild_rows()

    def watch_work_item(self, work_item: JiraWorkItem | None) -> None:
        if work_item is None:
            self._rows = []
            self.virtual_size = Size(max(1, self.size.width), 0)
            self._update_vertical_overflow_class(0)
            self._scroll_update(self.virtual_size)
            self.scroll_to(y=0, animate=False, force=True, immediate=True)
            self._pending_initial_render = False
            self._initial_render_attempts = 0
            self._skip_next_resize_rebuild = False
            self.display = False
            self.refresh()
            return

        self._pending_initial_render = True
        self._initial_render_attempts = 0
        self._skip_next_resize_rebuild = False
        self.display = False
        self.call_after_refresh(self._complete_initial_render)

    def set_work_item(
        self,
        work_item: JiraWorkItem | None,
        field_names_by_id: dict[str, str] | None = None,
    ) -> None:
        if field_names_by_id is not None:
            self._field_names_by_id = dict(field_names_by_id)
        self.work_item = work_item

    def _is_narrow_layout(self, width: int) -> bool:
        return width < self._WIDE_LAYOUT_THRESHOLD

    def _label_width(self, width: int) -> int:
        width = max(1, width)
        return max(
            self._LABEL_MIN_WIDTH,
            min(self._LABEL_MAX_WIDTH, int(width * 0.2)),
        )

    def _wrap_text(self, text: str, width: int) -> list[str]:
        return wrap_text_cell_aware(text, width)

    def _stringify_value(self, value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            values = [self._stringify_value(item) for item in value]
            return ', '.join(item for item in values if item)
        if isinstance(value, dict):
            for key in ('displayName', 'name', 'value'):
                field_value = value.get(key)
                if field_value:
                    return str(field_value)
            if value.get('accountId'):
                return str(value.get('displayName') or value['accountId'])
        return str(value)

    def _normalized_field_label(self, field_id: str) -> str:
        return ' '.join(str(self._field_names_by_id.get(field_id, field_id)).split())

    def _append_dynamic_field_pairs(
        self,
        pairs: list[tuple[str, str]],
        fields: dict[str, Any],
        *,
        skipped_ids: set[str],
        blocked_ids: set[str] | None = None,
        require_custom_field_prefix: bool = False,
    ) -> None:
        for field_id, field_value in fields.items():
            if field_id in skipped_ids or field_value is None:
                continue
            if blocked_ids is not None and field_id in blocked_ids:
                continue
            if require_custom_field_prefix and not str(field_id).startswith('customfield_'):
                continue
            label = self._normalized_field_label(field_id)
            if not label:
                continue
            string_value = self._stringify_value(field_value).strip()
            if string_value:
                pairs.append((label, string_value))

    def _static_pairs(self, work_item: JiraWorkItem) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []

        def add(label: str, value: Any) -> None:
            string_value = self._stringify_value(value).strip()
            if string_value:
                pairs.append((label, string_value))

        add('Status', work_item.status.name if work_item.status else None)
        add('Resolution', work_item.resolution)
        add('Priority', work_item.priority_name)
        add('Assignee', work_item.assignee_display_name)
        add('Reporter', work_item.reporter.display_name if work_item.reporter else None)
        add('Labels', getattr(work_item, 'labels', None))
        add('Components', [component.name for component in (work_item.components or [])])

        additional_fields = work_item.additional_fields or {}
        add(
            'Affects Versions',
            [version.get('name') for version in additional_fields.get('versions', [])],
        )
        add(
            'Fix Versions',
            [version.get('name') for version in additional_fields.get('fixVersions', [])],
        )
        add('Story Points', work_item.get_custom_field_value('customfield_10106'))

        sprint_value = work_item.get_custom_field_value('customfield_10101')
        if isinstance(sprint_value, list):
            add('Sprint', [sprint.get('name') or sprint.get('value') for sprint in sprint_value])
        else:
            add('Sprint', sprint_value)

        return pairs

    def _dynamic_pairs(self, work_item: JiraWorkItem) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        skipped_ids = {
            'status',
            'resolution',
            'priority',
            'assignee',
            'reporter',
            'labels',
            'components',
            'versions',
            'fixVersions',
            'duedate',
            'customfield_10106',
            'customfield_10101',
        }

        custom_fields = work_item.custom_fields or {}
        self._append_dynamic_field_pairs(
            pairs,
            custom_fields,
            skipped_ids=skipped_ids,
        )

        self._append_dynamic_field_pairs(
            pairs,
            work_item.additional_fields or {},
            skipped_ids=skipped_ids,
            blocked_ids=set(custom_fields),
            require_custom_field_prefix=True,
        )

        return pairs

    def _date_pairs(self, work_item: JiraWorkItem) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []

        def add(label: str, value: Any) -> None:
            string_value = self._stringify_value(value).strip()
            if string_value:
                pairs.append((label, string_value))

        add('Due Date', work_item.display_due_date)
        add('Updated', work_item.updated.strftime('%Y-%m-%d %H:%M') if work_item.updated else None)
        add('Created', work_item.created.strftime('%Y-%m-%d %H:%M') if work_item.created else None)
        add(
            'Resolution Date',
            work_item.resolution_date.strftime('%Y-%m-%d %H:%M')
            if work_item.resolution_date
            else None,
        )
        return pairs

    def _preview_pairs(self, work_item: JiraWorkItem) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        pairs.extend(self._static_pairs(work_item))
        pairs.extend(self._dynamic_pairs(work_item))
        pairs.extend(self._date_pairs(work_item))
        return pairs

    def _row_height(self, _label: str, value: str, width: int) -> tuple[list[str], int]:
        narrow = self._is_narrow_layout(width)
        if narrow:
            value_width = width
            value_lines = self._wrap_text(value, value_width)
            return value_lines, 1 + len(value_lines)

        label_width = self._label_width(width)
        value_width = max(1, width - label_width - self._LABEL_PADDING_RIGHT)
        value_lines = self._wrap_text(value, value_width)
        return value_lines, max(1, len(value_lines))

    def _build_rows_for_width(
        self,
        work_item: JiraWorkItem,
        width: int,
    ) -> tuple[list[PreviewFieldRow], int]:
        pairs = self._preview_pairs(work_item)
        rows: list[PreviewFieldRow] = []
        y = 0

        for index, (label, value) in enumerate(pairs):
            value_lines, height = self._row_height(label, value, width)
            if index > 0:
                y += 1
            rows.append(PreviewFieldRow(label=label, value_lines=value_lines, y=y, height=height))
            y += height

        return rows, y

    def _build_layout_for_current_geometry(self) -> tuple[int, list[PreviewFieldRow], int]:
        work_item = self.work_item
        if work_item is None:
            return max(1, self._render_width()), [], 0

        return build_scrollbar_aware_layout(
            base_width=self._render_width(),
            container_height=self._container_height(),
            scrollbar_size_vertical=self.scrollbar_size_vertical,
            reserve_vertical_scrollbar=True,
            build_rows_for_width=lambda width: self._build_rows_for_width(work_item, width),
        )

    def _estimated_initial_width(self) -> int:
        width = self._render_width()
        if width > 1:
            return width

        if self.parent is not None:
            parent_width = self._parent_content_width()
            if parent_width > 1:
                return parent_width

        if self.screen is not None:
            estimated_pane_width = max(1, self.screen.size.width // 2)
            return estimated_pane_width

    def _build_initial_layout_for_current_geometry(
        self,
        work_item: JiraWorkItem,
    ) -> tuple[int, list[PreviewFieldRow], int]:
        return build_scrollbar_aware_layout(
            base_width=self._estimated_initial_width(),
            container_height=self._container_height(),
            scrollbar_size_vertical=self.styles.scrollbar_size_vertical or 1,
            reserve_vertical_scrollbar=True,
            build_rows_for_width=lambda width: self._build_rows_for_width(work_item, width),
        )

    def _apply_layout(
        self,
        width: int,
        rows: list[PreviewFieldRow],
        virtual_height: int,
        *,
        force_scroll_to_top: bool = False,
    ) -> None:
        self._rows = rows
        self._cache_component_styles()
        self.virtual_size = Size(width, virtual_height)
        self._update_vertical_overflow_class(virtual_height)
        self._scroll_update(self.virtual_size)
        if force_scroll_to_top or virtual_height <= self._container_height():
            self.scroll_to(y=0, animate=False, force=True, immediate=True)

    def _complete_initial_render(self) -> None:
        if not self._pending_initial_render:
            return
        work_item = self.work_item
        if work_item is None:
            self._pending_initial_render = False
            self._initial_render_attempts = 0
            return

        if not self._continue_initial_render(
            has_content=True,
            retry_callback=self._complete_initial_render,
        ):
            return

        width, rows, virtual_height = self._build_initial_layout_for_current_geometry(work_item)
        self._finalize_initial_layout(
            width,
            rows,
            virtual_height,
        )

    def _refresh_scrollbars(self) -> None:
        super()._refresh_scrollbars()
        self.show_horizontal_scrollbar = False

    def _rebuild_rows(self) -> None:
        if self.work_item is None:
            return

        width, rows, virtual_height = self._build_layout_for_current_geometry()
        self._apply_layout(
            width,
            rows,
            virtual_height,
            force_scroll_to_top=False,
        )
        self.refresh()

    def _ellipsize(self, text: str, width: int) -> str:
        width = max(1, width)
        if cell_len(text) <= width:
            return text
        if width == 1:
            return text[:1]

        result = ''
        for char in text:
            candidate = result + char
            if cell_len(candidate) >= width:
                break
            result = candidate
        return f'{result}.'

    def render_line(self, y: int) -> Strip:
        width = self._render_width()
        if not self._rows:
            return Strip.blank(width, self.rich_style)

        document_y = y + self.scroll_offset.y
        for row in self._rows:
            if not (row.y <= document_y < row.y + row.height):
                continue

            local_y = document_y - row.y
            label_style = self._label_style or self.rich_style
            value_style = self._value_style or self.rich_style
            narrow = self._is_narrow_layout(width)

            if narrow:
                if local_y == 0:
                    label_text = self._ellipsize(row.label, width)
                    label_width = cell_len(label_text)
                    segments = [Segment(label_text, label_style)]
                    if label_width < width:
                        segments.append(Segment(' ' * (width - label_width), self.rich_style))
                    return Strip(segments)

                value_line = (
                    row.value_lines[local_y - 1] if local_y - 1 < len(row.value_lines) else ''
                )
                value_width = cell_len(value_line)
                segments = [Segment(value_line, value_style)]
                if value_width < width:
                    segments.append(Segment(' ' * (width - value_width), self.rich_style))
                return Strip(segments)

            label_width = min(self._label_width(width), max(1, width - 1))
            label_text = self._ellipsize(row.label, label_width)
            value_line = row.value_lines[local_y] if local_y < len(row.value_lines) else ''
            label_cell_width = cell_len(label_text)
            value_cell_width = cell_len(value_line)

            segments = []
            if local_y == 0:
                segments.append(Segment(label_text, label_style))
                if label_cell_width < label_width:
                    segments.append(
                        Segment(' ' * (label_width - label_cell_width), self.rich_style)
                    )
            else:
                segments.append(Segment(' ' * label_width, self.rich_style))

            segments.append(Segment(' ' * self._LABEL_PADDING_RIGHT, self.rich_style))
            segments.append(Segment(value_line, value_style))
            remaining_width = width - label_width - self._LABEL_PADDING_RIGHT - value_cell_width
            if remaining_width > 0:
                segments.append(Segment(' ' * remaining_width, self.rich_style))
            return Strip(segments)

        return Strip.blank(width, self.rich_style)
