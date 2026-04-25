from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Static

from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks


class RemoteLinkURLInputWidget(ExtendedInput):
    def __init__(self):
        super().__init__(
            classes='required',
            type='text',
            placeholder='',
            tooltip='The URL of the external resource',
        )
        self.compact = True


class RemoteLinkNameInputWidget(ExtendedInput):
    def __init__(self):
        super().__init__(
            classes='required',
            type='text',
            placeholder='A short title for the link...',
            tooltip='A title to describe the link',
        )
        self.compact = True


class RemoteLinkScreen(ExtendedModalScreen[dict]):
    """A screen to add or edit a remote link for a work item."""

    def __init__(
        self,
        work_item_key: str | None = None,
        link_id: str | None = None,
        initial_url: str | None = None,
        initial_title: str | None = None,
    ):
        super().__init__()
        self.work_item_key = work_item_key
        self.link_id = link_id
        self.initial_url = initial_url
        self.initial_title = initial_title
        self.is_edit_mode = link_id is not None
        action = 'Edit' if self.is_edit_mode else 'Add'
        self._modal_title: str = f'{action} Remote Link - Work Item: {self.work_item_key}'

    @property
    def link_name(self) -> RemoteLinkNameInputWidget:
        return self.query_one(RemoteLinkNameInputWidget)

    @property
    def link_url(self) -> RemoteLinkURLInputWidget:
        return self.query_one(RemoteLinkURLInputWidget)

    @property
    def save_button(self) -> Button:
        return self.query_one('#add-remote-link-button-save', expect_type=Button)

    def _has_required_link_fields(self) -> bool:
        return bool(self.link_url.value and self.link_url.value.strip()) and bool(
            self.link_name.value and self.link_name.value.strip()
        )

    def _update_save_button_enabled(self) -> None:
        self.save_button.disabled = not self._has_required_link_fields()

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(
                id='add-remote-link-form',
                classes='modal-form modal-form--fields tab-scroll-surface--persistent',
            ):
                with Vertical():
                    url_label = Label('URL')
                    url_label.add_class('field_label')
                    yield url_label
                    yield RemoteLinkURLInputWidget()
                    title_label = Label('Title')
                    title_label.add_class('field_label')
                    yield title_label
                    yield RemoteLinkNameInputWidget()
            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button, button_id='add-remote-link-button-save', disabled=True
                )
                yield build_modal_cancel_button(Button, button_id='add-remote-link-button-quit')
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        self.activate_modal_actions(self.link_url, self.link_name, jump_mode='focus')
        self.activate_modal_actions(
            self.save_button,
            self.query_one('#add-remote-link-button-quit', Button),
            focus=False,
        )

        if self.is_edit_mode:
            if self.initial_url:
                self.link_url.value = self.initial_url
            if self.initial_title:
                self.link_name.value = self.initial_title

            if self.initial_url and self.initial_title:
                self.save_button.disabled = False

    @on(Input.Blurred, 'RemoteLinkURLInputWidget')
    def validate_url(self):
        self._update_save_button_enabled()

    @on(Input.Blurred, 'RemoteLinkNameInputWidget')
    def validate_name(self):
        self._update_save_button_enabled()

    @on(Input.Changed, 'RemoteLinkNameInputWidget')
    def validate_change(self, event: Input.Changed):
        _ = event
        self._update_save_button_enabled()

    @on(Button.Pressed, '#add-remote-link-button-save')
    def handle_save(self) -> None:
        url_value = self.link_url.value
        name_value = self.link_name.value

        if not url_value or not name_value:
            action = 'Edit' if self.is_edit_mode else 'Add'
            self.notify('Enter a URL and a title for the link.', title=f'{action} Remote Link')
            return

        result = {
            'link_url': url_value,
            'link_title': name_value,
        }
        if self.is_edit_mode and self.link_id:
            result['link_id'] = self.link_id

        self.dismiss(result)

    @on(Button.Pressed, '#add-remote-link-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss()
