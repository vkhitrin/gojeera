from textual.widgets import Input

from gojeera.utils.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    ValidationUtils,
)


class TextInput(Input, BaseField, BaseUpdateField):
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
                original_value=original_value or '',
                field_supports_update=field_supports_update,
            )
            self.add_class('work_item_details_input_field')

            if original_value:
                self.value = original_value
        else:
            self.add_class('create-work-item-generic-input-field')

    def get_value_for_update(self) -> str:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

        return self.value

    @property
    def value_has_changed(self) -> bool:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

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
