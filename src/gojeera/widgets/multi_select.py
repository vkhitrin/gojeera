import logging
from typing import Sequence, cast

from textual import events
from textual.reactive import reactive
from textual.widgets import Input
from textual_tags import Tag, TagAutoComplete, TagInput, Tags

from gojeera.utils.fields import BaseField, FieldMode

logger = logging.getLogger('gojeera')


class MultiSelectTagAutoComplete(TagAutoComplete):
    """Keep autocomplete open long enough for mouse option selection."""

    def _handle_focus_change(self, has_focus: bool) -> None:
        if has_focus:
            super()._handle_focus_change(has_focus)


class MultiSelectTagInput(TagInput):
    """Reopen autocomplete suggestions on mouse click."""

    def on_click(self, event: events.Click) -> None:
        self.focus()
        parent = self.parent
        if parent is not None:
            parent.query_one(TagAutoComplete).action_show()


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

    selected_tags: reactive[set[str]] = cast(reactive[set[str]], reactive(SafeSet))

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

        self._id_to_name = {value_id: name for name, value_id in options}
        self._name_to_id = dict(options)

        if mode == FieldMode.UPDATE and original_value:
            self._original_value = (
                list(original_value) if not isinstance(original_value, list) else original_value
            )
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

        self._ensure_safe_selected_tags()

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            compact=True,
        )

        self._initially_selected_tags = selected_tag_names

        if self.mode == FieldMode.CREATE:
            self.add_class('create-work-item-generic-input-field')
        elif self.mode == FieldMode.UPDATE:
            self.add_class('work_item_details_input_field')

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

        tag = Tag(value)
        tag.show_x = self.show_x
        tag.tooltip = value
        await self.mount(tag, before=f'#{self.field_id}_input_tag')
        self._ensure_safe_selected_tags().add(value)

        self.mutate_reactive(Tags.selected_tags)

        if value not in self.tag_values:
            self.tag_values.add(value)

        if not self._suspend_tag_selection_messages:

            def trigger_validation():
                try:
                    self.post_message(Tag.Selected(tag))
                except Exception as e:
                    logger.debug(f'Exception occurred: {e}')

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
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    async def on_mount(self) -> None:
        """Mount handler - manually mount initially selected tags."""

        await super().on_mount()

        def set_placeholder_text():
            try:
                placeholder_text = ''
                tag_input = self.query_one(TagInput)
                tag_input.placeholder = placeholder_text
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

        self.call_later(set_placeholder_text)

        try:
            tag_input = self.query_one(TagInput)
            tag_input.styles.display = 'block'
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        if hasattr(self, '_initially_selected_tags'):
            self._suspend_tag_selection_messages = True
            try:
                for tag_name in self._initially_selected_tags:
                    if tag_name in self._all_option_names:
                        await self.add_new_tag(tag_name)
            finally:
                self._suspend_tag_selection_messages = False

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
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

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

    def get_value_for_create(self) -> Sequence[dict[str, str]] | Sequence[str] | None:
        """
        Returns the value formatted for Jira API creation (CREATE mode).

        Returns:
            A list of dicts with IDs of selected options, or None if no selection
        """
        if self.mode != FieldMode.CREATE:
            raise ValueError('get_value_for_create() only valid in CREATE mode')

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
        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

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
        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

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

        self._id_to_name = {value_id: name for name, value_id in options}
        self._name_to_id = dict(options)
        self._all_option_names = [name for name, _ in options]

        if original_value:
            self._original_value = (
                list(original_value) if not isinstance(original_value, list) else original_value
            )
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
            from textual_tags import TagInput as TagInputWidget

            tag_input = self.query_one(TagInputWidget)
            tag_input.styles.display = 'block'
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        if self._original_value:
            selected_tag_names = [
                self._id_to_name.get(value_id, value_id) for value_id in self._original_value
            ]
            self._suspend_tag_selection_messages = True
            try:
                for tag_name in selected_tag_names:
                    if tag_name in self._all_option_names:
                        await self.add_new_tag(tag_name)
            finally:
                self._suspend_tag_selection_messages = False
