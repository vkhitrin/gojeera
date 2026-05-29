from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Button, Label, Select, Static

from gojeera.utils.work_item_templates import (
    TEMPLATE_NAME_FIELD,
    WorkItemTemplate,
    WorkItemTemplateError,
    WorkItemTemplatePayloadError,
    list_work_item_template_files,
    load_work_item_template,
    prepare_work_item_template_payload,
)
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.selection.vim_select import VimSelect

TEMPLATE_METADATA_PLACEHOLDER = 'Details will be shown once a template has been selected'


@dataclass(frozen=True)
class WorkItemTemplateRecord:
    id: str
    display_name: str
    path: Path
    template: WorkItemTemplate
    field_count: int

    @property
    def metadata(self) -> str:
        return f'{self.field_count} field(s) • {self.path.name}'


@dataclass(frozen=True)
class InvalidWorkItemTemplateRecord:
    path: Path
    error: str


class WorkItemTemplatePickerScreen(ExtendedModalScreen[tuple[str, WorkItemTemplate] | None]):
    """Modal screen for selecting a configured work item template."""

    is_submitting: reactive[bool] = reactive(False)
    templates_loaded: reactive[bool] = reactive(False)

    DEFAULT_CSS = (
        ExtendedModalScreen.DEFAULT_CSS
        + """
    WorkItemTemplatePickerScreen #modal_outer {
        width: 80;
        height: auto;
        max-height: 80%;
    }

    WorkItemTemplatePickerScreen #template-field {
        height: auto;
        padding: 0 2 1 2;
    }

    WorkItemTemplatePickerScreen #template-selector {
        width: 100%;
    }

    WorkItemTemplatePickerScreen #template-metadata {
        height: auto;
        margin: 0;
        padding: 0;
        color: $text-muted;
    }
    """
    )

    def __init__(
        self,
        on_use_template: Callable[[tuple[str, WorkItemTemplate]], object | Awaitable[object]]
        | None = None,
    ) -> None:
        super().__init__()
        self._on_use_template = on_use_template
        self._templates: dict[str, WorkItemTemplateRecord] = {}
        self._invalid_templates: list[InvalidWorkItemTemplateRecord] = []

    @staticmethod
    def _display_name(template_id: str, template: WorkItemTemplate) -> str:
        return str(template.get(TEMPLATE_NAME_FIELD) or template_id)

    @staticmethod
    def _field_count(template: WorkItemTemplate) -> int:
        return len([field_id for field_id in template if field_id != TEMPLATE_NAME_FIELD])

    @classmethod
    def _build_record(cls, template_path: Path) -> WorkItemTemplateRecord:
        template = load_work_item_template(template_path)
        template_id = template_path.stem
        return WorkItemTemplateRecord(
            id=template_id,
            display_name=cls._display_name(template_id, template),
            path=template_path,
            template=template,
            field_count=cls._field_count(template),
        )

    @classmethod
    def _load_template_records(
        cls,
    ) -> tuple[dict[str, WorkItemTemplateRecord], list[InvalidWorkItemTemplateRecord]]:
        templates: dict[str, WorkItemTemplateRecord] = {}
        invalid_templates: list[InvalidWorkItemTemplateRecord] = []
        for template_file in list_work_item_template_files():
            try:
                record = cls._build_record(template_file)
                templates[record.id] = record
            except (OSError, WorkItemTemplateError) as error:
                invalid_templates.append(
                    InvalidWorkItemTemplateRecord(path=template_file, error=str(error))
                )
        return templates, invalid_templates

    async def _reload_templates_async(self, *, selection: str | None = None) -> None:
        self.templates_loaded = False
        self.template_selector.disabled = True
        try:
            self._templates, self._invalid_templates = await asyncio.to_thread(
                self._load_template_records
            )
            self._refresh_selector_options(selection=selection)
            self._notify_invalid_templates()
        finally:
            self.templates_loaded = True
            if self.is_mounted:
                self.template_selector.disabled = False

    @property
    def template_selector(self) -> VimSelect:
        return self.query_one('#template-selector', VimSelect)

    @property
    def template_metadata(self) -> Static:
        return self.query_one('#template-metadata', Static)

    @property
    def use_button(self) -> Button:
        return self.query_one('#use-template-button', Button)

    @property
    def create_button(self) -> Button:
        return self.query_one('#create-work-item-from-template-button', Button)

    @property
    def cancel_button(self) -> Button:
        return self.query_one('#cancel-template-button', Button)

    @property
    def modal_footer(self) -> Horizontal:
        return self.query_one('#modal_footer', Horizontal)

    def _selector_options(self) -> list[tuple[str, str]]:
        return [(record.display_name, record.id) for record in self._templates.values()]

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()

        with VerticalSuppressClicks(id='modal_outer'):
            yield Label('Work Item Templates', id='modal_title')
            with VerticalScroll(id='modal-form-scroll', classes='modal-form modal-form--fields'):
                with Vertical(id='template-field'):
                    template_label = Label('Template')
                    template_label.add_class('field_label')
                    yield template_label
                    yield VimSelect(
                        options=self._selector_options(),
                        prompt='Select template',
                        id='template-selector',
                        classes='surface-input-select',
                        allow_blank=True,
                        compact=True,
                    )
                    yield Static(TEMPLATE_METADATA_PLACEHOLDER, id='template-metadata')

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button,
                    button_id='use-template-button',
                    label='Use Template',
                    disabled=True,
                )
                yield build_modal_confirm_button(
                    Button,
                    button_id='create-work-item-from-template-button',
                    label='Create Work Item',
                    disabled=True,
                )
                yield build_modal_cancel_button(Button, button_id='cancel-template-button')

        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        self.activate_modal_actions(self.template_selector, jump_mode='focus')
        self.activate_modal_actions(
            self.use_button,
            self.create_button,
            self.cancel_button,
            focus=False,
        )
        self.run_worker(self._reload_templates_async(), exclusive=True, group='work-item-templates')

    def _notify_invalid_templates(self) -> None:
        if not self._invalid_templates:
            return
        self.notify(
            f'{len(self._invalid_templates)} invalid template file(s) were skipped.',
            title='Work Item Templates',
            severity='warning',
        )

    def _selected_template_record(self) -> WorkItemTemplateRecord | None:
        selected_name = self.template_selector.selection
        if not selected_name:
            return None
        return self._templates.get(selected_name)

    def _selected_template(self) -> tuple[str, WorkItemTemplate] | None:
        if record := self._selected_template_record():
            return record.id, record.template
        return None

    async def _create_work_item_from_template(self, template: WorkItemTemplate) -> None:
        self._set_submitting(True)
        try:
            application = cast(Any, self.app)
            payload = await prepare_work_item_template_payload(application.api, template)
            response = await application.api.create_work_item(
                payload.base_data,
                payload.available_fields,
                **payload.dynamic_fields,
            )
            if not response.success or not response.result:
                self.notify(
                    f'Failed to create the work item: {response.error}',
                    title='Create Work Item',
                    severity='error',
                )
                return
            self.notify('Work item created successfully', title=response.result.key)
            self.dismiss((response.result.key, template))
        except WorkItemTemplatePayloadError as error:
            self.notify(str(error), title='Work Item Templates', severity='error')
        finally:
            if self.is_mounted:
                self._set_submitting(False)

    def _set_submitting(self, submitting: bool) -> None:
        self.is_submitting = submitting
        self.modal_footer.loading = submitting
        self.use_button.disabled = submitting
        self.create_button.disabled = submitting
        self.cancel_button.disabled = submitting
        if not submitting:
            self._sync_buttons_and_metadata()

    def _sync_buttons_and_metadata(self) -> None:
        selected_template = self._selected_template_record()
        disabled = selected_template is None or self.is_submitting or not self.templates_loaded
        self.use_button.disabled = disabled
        self.create_button.disabled = disabled
        self.template_metadata.update(
            selected_template.metadata if selected_template else TEMPLATE_METADATA_PLACEHOLDER
        )

    def _refresh_selector_options(self, *, selection: str | None = None) -> None:
        self.template_selector.replace_options(self._selector_options(), selection=selection)
        self._sync_buttons_and_metadata()

    @on(Select.Changed, '#template-selector')
    def handle_template_changed(self) -> None:
        self._sync_buttons_and_metadata()

    async def _invoke_use_template_callback(
        self,
        selected_template: tuple[str, WorkItemTemplate],
    ) -> None:
        await asyncio.sleep(0)
        if self._on_use_template is None:
            return
        result = self._on_use_template(selected_template)
        if isawaitable(result):
            await cast(Awaitable[Any], result)

    @on(Button.Pressed)
    def handle_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'use-template-button':
            selected_template = self._selected_template()
            if selected_template is None:
                return
            self.dismiss(selected_template)
            asyncio.create_task(self._invoke_use_template_callback(selected_template))
            return

        if event.button.id == 'create-work-item-from-template-button':
            selected_template = self._selected_template_record()
            if selected_template is None:
                return
            self.run_worker(
                self._create_work_item_from_template(selected_template.template),
                exclusive=False,
            )
            return

        if event.button.id == 'cancel-template-button':
            self.dismiss()
