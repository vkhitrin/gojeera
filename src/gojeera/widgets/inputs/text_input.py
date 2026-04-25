from gojeera.utils.data.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    ValidationUtils,
    configure_compact_field_for_mode,
    require_update_mode,
    update_value_or_unset,
)
from gojeera.widgets.inputs.extended_input import ExtendedInput


class TextInput(ExtendedInput, BaseField, BaseUpdateField):
    """
    Text input widget.
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: str | None = None,
        field_supports_update: bool = True,
    ):
        super().__init__(
            id=field_id,
            compact=True,
        )

        configure_compact_field_for_mode(
            self,
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            original_value=original_value or '',
            field_supports_update=field_supports_update,
            update_value=update_value_or_unset(original_value),
        )

    def get_value_for_update(self) -> str:
        require_update_mode(self.mode, 'get_value_for_update()')
        return self.value

    @property
    def value_has_changed(self) -> bool:
        require_update_mode(self.mode, 'value_has_changed')
        original = self.original_value if self.original_value else ''
        current = self.value if self.value else ''

        if ValidationUtils.is_empty_or_whitespace(
            original
        ) and ValidationUtils.is_empty_or_whitespace(current):
            return False

        if ValidationUtils.is_empty_or_whitespace(
            original
        ) or ValidationUtils.is_empty_or_whitespace(current):
            return True

        return ValidationUtils.values_differ(original, current, ignore_whitespace=True)
