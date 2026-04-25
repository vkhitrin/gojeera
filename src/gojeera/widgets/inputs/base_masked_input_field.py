from typing import Any, Callable

from dateutil.parser import isoparse
from textual.validation import ValidationResult
from textual.widgets import MaskedInput

from gojeera.utils.data.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    configure_compact_field_for_mode,
    update_value_or_unset,
)
from gojeera.widgets.inputs.masked_input_utils import (
    allow_empty_masked_input_validation,
    update_field_value_has_changed,
)


class BaseMaskedInputField(MaskedInput, BaseField, BaseUpdateField):
    _strip_chars = ''
    _mask_template = ''
    _mask_placeholder = ''
    _mask_compact = False
    _mask_initial_classes: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: str | None = None,
        field_supports_update: bool = True,
    ) -> None:
        configured_required = self._configured_required(mode, required)
        valid_empty = not configured_required if mode == FieldMode.CREATE else True
        super().__init__(
            id=field_id,
            template=self._mask_template,
            placeholder=self._mask_placeholder,
            valid_empty=valid_empty,
            compact=self._mask_compact,
        )

        configure_compact_field_for_mode(
            self,
            mode=mode,
            field_id=field_id,
            title=title,
            required=configured_required,
            compact=self._mask_compact,
            original_value=original_value,
            field_supports_update=field_supports_update,
            update_value=update_value_or_unset(original_value),
        )
        for class_name in self._mask_initial_classes:
            self.add_class(class_name)

    def validate(self, value: str) -> ValidationResult | None:
        if allow_empty_masked_input_validation(self, value, strip_chars=self._strip_chars):
            return None

        return super().validate(value)

    @staticmethod
    def _try_parse_update_value(value: str | None, formatter: Callable[[Any], str]) -> str | None:
        if value and value.strip():
            try:
                return formatter(isoparse(value))
            except ValueError:
                return None
        return None

    @property
    def value_has_changed(self) -> bool:
        return update_field_value_has_changed(
            mode=self.mode,
            original_value=self.original_value,
            current_value=self.value,
        )

    @staticmethod
    def _configured_required(mode: FieldMode, required: bool) -> bool:
        del mode
        return required
