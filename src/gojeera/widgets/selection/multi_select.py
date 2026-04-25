import logging
import textwrap
from typing import Any, Sequence, cast

from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual import events, on
from textual.app import RenderResult
from textual.css.query import NoMatches
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input
from textual_autocomplete._autocomplete import AutoCompleteList
from textual_tags import Tag, TagAutoComplete, TagInput, Tags

from gojeera.utils.data.fields import BaseField, FieldMode, require_create_mode, require_update_mode
from gojeera.widgets.selection.dropdown_positioning import constrain_dropdown_offset

logger = logging.getLogger('gojeera')


def extract_sprint_entries(value: Any) -> list[tuple[str, str]]:
    """Normalize Jira sprint field values into display-name / id pairs."""

    if not value:
        return []

    if isinstance(value, list):
        entries: list[tuple[str, str]] = []
        for item in value:
            entries.extend(extract_sprint_entries(item))
        return entries

    if isinstance(value, dict):
        sprint_id = value.get('id')
        if sprint_id is None:
            return []
        sprint_name = value.get('name') or value.get('value') or str(sprint_id)
        return [(str(sprint_name), str(sprint_id))]

    sprint_id = str(value).strip()
    if not sprint_id:
        return []
    return [(sprint_id, sprint_id)]


def extract_sprint_ids(value: Any) -> list[str]:
    return [sprint_id for _name, sprint_id in extract_sprint_entries(value)]


