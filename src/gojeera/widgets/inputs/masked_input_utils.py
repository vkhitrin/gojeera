from __future__ import annotations

from textual.widgets import MaskedInput

from gojeera.utils.data.fields import FieldMode, require_update_mode


def allow_empty_masked_input_validation(
    widget: MaskedInput,
    value: str,
    *,
    strip_chars: str,
) -> bool:
    if not widget.valid_empty:
        return False

    stripped = value
    for char in f'_{strip_chars}':
        stripped = stripped.replace(char, '')
    stripped = stripped.strip()
    if stripped:
        return False

    widget.__dict__['_valid'] = True
    widget.set_class(False, '-invalid')
    widget.set_class(True, '-valid')
    return True


def update_field_value_has_changed(
    *,
    mode: FieldMode,
    original_value: str | None,
    current_value: str | None,
) -> bool:
    require_update_mode(mode, 'value_has_changed')

    original = original_value if original_value else ''
    current = current_value.strip() if current_value else ''

    if not original and not current:
        return False

    if not original or not current:
        return True

    return original != current
