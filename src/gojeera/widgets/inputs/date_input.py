from gojeera.utils.data.fields import FieldMode, require_update_mode
from gojeera.widgets.inputs.base_masked_input_field import BaseMaskedInputField


class DateInput(BaseMaskedInputField):
    """This widget extends MaskedInput with template '9999-99-99' (YYYY-MM-DD format)."""

    _strip_chars = '-'
    _mask_template = '9999-99-99'
    _mask_placeholder = '1970-01-01'
    _mask_compact = True
    _mask_initial_classes = ('input-date',)

    DEFAULT_CSS = """
    DateInput {
        width: 100%;
        border: none;
        height: 1;
        padding: 0 0;
    }
    """

    @staticmethod
    def _configured_required(mode: FieldMode, required: bool) -> bool:
        return required if mode == FieldMode.CREATE else False

    def get_value_for_update(self) -> str | None:
        require_update_mode(self.mode, 'get_value_for_update()')
        return self._try_parse_update_value(
            self.value, lambda parsed_value: str(parsed_value.date())
        )

    def set_original_value(self, value: str | None) -> None:
        require_update_mode(self.mode, 'set_original_value()')
        self._original_value = value
        self.value = value if value else ''
