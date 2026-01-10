from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Select, Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.config import CONFIGURATION
from gojeera.models import LinkWorkItemType
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.vim_select import VimSelect


class LinkedWorkItemInputWidget(Input):
    def __init__(self):
        super().__init__(
            classes='required',
            type='text',
            placeholder='e.g. ABC-1234',
            tooltip='Enter a case-sensitive key',
        )
        self.compact = True


class WorkItemLinkTypeSelector(VimSelect):
    def __init__(self, items: list[tuple[str, str]]):
        super().__init__(
            options=items,
            prompt='Select a link type',
            name='work_item_link_types',
            type_to_search=True,
            compact=True,
        )
        self.valid_empty = False


class AddWorkItemRelationshipScreen(ModalScreen[dict]):
    """A modal screen to allow the user to link work items."""

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, work_item_key: str | None = None):
        super().__init__()
        self.work_item_key = work_item_key
        self._modal_title: str = f'Link Work Items - Work Item: {self.work_item_key}'

    @property
    def relationship_type(self) -> WorkItemLinkTypeSelector:
        return self.query_one(WorkItemLinkTypeSelector)

    @property
    def linked_work_item_key(self) -> LinkedWorkItemInputWidget:
        return self.query_one(LinkedWorkItemInputWidget)

    @property
    def save_button(self) -> Button:
        return self.query_one('#add-link-button-save', expect_type=Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='link-work-items-form'):
                with Vertical():
                    yield Label('Link Type').add_class('field_label')
                    yield WorkItemLinkTypeSelector([])
                    yield Label('Work Item Key').add_class('field_label')
                    yield LinkedWorkItemInputWidget()
            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id='add-link-button-save',
                    disabled=True,
                    compact=True,
                )
                yield Button('Cancel', variant='error', id='add-link-button-quit', compact=True)
        yield Footer(show_command_palette=False)

    async def on_mount(self) -> None:
        self.run_worker(self.fetch_work_item_link_types())

        if CONFIGURATION.get().jumper.enabled:
            self.relationship_type.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.linked_work_item_key.jump_mode = 'focus'  # type: ignore[attr-defined]

            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#add-link-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

    def validate_work_item_key(self):
        value = self.linked_work_item_key.value
        self.save_button.disabled = (
            False if (value and value.strip()) and self.relationship_type.selection else True
        )

    @on(Input.Changed, 'LinkedWorkItemInputWidget')
    def validate_change(self, event: Input.Changed):
        if event.value and event.value.strip():
            self.save_button.disabled = not self.relationship_type.selection
        else:
            self.save_button.disabled = True

    @on(Select.Changed, 'WorkItemLinkTypeSelector')
    def validate_relationship(self):
        value = self.linked_work_item_key.value
        self.save_button.disabled = (
            False if (value and value.strip()) and self.relationship_type.selection else True
        )

    def on_click(self) -> None:
        self.dismiss({})

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def fetch_work_item_link_types(self) -> None:
        response: APIControllerResponse = await self.app.api.work_item_link_types()  # type: ignore[union-attr]
        if not response.success:
            self.notify(
                'Unable to fetch the types of supported links',
                title='Link Work Items',
                severity='error',
            )
            self.relationship_type.set_options([])
        else:
            link_type: LinkWorkItemType
            options: list[tuple[str, str]] = []
            for link_type in response.result or []:
                options.append((link_type.inward, f'{link_type.id}:inward'))
                options.append((link_type.outward, f'{link_type.id}:outward'))
            self.relationship_type.set_options(options)

    @on(Button.Pressed, '#add-link-button-save')
    def handle_save(self) -> None:
        selection = self.relationship_type.selection
        work_item_value = self.linked_work_item_key.value

        if not selection or not work_item_value:
            self.notify('Select the type of link and the work item', title='Link Work Items')
            return

        link_type_id, link_type = selection.split(':')
        self.dismiss(
            {
                'right_work_item_key': work_item_value,
                'link_type': link_type,
                'link_type_id': link_type_id,
            }
        )

    @on(Button.Pressed, '#add-link-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss({})
