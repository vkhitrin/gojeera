from dateutil.parser import isoparse
from textual.validation import ValidationResult
from textual.widgets import MaskedInput

from gojeera.utils.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
)


class DateInput(MaskedInput, BaseField, BaseUpdateField):
    """This widget extends MaskedInput with template '9999-99-99' (YYYY-MM-DD format)."""

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
            template='9999-99-99',
            id=field_id,
            valid_empty=valid_empty,
            compact=True,
            placeholder='1970-01-01',
        )

        self.styles.width = '100%'

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title,
            required=required if mode == FieldMode.CREATE else False,
            compact=True,
        )
        self.add_class('input-date')

        if mode == FieldMode.UPDATE:
            self.setup_update_field(
                jira_field_key=field_id,
                original_value=original_value,
                field_supports_update=field_supports_update,
            )

            if original_value:
                self.value = original_value

    def validate(self, value: str) -> ValidationResult | None:
        """Override validation to allow empty values when valid_empty is True.

        MaskedInput validates against the template even when valid_empty=True,
        which causes empty fields with placeholder characters to be marked as invalid.
        This override allows empty values to pass validation without triggering the
        template validation.

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
            stripped = value.replace('_', '').replace('-', '').strip()
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
                return str(isoparse(self.value).date())
            except ValueError:
                return None
        return None

    def set_original_value(self, value: str | None) -> None:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('set_original_value() only valid in UPDATE mode')

        self._original_value = value
        self.value = value if value else ''

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
