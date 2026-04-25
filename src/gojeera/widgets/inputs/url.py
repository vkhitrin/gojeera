from typing import Any

from textual.widgets import Input

from gojeera.utils.data.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    configure_compact_field_for_mode,
    require_create_mode,
    require_update_mode,
)


class URL(Input, BaseField, BaseUpdateField):
    """
    URL input widget.
    """

    DEFAULT_CSS = """
    URL {
        width: 100%;
        padding: 0;
    }
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        original_value: str | None = None,
        field_supports_update: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            placeholder='https://example.com',
            id=field_id,
            compact=True,
            **kwargs,
        )
        configure_compact_field_for_mode(
            self,
            mode=mode,
            field_id=field_id,
            title=title,
            original_value=original_value or '',
            field_supports_update=field_supports_update,
            update_value=original_value or '',
        )

    def on_input_blurred(self, _event: Input.Changed) -> None:
        if self.mode == FieldMode.UPDATE and not self.update_enabled:
            return

        value = self.value.strip()
        if value and 'http' not in value:
            self.value = f'https://{value}'

    def get_value_for_create(self) -> str:
        require_create_mode(self.mode, 'get_value_for_create()')
        return self.value.strip()

    def get_value_for_update(self) -> str:
        require_update_mode(self.mode, 'get_value_for_update()')
        return self.value.strip()

    @property
    def value_has_changed(self) -> bool:
        require_update_mode(self.mode, 'value_has_changed')
        original = self.original_value.strip()
        current = self.value.strip()

        if not original and not current:
            return False

        return original != current
