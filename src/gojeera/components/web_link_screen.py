from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static

from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class RemoteLinkURLInputWidget(Input):
    def __init__(self):
        super().__init__(
            classes='required',
            type='text',
            placeholder='',
            tooltip='The URL of the external resource',
        )
        self.compact = True


class RemoteLinkNameInputWidget(Input):
    def __init__(self):
        super().__init__(
            classes='required',
            type='text',
            placeholder='A short title for the link...',
            tooltip='A title to describe the link',
        )
        self.compact = True


class RemoteLinkScreen(ModalScreen[dict]):
    """A screen to add or edit a remote link for a work item."""

    BINDINGS = [
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
                    yield Label('URL').add_class('field_label')
                    yield RemoteLinkURLInputWidget()
                    yield Label('Title').add_class('field_label')
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
                    'Cancel', variant='error', id='add-remote-link-button-quit', compact=True
                )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            self.link_url.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.link_name.jump_mode = 'focus'  # type: ignore[attr-defined]

            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#add-remote-link-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

        if self.is_edit_mode:
            if self.initial_url:
                self.link_url.value = self.initial_url
            if self.initial_title:
                self.link_name.value = self.initial_title

            if self.initial_url and self.initial_title:
                self.save_button.disabled = False

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def on_click(self) -> None:
        self.dismiss({})

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
        self.dismiss({})
