from gojeera.utils.data.fields import require_update_mode
from gojeera.widgets.inputs.base_masked_input_field import BaseMaskedInputField


class DateTimeInput(BaseMaskedInputField):
    """
    Unified datetime input widget that works in both CREATE and UPDATE modes.

    Uses MaskedInput with template '9999-99-99 99:99:99' for datetime entry.
    """

    _strip_chars = '-: '
    _mask_template = '9999-99-99 99:99:99'
    _mask_placeholder = '2025-12-23 13:45:10'
    _mask_compact = False
    DEFAULT_CSS = """
    DateTimeInput {
        width: 100%;
    }
    """

    def get_value_for_update(self) -> str | None:
        require_update_mode(self.mode, 'get_value_for_update()')
        return self._try_parse_update_value(
            self.value, lambda parsed_value: parsed_value.isoformat()
        )
