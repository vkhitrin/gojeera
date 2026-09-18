"""Shared widget surface for modal forms."""

from textual.widgets import Static

from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.markdown.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.navigation.extended_jumper import set_jump_mode
from gojeera.widgets.selection.vim_select import VimSelect


def build_incremental_loading_label(text: str, widget_id: str) -> Static:
    label = Static(text, id=widget_id)
    label.display = False
    return label


__all__ = [
    'ExtendedADFMarkdownTextArea',
    'ExtendedFooter',
    'ExtendedInput',
    'ExtendedModalScreen',
    'VerticalSuppressClicks',
    'VimSelect',
    'build_incremental_loading_label',
    'build_modal_cancel_button',
    'build_modal_confirm_button',
    'set_jump_mode',
]
