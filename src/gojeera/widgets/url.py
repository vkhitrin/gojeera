from typing import Any

from textual.widgets import Input

from gojeera.utils.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
)


class URL(Input, BaseField, BaseUpdateField):
    """
    URL input widget.
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: str | None = None,
        field_supports_update: bool = True,
        **kwargs: Any,
    ) -> None:
        self.mode = mode
        self._original_value = original_value or ''
        self._supports_update = field_supports_update
        self.field_id = field_id

        placeholder = 'https://example.com'
        super().__init__(
            placeholder=placeholder,
            id=field_id,
            compact=True,
            **kwargs,
        )

        self.styles.width = '100%'

        self.styles.padding = (0, 0, 0, 0)

        self.label_text = title

        if mode == FieldMode.CREATE:
            self.add_class('create-field')
        elif mode == FieldMode.UPDATE:
            self.add_class('update-field')
            if original_value:
                self.value = original_value
            if not field_supports_update:
                self.disabled = True

    @property
    def original_value(self) -> str:
        return self._original_value

    def on_input_blurred(self, event: Input.Changed) -> None:
        if self.mode == FieldMode.UPDATE and not self._supports_update:
            return

        value = self.value.strip()
        if value and 'http' not in value:
            self.value = f'https://{value}'

    def get_value_for_create(self) -> str:
        if self.mode != FieldMode.CREATE:
            msg = 'get_value_for_create() can only be called in CREATE mode'
            raise ValueError(msg)
        return self.value.strip()

    def get_value_for_update(self) -> str:
        if self.mode != FieldMode.UPDATE:
            msg = 'get_value_for_update() can only be called in UPDATE mode'
            raise ValueError(msg)
        return self.value.strip()

    @property
    def value_has_changed(self) -> bool:
        if self.mode != FieldMode.UPDATE:
            msg = 'value_has_changed can only be checked in UPDATE mode'
            raise ValueError(msg)

        original = self.original_value.strip()
        current = self.value.strip()

        if not original and not current:
            return False

        return original != current
