from textual.events import Key
from textual.validation import Number

from gojeera.utils.data.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    ValidationUtils,
    configure_compact_field_for_mode,
    require_create_mode,
    require_update_mode,
)
from gojeera.widgets.inputs.extended_input import ExtendedInput, allow_digit_only_key_input


class NumericInput(ExtendedInput, BaseField, BaseUpdateField):
    """
    Numeric/float input widget.
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        placeholder: str = '',
        original_value: float | None = None,
        field_supports_update: bool = True,
    ):
        super().__init__(
            id=field_id,
            placeholder=placeholder,
            validators=[Number()] if required else [],
            valid_empty=not required,
            type='number' if mode == FieldMode.UPDATE else 'text',
            compact=True,
        )

        configure_compact_field_for_mode(
            mode=mode,
            widget=self,
            field_id=field_id,
            title=title,
            required=required,
            original_value=original_value,
            field_supports_update=field_supports_update,
            create_classes=['create-work-item-float-input', 'surface-input-float'],
            update_value=str(original_value) if original_value is not None else '',
        )

    def get_value_for_update(self) -> float | None:
        require_update_mode(self.mode, 'get_value_for_update()')
        return self._parse_float_value()

    def get_value_for_create(self) -> float | None:
        require_create_mode(self.mode, 'get_value_for_create()')
        return self._parse_float_value()

    def _parse_float_value(self) -> float | None:
        if self.value and self.value.strip():
            try:
                return float(self.value)
            except ValueError:
                return None
        return None

    def on_key(self, event: Key) -> None:
        if allow_digit_only_key_input(event, extra_control_keys={'up', 'down'}):
            return

        if event.character == '.':
            if '.' not in self.value:
                return
            else:
                event.prevent_default()
                return

        if event.character == '-':
            if not self.value or self.cursor_position == 0:
                return
            else:
                event.prevent_default()
                return

        event.prevent_default()

    @property
    def value_has_changed(self) -> bool:
        require_update_mode(self.mode, 'value_has_changed')
        if self.original_value is None:
            result = bool(self.value and self.value.strip())
            return result

        if ValidationUtils.is_empty_or_whitespace(self.value):
            return True

        try:
            current_float = float(self.value.strip())

            epsilon = 1e-9
            diff = abs(self.original_value - current_float)
            result = diff > epsilon

            return result
        except (ValueError, TypeError):
            return True
