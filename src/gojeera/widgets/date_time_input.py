from dateutil.parser import isoparse
from textual.validation import ValidationResult
from textual.widgets import MaskedInput

from gojeera.utils.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
)


class DateTimeInput(MaskedInput, BaseField, BaseUpdateField):
    """
    Unified datetime input widget that works in both CREATE and UPDATE modes.

    Uses MaskedInput with template '9999-99-99 99:99:99' for datetime entry.
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
        valid_empty = not required if mode == FieldMode.CREATE else True
        super().__init__(
            id=field_id,
            template='9999-99-99 99:99:99',
            placeholder='2025-12-23 13:45:10',
            valid_empty=valid_empty,
        )

        self.styles.width = '100%'

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            compact=False,
        )

        if mode == FieldMode.UPDATE:
            self.setup_update_field(
                jira_field_key=field_id,
                original_value=original_value,
                field_supports_update=field_supports_update,
            )
            self.add_class('work_item_details_input_field')

            if original_value:
                self.value = original_value
        else:
            self.add_class('create-work-item-datetime-input')

    def validate(self, value: str) -> ValidationResult | None:
        """Override validation to allow empty values when valid_empty is True.

        Args:
            value: The value to validate

        Returns:
            ValidationResult indicating whether validation succeeded
        """

        def set_classes() -> None:
            valid = self._valid
            self.set_class(not valid, '-invalid')
            self.set_class(valid, '-valid')

        if self.valid_empty:
            stripped = (
                value.replace('_', '').replace('-', '').replace(':', '').replace(' ', '').strip()
            )
            if not stripped:
                self._valid = True
                set_classes()
                return None

        return super().validate(value)

    def get_value_for_update(self) -> str | None:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

        if self.value and self.value.strip():
            try:
                return isoparse(self.value).isoformat()
            except ValueError:
                return None
        return None

    @property
    def value_has_changed(self) -> bool:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

        original = self.original_value if self.original_value else ''
        current = self.value.strip() if self.value else ''

        if not original and not current:
            return False

        if not original or not current:
            return True

        return original != current
