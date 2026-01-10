from textual.events import Key
from textual.validation import Number
from textual.widgets import Input

from gojeera.utils.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    ValidationUtils,
)


class NumericInput(Input, BaseField, BaseUpdateField):
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

        self.styles.width = '100%'

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            compact=True,
        )

        if mode == FieldMode.UPDATE:
            str_value = str(original_value) if original_value is not None else ''
            self.setup_update_field(
                jira_field_key=field_id,
                original_value=original_value,
                field_supports_update=field_supports_update,
            )
            self.value = str_value
            self.add_class('work_item_details_input_field')
        else:
            self.add_class('create-work-item-float-input')

    def get_value_for_update(self) -> float | None:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

        if self.value and self.value.strip():
            try:
                return float(self.value)
            except ValueError:
                return None
        return None

    def get_value_for_create(self) -> float | None:
        if self.mode != FieldMode.CREATE:
            raise ValueError('get_value_for_create() only valid in CREATE mode')

        if self.value and self.value.strip():
            try:
                return float(self.value)
            except ValueError:
                return None
        return None

    def on_key(self, event: Key) -> None:
        control_keys = {
            'backspace',
            'delete',
            'left',
            'right',
            'home',
            'end',
            'tab',
            'escape',
            'enter',
            'up',
            'down',
        }

        if event.key in control_keys:
            return

        if event.character and event.character.isdigit():
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
        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

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