class ExtendedTag(Tag):
    """Tag that wraps long content across multiple lines."""

    COMPONENT_CLASSES = {
        'extended-tag--chip',
        'extended-tag--close',
        'extended-tag--close-hover',
    }

    DEFAULT_CSS = """
    ExtendedTag {
        margin: 0 1 0 0;
        padding: 0 0;
        width: auto;
        height: auto;
        min-height: 1;
        color: $text-primary;
        background: transparent;

        &:hover {
            background: transparent;
            tint: 0%;
        }

        &:focus {
            background: transparent;
            tint: 0%;
        }

        & > .extended-tag--chip {
            color: $text-primary;
            background: $primary-muted;
        }

        & > .extended-tag--close {
            color: $text-primary;
            background: $primary-muted;
        }

        & > .extended-tag--close-hover {
            color: red;
            background: $primary-muted;
        }

        &:hover > .extended-tag--chip,
        &:focus > .extended-tag--chip,
        &:hover > .extended-tag--close,
        &:focus > .extended-tag--close,
        &:hover > .extended-tag--close-hover,
        &:focus > .extended-tag--close-hover {
            background: $primary-darken-2;
        }

        &:light {
            & > .extended-tag--close-hover {
                background: $primary;
            }

            &:hover > .extended-tag--chip,
            &:focus > .extended-tag--chip,
            &:hover > .extended-tag--close,
            &:focus > .extended-tag--close {
                background: $primary-muted;
            }

            &:hover > .extended-tag--close-hover,
            &:focus > .extended-tag--close-hover {
                background: $primary;
            }
        }
    }
    """

    def _get_payload_lines(self, width: int) -> list[str]:
        available_width = max(1, width - 2)
        suffix = ' x' if self.show_x else ' '
        content_width = max(1, available_width - len(suffix))

        wrapped_lines = textwrap.wrap(
            str(self.value),
            width=content_width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or ['']

        wrapped_lines[-1] = f'{wrapped_lines[-1]}{suffix}'
        return wrapped_lines

    def get_content_width(self, container: Size, viewport: Size) -> int:
        del viewport
        natural_width = len(str(self.value)) + 2 + (2 if self.show_x else 1)
        return max(1, min(natural_width, container.width))

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        del container, viewport
        if not width:
            return 0
        return len(self._get_payload_lines(width))

    def _render_width(self) -> int:
        return self.content_region.width or self.size.width or max(len(str(self.value)) + 4, 1)

    def _mouse_over_x(self) -> bool:
        if not self.show_x or not self.mouse_hover or self.region.height < 1:
            return False

        payload_lines = self._get_payload_lines(self._render_width())
        last_line = payload_lines[-1]
        if not last_line.endswith('x'):
            return False

        x_position = self.region.x + len(last_line)
        y_position = self.region.y + len(payload_lines) - 1
        return self.app.mouse_position.y == y_position and self.app.mouse_position.x == x_position

    def render(self) -> RenderResult:
        payload_lines = self._get_payload_lines(self._render_width())
        chip_styles = self.get_component_styles('extended-tag--chip')
        close_styles = self.get_component_styles(
            'extended-tag--close-hover' if self._mouse_over_x() else 'extended-tag--close'
        )
        chip_rich_style = chip_styles.rich_style
        close_rich_style = close_styles.rich_style
        if self.mouse_hover and not self.app.current_theme.dark:
            hover_text_color = self.colors[0].hex
            chip_rich_style += RichStyle(color=hover_text_color)
            close_rich_style += RichStyle(color=hover_text_color)
        text = Text()

        for index, line in enumerate(payload_lines):
            if index:
                text.append('\n')

            text.append(' ', style=chip_styles.rich_style)

            if self.show_x and index == len(payload_lines) - 1 and line.endswith('x'):
                text.append(line[:-1], style=chip_rich_style)
                text.append('x', style=close_rich_style)
            else:
                text.append(line, style=chip_rich_style)

            text.append(' ', style=chip_rich_style)

        return text


class MultiSelectTagAutoComplete(TagAutoComplete):
    """Keep autocomplete open long enough for mouse option selection."""

    class VisibilityChanged(Message):
        def __init__(self, autocomplete: 'MultiSelectTagAutoComplete', visible: bool) -> None:
            self.autocomplete = autocomplete
            self.visible = visible
            super().__init__()

    def _safe_option_list(self) -> AutoCompleteList | None:
        try:
            return self.option_list
        except NoMatches:
            return None

    def _hide_if_target_unfocused(self) -> None:
        option_list = self._safe_option_list()
        if option_list is None:
            return
        if (
            not self.target.has_focus
            and not self.has_focus
            and not option_list.has_focus
            and not option_list.mouse_hover
        ):
            self.action_hide()

    def _handle_focus_change(self, has_focus: bool) -> None:
        if has_focus:
            self.action_hide()
        else:
            self.call_after_refresh(self._hide_if_target_unfocused)

    def _listen_to_messages(self, event: events.Event) -> None:
        parent = self.parent
        if (
            isinstance(event, events.Key)
            and event.key == 'enter'
            and not self.display
            and parent is not None
            and not getattr(parent, 'allow_new_tags', False)
        ):
            self._handle_target_update()
            option_list = self._safe_option_list()
            if option_list and option_list.option_count:
                event.prevent_default()
                event.stop()
                self.action_show()
                option_list.highlighted = 0
            return

        super()._listen_to_messages(event)

    def _rebuild_options(self, target_state, search_string: str) -> None:
        super()._rebuild_options(target_state, search_string)
        option_list = self._safe_option_list()
        if option_list is None:
            return
        option_count = max(1, min(option_list.option_count, 12))
        self.styles.height = option_count
        option_list.styles.height = option_count

    def _align_to_target(self) -> None:
        parent = self.parent
        if parent is None:
            super()._align_to_target()
            return
        parent_widget = cast(Widget, parent)

        _, y = self.target.cursor_screen_offset
        dropdown = self._safe_option_list()
        if dropdown is None:
            return
        parent_width = max(1, parent_widget.region.width)
        dropdown.styles.width = parent_width
        width, height = dropdown.outer_size
        width = max(1, width)
        height = max(1, height)

        self.absolute_offset = constrain_dropdown_offset(
            x=parent_widget.region.x,
            y=y + 1,
            width=width,
            height=height,
            container_region=self.screen.scrollable_content_region,
        )

    def action_show(self) -> None:
        super().action_show()
        self.post_message(self.VisibilityChanged(self, True))

    def action_hide(self) -> None:
        super().action_hide()
        self.post_message(self.VisibilityChanged(self, False))


class MultiSelectTagInput(TagInput):
    """Reopen autocomplete suggestions on mouse click."""

    expanded = reactive(False)

    def _on_focus(self, event: events.Focus) -> None:
        super()._on_focus(event)
        parent = self.parent
        if parent is not None:
            parent.query_one(TagAutoComplete).action_hide()

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if y != 0:
            return strip

        if self.has_class('-hide-arrow'):
            return strip

        arrow_text = ' ▲' if self.expanded else ' ▼'
        arrow_style = self.rich_style + self.get_component_rich_style('input--placeholder')
        arrow_strip = Strip([Segment(arrow_text, arrow_style)], len(arrow_text))
        right_padding = Strip.blank(1, self.rich_style)
        content_width = max(
            1, self.size.width - arrow_strip.cell_length - right_padding.cell_length
        )
        content_strip = strip.crop_extend(0, content_width, self.rich_style)
        return Strip.join([content_strip, arrow_strip, right_padding]).crop_extend(
            0, self.size.width, self.rich_style
        )

    def on_click(self, _event: events.Click) -> None:
        self.focus()
        parent = self.parent
        if isinstance(parent, MultiSelect):
            parent._refresh_autocomplete_visibility()


class SafeSet(set[str]):
    """
    A set that doesn't raise KeyError when removing nonexistent items.
    """

    def remove(self, element: str) -> None:
        self.discard(element)


class MultiSelect(Tags, BaseField):
    """
    Multi-select widget using textual-tags for array fields with known options.

    This widget handles array fields (like components) that allow multiple selections
    from a predefined set of options. Uses textual-tags for a visual tag interface
    where all options are known in advance.
    """

    can_focus = True

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        options: list[tuple[str, str]],
        title: str | None = None,
        required: bool = False,
        initial_value: list[str] | None = None,
        original_value: list[str] | None = None,
        field_supports_update: bool = True,
        allow_new_tags: bool = False,
    ):
        self.mode = mode
        self.field_id = field_id
        self.jira_field_key = field_id
        self.title = title or field_id
        self._supports_update = field_supports_update if mode == FieldMode.UPDATE else True
        self._suspend_tag_selection_messages = False
        self._suspend_change_events = False
        self._is_hydrating = False
        self._pending_options_state: dict[str, Any] | None = None

        self._id_to_name = {value_id: name for name, value_id in options}
        self._name_to_id = dict(options)

        if mode == FieldMode.UPDATE and original_value:
            self._original_value = list(original_value)
        else:
            self._original_value = None

        selected_tag_names = []
        if mode == FieldMode.UPDATE and original_value:
            selected_tag_names = [
                self._id_to_name.get(value_id, value_id) for value_id in original_value
            ]
        elif mode == FieldMode.CREATE and initial_value:
            selected_tag_names = [
                self._id_to_name.get(value_id, value_id) for value_id in initial_value
            ]

        self._all_option_names = [name for name, _ in options]

        Tags.__init__(
            self,
            tag_values=self._all_option_names,
            show_x=True,
            start_with_tags_selected=False,
            allow_new_tags=allow_new_tags,
            id=field_id,
            disabled=mode == FieldMode.UPDATE and not field_supports_update,
        )

        # textual-tags uses mutable reactive defaults; set per-instance storage directly,
        # including the empty-set case where reactive equality would otherwise skip assignment.
        self._reactive_tag_values = set(self._all_option_names)
        self._reactive_selected_tags = SafeSet()

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
        )

        self._initially_selected_tags = selected_tag_names

        if self.mode == FieldMode.CREATE:
            self.add_class('surface-input-tags')

        if required:
            self.add_class('required')

    def compose(self):
        """Override compose."""

        tag_input = MultiSelectTagInput(id=f'{self.field_id}_input_tag')
        yield tag_input

        tag_autocomplete = MultiSelectTagAutoComplete(
            target=tag_input,
            candidates=self.update_autocomplete_candidates,
        )
        yield tag_autocomplete

    def _refresh_autocomplete_visibility(self) -> None:
        autocomplete = self.query_one(TagAutoComplete)
        autocomplete._handle_target_update()
        if autocomplete.option_list.option_count:
            autocomplete.action_show()
        else:
            autocomplete.action_hide()

    def on_click(self, event: events.Click) -> None:
        if self.disabled:
            return

        self.tag_input_widget.focus()
        self._refresh_autocomplete_visibility()

        event.stop()

    @property
    def multi_select_tag_input(self) -> MultiSelectTagInput:
        return self.query_one(MultiSelectTagInput)

    @property
    def tag_input_widget(self) -> TagInput:
        return self.query_one(TagInput)

    def _has_remaining_options(self) -> bool:
        return any(option not in self.selected_tags for option in self._all_option_names)

    def _sync_dropdown_arrow_visibility(self) -> None:
        self.multi_select_tag_input.set_class(not self._has_remaining_options(), '-hide-arrow')

    def on_multi_select_tag_auto_complete_visibility_changed(
        self, event: MultiSelectTagAutoComplete.VisibilityChanged
    ) -> None:
        self.multi_select_tag_input.expanded = event.visible

    @on(TagAutoComplete.Applied)
    async def on_tag_auto_complete_applied(self, event: TagAutoComplete.Applied) -> None:
        await event.autocomplete.target.action_submit()

    def _ensure_safe_selected_tags(self) -> SafeSet:
        """Keep selected_tags on the non-throwing set implementation."""

        if not isinstance(self.selected_tags, SafeSet):
            self.selected_tags = SafeSet(self.selected_tags)
        return cast(SafeSet, self.selected_tags)

    async def add_new_tag(self, value: str) -> None:
        """
        Override add_new_tag to fix data_bind issue with inheritance.

        The textual-tags library uses Tag(value).data_bind(Tags.show_x) which fails
        when Tags is inherited by MultiSelect. We override to avoid data_bind entirely.

        CRITICAL: After adding the tag, we schedule validation to run on the next cycle.
        This ensures the parent screen revalidates after the tag is fully added.
        """

        tag = ExtendedTag(value)
        tag.show_x = self.show_x
        await self.mount(tag, before=f'#{self.field_id}_input_tag')
        self._ensure_safe_selected_tags().add(value)

        self.mutate_reactive(Tags.selected_tags)
        self._sync_dropdown_arrow_visibility()

        if value not in self.tag_values:
            self.tag_values.add(value)

        if not self._suspend_tag_selection_messages:

            def trigger_validation():
                try:
                    self.post_message(Tag.Selected(tag))
                except Exception:
                    pass

            self.call_later(trigger_validation)

    def _on_tag_removed(self, event: Tag.Removed):
        """
        Override parent's _on_tag_removed to use discard instead of remove.

        The parent class uses .remove() which raises KeyError if the tag doesn't exist.
        This can happen due to race conditions or state desync. We use discard() instead
        which silently ignores missing tags.

        NOTE: We don't stop() the event because the parent screen needs to receive it
        for validation updates. The event will bubble up to the parent screen's handler.
        """

        tag_value = str(event.tag.value) if event.tag.value is not None else ''
        self._ensure_safe_selected_tags().discard(tag_value)
        self.mutate_reactive(Tags.selected_tags)
        self._sync_dropdown_arrow_visibility()
        if self._suspend_change_events:
            event.stop()

    async def watch_selected_tags(self):
        """
        Override parent's watch_selected_tags to handle widget detachment gracefully.

        The parent class tries to query TagInput which may not exist if the widget
        has been removed from the DOM during navigation. We wrap this in a try-except
        to prevent NoMatches errors during cleanup.
        """
        try:
            if self.is_attached:
                await super().watch_selected_tags()
        except Exception:
            pass

    async def on_mount(self) -> None:
        """Mount handler - manually mount initially selected tags."""

        await super().on_mount()

        def set_placeholder_text():
            try:
                self.tag_input_widget.placeholder = ''
            except Exception:
                pass

        self.call_later(set_placeholder_text)

        try:
            self.tag_input_widget.styles.display = 'block'
        except Exception:
            pass

        if hasattr(self, '_initially_selected_tags'):
            self._suspend_tag_selection_messages = True
            try:
                for tag_name in self._initially_selected_tags:
                    if tag_name in self._all_option_names:
                        await self.add_new_tag(tag_name)
            finally:
                self._suspend_tag_selection_messages = False

        if self._pending_options_state is not None:
            pending_state = self._pending_options_state
            self._pending_options_state = None
            self.set_options_state(pending_state)

        self._sync_dropdown_arrow_visibility()

    async def reset_last_tag(self) -> None:
        """Safely reset the last tag when backspace is pressed on an empty TagInput.

        The upstream textual-tags implementation assumes at least one tag exists and
        raises ``NoMatches`` when the widget has no selected tags.
        """

        if not self.allow_new_tags:
            return

        try:
            tags = list(self.query(Tag))
            if not tags:
                return

            last_tag = tags[-1]

            if last_tag.value in self.tag_values:
                self.tag_values.discard(last_tag.value)

            await last_tag.remove()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """
        Handle Input.Changed events from the TagInput widget.

        This provides autocomplete suggestions based on available options.
        Unlike WorkItemLabels which fetches from API, we use the pre-known options.

        Args:
            event: The Input.Changed event containing the new value
        """

        if event.input.id != f'{self.field_id}_input_tag':
            return

        query = event.value.strip().lower()

        if len(query) < 1:
            return

        matching_options = [
            opt
            for opt in self._all_option_names
            if query in opt.lower() and opt not in self.selected_tags
        ]

        if matching_options:
            self.add_tag_values(matching_options)

    @property
    def original_value(self) -> list[str]:
        """Get the original value IDs from Jira."""
        return self._original_value or []

    @property
    def update_enabled(self) -> bool:
        """Check if this field supports updates."""
        return self._supports_update

    @update_enabled.setter
    def update_enabled(self, value: bool) -> None:
        """Set whether this field supports updates."""
        self._supports_update = value
        self.disabled = not value

    @property
    def value(self) -> str:
        """
        Get current selections as a comma-separated string (for display).

        Returns:
            Comma-separated string of selected display names, or empty string if no selection.
        """
        if not self.selected_tags:
            return ''
        return ','.join(sorted(self.selected_tags))

    def get_selected_option_ids(self) -> list[str]:
        selected_ids: list[str] = []
        for name in self.selected_tags:
            value_id = self._name_to_id.get(name)
            if value_id is None:
                continue
            selected_ids.append(str(value_id))
        return selected_ids

    def get_selected_option_int_ids(self) -> list[int]:
        selected_ids: list[int] = []
        for value_id in self.get_selected_option_ids():
            try:
                selected_ids.append(int(value_id))
            except (TypeError, ValueError):
                continue
        return selected_ids

    def get_value_for_create(self) -> Sequence[dict[str, str]] | Sequence[str] | None:
        """
        Returns the value formatted for Jira API creation (CREATE mode).

        Returns:
            A list of dicts with IDs of selected options, or None if no selection
        """
        require_create_mode(self.mode, 'get_value_for_create()')
        selected = self.selected_tags
        if not selected:
            return None

        return [{'id': self._name_to_id[name]} for name in selected if name in self._name_to_id]

    def get_value_for_update(self) -> Sequence[dict[str, str]] | Sequence[str] | None:
        """
        Returns the value formatted for Jira API updates (UPDATE mode).

        Returns:
            A list of dicts with IDs of selected options, or empty list if no selection
        """
        require_update_mode(self.mode, 'get_value_for_update()')
        selected = self.selected_tags
        if not selected:
            return []

        return [{'id': self._name_to_id[name]} for name in selected if name in self._name_to_id]

    @property
    def value_has_changed(self) -> bool:
        """
        Determines if the current selection differs from the original value (UPDATE mode).

        Returns:
            True if selection has changed, False otherwise
        """
        require_update_mode(self.mode, 'value_has_changed')
        if self.loading or self._is_hydrating:
            return False

        original_ids = set(self.original_value or [])

        current_ids = set()
        for name in self.selected_tags:
            if name in self._name_to_id:
                current_ids.add(self._name_to_id[name])
            else:
                current_ids.add(name)

        return current_ids != original_ids

    async def update_options(
        self,
        options: list[tuple[str, str]],
        original_value: list[str] | None = None,
        field_supports_update: bool = True,
    ) -> None:
        """
        Update the widget with new options and values.

        This is used in UPDATE mode to refresh the widget with new data from Jira.

        Args:
            options: List of (display_name, value_id) tuples - all available options
            original_value: Original values from Jira as list of IDs
            field_supports_update: Whether field can be updated
        """

        self._suspend_change_events = True
        self._suspend_tag_selection_messages = True
        try:
            self._id_to_name = {value_id: name for name, value_id in options}
            self._name_to_id = dict(options)
            self._all_option_names = [name for name, _ in options]

            if original_value:
                self._original_value = list(original_value)
            else:
                self._original_value = None

            self._supports_update = field_supports_update
            self.disabled = not field_supports_update

            self.selected_tags.clear()
            self.tag_values.clear()

            from textual_tags import Tag

            for tag in self.query(Tag):
                await tag.remove()

            self.tag_values.update(self._all_option_names)

            try:
                self.tag_input_widget.styles.display = 'block'
            except Exception:
                pass

            if self._original_value:
                selected_tag_names = [
                    self._id_to_name.get(value_id, value_id) for value_id in self._original_value
                ]
                for tag_name in selected_tag_names:
                    if tag_name in self._all_option_names:
                        await self.add_new_tag(tag_name)
        finally:
            self._suspend_tag_selection_messages = False
            self._suspend_change_events = False

        self._sync_dropdown_arrow_visibility()

    async def _apply_options_state(
        self,
        *,
        options: list[tuple[str, str]],
        selection: list[str] | None,
        field_supports_update: bool,
    ) -> None:
        self._is_hydrating = True
        try:
            await self.update_options(
                options=options,
                original_value=selection,
                field_supports_update=field_supports_update,
            )
        finally:
            self._is_hydrating = False

    def set_options_state(self, state: dict[str, Any] | None) -> None:
        if not self.is_mounted:
            self._pending_options_state = state
            return

        if state is None:
            self.run_worker(
                self._apply_options_state(
                    options=[],
                    selection=None,
                    field_supports_update=self.update_enabled,
                ),
                exclusive=False,
            )
            return

        options = state.get('options', []) or []
        selection = state.get('selection')
        field_supports_update = state.get('field_supports_update', self.update_enabled)
        self.run_worker(
            self._apply_options_state(
                options=options,
                selection=selection,
                field_supports_update=field_supports_update,
            ),
            exclusive=False,
        )
