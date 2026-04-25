from typing import Any

from textual.widgets import Select

from gojeera.utils.data.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    configure_select_field_for_mode,
    optional_selection_value_has_changed,
    require_create_mode,
    require_update_mode,
    selection_update_payload,
)
from gojeera.widgets.selection.vim_select import VimSelect


class SelectionWidget(VimSelect, BaseField, BaseUpdateField):
    """
    Selection widget.
    """

    DEFAULT_CSS = """
    SelectionWidget {
        width: 100%;
    }
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        options: list[tuple[str, str]],
        title: str | None = None,
        required: bool = False,
        initial_value: Any = Select.NULL,
        original_value: str | None = None,
        field_supports_update: bool = True,
        allow_blank: bool = True,
        prompt: str | None = None,
    ):
        display_prompt = prompt or ''
        select_value = original_value if mode == FieldMode.UPDATE else initial_value
        if select_value is None:
            select_value = Select.NULL

        super().__init__(
            options=options,
            prompt=display_prompt,
            id=field_id,
            allow_blank=allow_blank,
            value=select_value,
            compact=True,
            type_to_search=True,
        )

        configure_select_field_for_mode(
            self,
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            original_value=original_value,
            field_supports_update=field_supports_update,
        )

    def get_value_for_update(self) -> dict | None:
        require_update_mode(self.mode, 'get_value_for_update()')
        return selection_update_payload(self.selection, 'id')

    def get_value_for_create(self) -> dict | None:
        require_create_mode(self.mode, 'get_value_for_create()')
        if self.value and self.value != Select.NULL:
            return {'id': self.value}
        return None

    @property
    def value_has_changed(self) -> bool:
        require_update_mode(self.mode, 'value_has_changed')
        return optional_selection_value_has_changed(
            original_value=self.original_value,
            current_value=self.selection,
        )
