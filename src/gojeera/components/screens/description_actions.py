import logging
from typing import TYPE_CHECKING, Protocol, cast

from textual.containers import Vertical
from textual.widgets import Label

from gojeera.components.screens.decision_picker_screen import DecisionPickerScreen
from gojeera.components.screens.panel_picker_screen import PanelPickerScreen
from gojeera.utils.ui.textarea_insertion import insert_picker_markup_from_getter
from gojeera.widgets.markdown.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea

if TYPE_CHECKING:
    from textual.app import App
    from textual.widgets import TextArea


logger = logging.getLogger('gojeera')


class DescriptionActionsHost(Protocol):
    app: 'App'
    description_textarea: 'TextArea'

    def notify(self, message: str, *args, **kwargs) -> None: ...


class DescriptionActionsMixin:
    def compose_description_field(
        self,
        initial_text: str = '',
        initial_wrap_width_hint: int | None = None,
    ):
        with Vertical(id='description-field-container'):
            description_label = Label('Description')
            description_label.add_class('field_label')
            yield description_label
            yield ExtendedADFMarkdownTextArea(
                field_id='description',
                required=False,
                initial_text=initial_text,
                initial_wrap_width_hint=initial_wrap_width_hint,
            )

    async def action_insert_decision(self) -> None:
        host = cast(DescriptionActionsHost, self)
        await insert_picker_markup_from_getter(
            app=host.app,
            get_textarea=lambda: host.description_textarea,
            picker_screen=DecisionPickerScreen(),
            build_insertion_text=lambda result: f'> `{result[0]}` ',
            logger=logger,
            error_context='Description widget or TextArea',
        )

    async def action_insert_alert(self) -> None:
        host = cast(DescriptionActionsHost, self)
        await insert_picker_markup_from_getter(
            app=host.app,
            get_textarea=lambda: host.description_textarea,
            picker_screen=PanelPickerScreen(),
            build_insertion_text=lambda result: f'> {result[0]}\n> ',
            logger=logger,
            error_context='Description widget or TextArea',
        )
