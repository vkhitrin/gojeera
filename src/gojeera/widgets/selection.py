from typing import Any

from textual.widgets import Select

from gojeera.utils.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
)
from gojeera.widgets.vim_select import VimSelect


class SelectionWidget(VimSelect, BaseField, BaseUpdateField):
    """
    Selection widget.
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        options: list[tuple[str, str]],
        title: str | None = None,
        required: bool = False,
        initial_value: Any = Select.NULL,
        original_value: str | None = None,
        field_supports_update: bool = True,
        allow_blank: bool = True,
        prompt: str | None = None,
    ):
        display_prompt = prompt or ''

        super().__init__(
            options=options,
            prompt=display_prompt,
            id=field_id,
            allow_blank=allow_blank,
            compact=True,
            type_to_search=True,
        )

        self.styles.width = '100%'

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            compact=True,
        )

        if mode == FieldMode.UPDATE:
            self.setup_update_field(
                jira_field_key=field_id,
                original_value=original_value,
                field_supports_update=field_supports_update,
            )

            if original_value is not None:
                self.value = original_value
            self.add_class('create-work-item-generic-selector')
        else:
            if initial_value != Select.NULL:
                self.value = initial_value
            self.add_class('create-work-item-generic-selector')

    def get_value_for_update(self) -> dict | None:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

        if self.selection is None:
            return None
        return {'id': self.selection}

    def get_value_for_create(self) -> dict | None:
        if self.mode != FieldMode.CREATE:
            raise ValueError('get_value_for_create() only valid in CREATE mode')

        if self.value and self.value != Select.NULL:
            return {'id': self.value}
        return None

    @property
    def value_has_changed(self) -> bool:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

        if not self.original_value:
            return bool(self.selection)

        if not self.selection:
            return True

        return self.original_value != self.selection
