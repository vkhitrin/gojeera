from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Static

from gojeera.config import CONFIGURATION
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_input import ExtendedInput
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


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

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

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

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='add-remote-link-form'):
                with Vertical():
                    url_label = Label('URL')
                    url_label.add_class('field_label')
                    yield url_label
                    yield RemoteLinkURLInputWidget()
                    title_label = Label('Title')
                    title_label.add_class('field_label')
                    yield title_label
                    yield RemoteLinkNameInputWidget()
            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id='add-remote-link-button-save',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='add-remote-link-button-quit',
                    compact=True,
                )
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.link_url, 'focus')
            set_jump_mode(self.link_name, 'focus')

            set_jump_mode(self.save_button, 'click')
            set_jump_mode(self.query_one('#add-remote-link-button-quit', Button), 'click')

        if self.is_edit_mode:
            if self.initial_url:
                self.link_url.value = self.initial_url
            if self.initial_title:
                self.link_name.value = self.initial_title

            if self.initial_url and self.initial_title:
                self.save_button.disabled = False

        self.call_after_refresh(lambda: focus_first_available(self.link_url, self.link_name))

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    @on(Input.Blurred, 'RemoteLinkURLInputWidget')
    def validate_url(self):
        value = self.link_url.value
        self.save_button.disabled = (
            False
            if (value and value.strip()) and self.link_name.value and self.link_name.value.strip()
            else True
        )

    @on(Input.Blurred, 'RemoteLinkNameInputWidget')
    def validate_name(self):
        value = self.link_name.value
        self.save_button.disabled = (
            False
            if (value and value.strip()) and self.link_url.value and self.link_url.value.strip()
            else True
        )

    @on(Input.Changed, 'RemoteLinkNameInputWidget')
    def validate_change(self, event: Input.Changed):
        if event.value and event.value.strip():
            self.save_button.disabled = not self.link_url.value or not self.link_url.value.strip()
        else:
            self.save_button.disabled = True

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
