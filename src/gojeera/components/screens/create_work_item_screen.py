import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from gojeera.app import JiraApp
    from gojeera.internal.models.work_items import JiraWorkItem

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static, TextArea
from textual.widgets._select import InvalidSelectValueError
from textual.worker import get_current_worker
from textual_tags import Tag

from gojeera.components.screens.description_actions import DescriptionActionsMixin
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.store.cache import get_cache, run_cache_io
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.data.fields import (
    CustomFieldType,
    FieldMode,
    get_parent_relation_field_ids_from_fields_data,
    get_sprint_field_id_from_fields_data,
    is_epic_work_item_type,
)
from gojeera.utils.markdown.adf_helpers import convert_adf_to_markdown
from gojeera.utils.ui.focus import focus_first_available
from gojeera.utils.ui.widgets_factory_utils import (
    DynamicFieldsWidgets,
    StaticFieldsWidgets,
    build_dynamic_widgets,
)
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.dynamic_modal_screen import DynamicModalScreen
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.markdown.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.navigation.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.selection.lazy_select import LazySelect
from gojeera.widgets.selection.multi_select import MultiSelect
from gojeera.widgets.selection.user_picker import UserPicker as UserPicker
from gojeera.widgets.work_item.work_item_labels import WorkItemLabels

logger = logging.getLogger('gojeera')
SKIP_FIELDS = [
    'project',
    'issuetype',
    'reporter',
    'summary',
    'description',
    'parent',
    'issuelinks',
    'attachment',
    'assignee',
]
PROCESS_OPTIONAL_FIELDS = ['duedate', 'priority']


class AddWorkItemScreen(DescriptionActionsMixin, DynamicModalScreen[dict[str, object | None]]):
    TITLE = 'Create Work Item'

    def __init__(
        self,
        project_key: str | None = None,
        reporter_account_id: str | None = None,
        parent_work_item: 'JiraWorkItem | None' = None,
        initial_template: dict[str, object] | None = None,
    ):
        super().__init__()
        self._initial_template = initial_template or {}
        template_project_key = self._extract_template_project_key(self._initial_template)
        self._project_key = project_key or template_project_key
        self._reporter_account_id = reporter_account_id
        self._parent_work_item = parent_work_item
        self._parent_work_item_key = parent_work_item.key if parent_work_item else None
        self._field_metadata: dict[str, dict] = {}
        self._available_field_keys: set[str] = set()
        self._reporter_is_editable: bool = True

        self._selected_project_key: str | None = self._project_key

        self._types_fetched_for_project: str | None = None
        self._users_fetched_for_project: str | None = None
        self._metadata_loaded_for: tuple[str, str] | None = None
        self._loading_metadata_for: tuple[str, str] | None = None
        self._selected_work_item_type_id: str | None = None
        self._sprint_field_id: str | None = None

        self._cache = get_cache()
        self._created_work_item_key: str | None = None
        self._is_submitting: bool = False

    @staticmethod
    def _extract_template_project_key(template: dict[str, object]) -> str | None:
        project = template.get('project')
        if isinstance(project, dict):
            project_data = cast(dict[str, object], project)
            key = project_data.get('key')
            return str(key) if key else None
        return str(project) if project else None

    @staticmethod
    def _extract_template_work_item_type_name(template: dict[str, object]) -> str | None:
        work_item_type = template.get('issuetype')
        if isinstance(work_item_type, dict):
            work_item_type_data = cast(dict[str, object], work_item_type)
            name = work_item_type_data.get('name')
            return str(name) if name else None
        return str(work_item_type) if work_item_type else None

    def _apply_initial_template_primary_fields(self) -> None:
        if not self._initial_template:
            return

        if summary := self._initial_template.get('summary'):
            self.summary_field.value = str(summary)

        description = self._initial_template.get('description')
        if isinstance(description, dict):
            self.description_field.text = convert_adf_to_markdown(description, base_url=None)
        elif description:
            self.description_field.text = str(description)

        self.save_button.disabled = not self._validate_required_fields()

    @property
    def _parent_work_item_type_name(self) -> str | None:
        parent_type = (
            self._parent_work_item.parent_work_item_type if self._parent_work_item else None
        )
        if self._parent_work_item and self._parent_work_item.work_item_type:
            parent_type = self._parent_work_item.work_item_type.name
        return parent_type

    @property
    def _sprint_inherited_from_parent(self) -> bool:
        return bool(self._parent_work_item_key) and not is_epic_work_item_type(
            self._parent_work_item_type_name
        )

    @property
    def _requires_subtask_issue_type(self) -> bool:
        return bool(self._parent_work_item_key) and not is_epic_work_item_type(
            self._parent_work_item_type_name
        )

    def _filter_work_item_types_for_parent(self, types: list[Any]) -> list[Any]:
        if not self._parent_work_item:
            return [t for t in types if not t.subtask]

        parent_type = self._parent_work_item.work_item_type
        if not parent_type:
            if self._parent_work_item_key:
                return [t for t in types if t.subtask]
            return [t for t in types if not t.subtask]

        if parent_type.subtask:
            return []

        parent_level = parent_type.hierarchy_level
        if parent_level == 0:
            return [t for t in types if t.subtask]

        if parent_level is not None:
            child_level = parent_level - 1
            return [t for t in types if not t.subtask and t.hierarchy_level == child_level]

        if self._parent_work_item_key:
            return [t for t in types if t.subtask]

        return [t for t in types if not t.subtask]

    @property
    def modal_title(self) -> Static:
        return self.query_one('#modal_title', Static)

    @property
    def save_button(self) -> Button:
        return self.query_one('#add-work-item-button-save', expect_type=Button)

    @property
    def cancel_button(self) -> Button:
        return self.query_one('#add-work-item-button-quit', expect_type=Button)

    @property
    def project_selector(self) -> LazySelect:
        return self.query_one('#create-work-item-select-project', LazySelect)

    @property
    def work_item_type_selector(self) -> LazySelect:
        return self.query_one('#create-work-item-select-type', LazySelect)

    @property
    def reporter_selector(self) -> LazySelect:
        return self.query_one('#create-work-item-select-reporter', LazySelect)

    @property
    def assignee_selector(self) -> LazySelect:
        return self.query_one('#create-work-item-select-assignee', LazySelect)

    @property
    def summary_field(self) -> Input:
        return self.query_one('#create-work-item-summary', Input)

    @property
    def description_field(self) -> ExtendedADFMarkdownTextArea:
        return self.query_one(ExtendedADFMarkdownTextArea)

    @property
    def static_fields_container(self) -> StaticFieldsWidgets:
        return self.query_one(StaticFieldsWidgets)

    @property
    def dynamic_fields_container(self) -> DynamicFieldsWidgets:
        return self.query_one(DynamicFieldsWidgets)

    @property
    def sprint_picker_widget(self) -> MultiSelect:
        return self.query_one('#sprint', MultiSelect)

    @property
    def required_tracker(self) -> Static:
        return self.query_one('#required-fields-tracker', Static)

    @property
    def description_textarea(self) -> TextArea:
        return self.description_field.query_one(TextArea)

    @property
    def modal_outer(self) -> VerticalSuppressClicks:
        return self.query_one('#modal_outer', VerticalSuppressClicks)

    @property
    def modal_form_scroll(self) -> VerticalScroll:
        return self.query_one('#modal-form-scroll', VerticalScroll)

    @property
    def modal_footer(self) -> Horizontal:
        return self.query_one('#modal_footer', Horizontal)

    @property
    def work_item_type_field_container(self) -> Widget:
        return self.query_one('#work-item-type-field-container')

    @property
    def reporter_field_container(self) -> Widget:
        return self.query_one('#reporter-field-container')

    @property
    def assignee_field_container(self) -> Widget:
        return self.query_one('#assignee-field-container')

    @property
    def summary_field_container(self) -> Widget:
        return self.query_one('#summary-field-container')

    @property
    def description_field_container(self) -> Widget:
        return self.query_one('#description-field-container')

    @property
    def sprint_field_container(self) -> Widget:
        return self.query_one('#sprint-field-container')

    def _set_primary_field_containers_display(self, visible: bool) -> None:
        self.work_item_type_field_container.display = visible
        self.reporter_field_container.display = visible
        self.assignee_field_container.display = visible
        self.summary_field_container.display = visible
        self.description_field_container.display = visible

    def _default_reporter_account_id(self) -> str | None:
        if self._reporter_account_id:
            return self._reporter_account_id

        app = cast('JiraApp', self.app)
        return (
            app.atlassian_context.user_info.account_id if app.atlassian_context.user_info else None
        )

    def _validate_required_fields(self) -> bool:
        pending_fields = []

        project_value = self.project_selector.value
        work_item_type_value = self.work_item_type_selector.value
        reporter_value = self.reporter_selector.value if self._reporter_is_editable else True

        if not project_value or project_value == Select.NULL:
            pending_fields.append('Project')
        if not work_item_type_value or work_item_type_value == Select.NULL:
            pending_fields.append('Issue Type')
        if not self.summary_field.value:
            pending_fields.append('Summary')

        if self._reporter_is_editable:
            if not reporter_value or reporter_value == Select.NULL:
                pending_fields.append('Reporter')

        desc_text = self.description_field.text.strip()
        desc_required = self.description_field.required
        if desc_required and not desc_text:
            pending_fields.append('Description')

        dynamic_pending = self._get_pending_dynamic_fields()
        pending_fields.extend(dynamic_pending)

        try:
            tracker = self.required_tracker
            if pending_fields:
                tracker.update(
                    f'⚠ Required: {len(pending_fields)} pending ({", ".join(pending_fields)})'
                )
                tracker.add_class('pending')
                tracker.remove_class('complete')
            else:
                tracker.update('Required: All fields complete ✓')
                tracker.remove_class('pending')
                tracker.add_class('complete')
        except Exception:
            pass

        return len(pending_fields) == 0

    def _get_pending_dynamic_fields(self) -> list[str]:
        from gojeera.widgets.inputs.date_input import DateInput
        from gojeera.widgets.inputs.date_time_input import DateTimeInput
        from gojeera.widgets.inputs.numeric_input import NumericInput
        from gojeera.widgets.inputs.text_input import TextInput
        from gojeera.widgets.inputs.url import URL
        from gojeera.widgets.selection.multi_select import MultiSelect
        from gojeera.widgets.selection.selection import SelectionWidget
        from gojeera.widgets.selection.user_picker import UserPicker
        from gojeera.widgets.work_item.work_item_labels import WorkItemLabels
        from gojeera.utils.ui.widgets_factory_utils import DynamicFieldWrapper

        pending_fields = []

        for wrapper in self.dynamic_fields_container.query(DynamicFieldWrapper):
            if not wrapper.required:
                continue

            widget = wrapper.widget
            if widget is None or not widget.is_attached:
                continue

            field_name = getattr(
                widget,
                'label_text',
                getattr(widget, 'title', getattr(widget, 'field_id', 'Unknown')),
            )
            is_empty = False

            if isinstance(widget, (TextInput, NumericInput, URL)):
                is_empty = not widget.value or not str(widget.value).strip()
            elif isinstance(widget, (SelectionWidget, UserPicker)):
                is_empty = not widget.value or widget.value == Select.NULL
            elif isinstance(widget, (DateInput, DateTimeInput)):
                is_empty = not widget.value or not widget.value.strip()
            elif isinstance(widget, MultiSelect):
                is_empty = not widget.selected_tags
            elif isinstance(widget, WorkItemLabels):
                is_empty = not widget.value

            if is_empty:
                pending_fields.append(field_name)

        return pending_fields

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('Create Work Item', id='modal_title')
            with VerticalScroll(id='modal-form-scroll'):
                with StaticFieldsWidgets():
                    with Vertical(id='project-field-container'):
                        label = Label('Project')
                        label.add_class('field_label')
                        label.add_class('required_field_label')
                        yield label
                        project_widget = LazySelect(
                            lazy_load_callback=lambda: self.fetch_projects(),
                            options=[],
                            prompt='Select a project',
                            id='create-work-item-select-project',
                            classes='surface-input-select',
                            type_to_search=True,
                            compact=True,
                        )
                        yield project_widget

                    with Vertical(id='work-item-type-field-container'):
                        label = Label('Issue Type')
                        label.add_class('field_label')
                        label.add_class('required_field_label')
                        yield label
                        work_item_type_widget = LazySelect(
                            lazy_load_callback=lambda: self._lazy_load_work_item_types(),
                            options=[],
                            prompt='Select a work item type',
                            id='create-work-item-select-type',
                            classes='surface-input-select',
                            type_to_search=True,
                            compact=True,
                        )
                        yield work_item_type_widget

                    with Vertical(id='reporter-field-container'):
                        label = Label('Reporter')
                        label.add_class('field_label')
                        label.add_class('required_field_label')
                        yield label
                        reporter_widget = LazySelect(
                            lazy_load_callback=lambda: self._lazy_load_users(),
                            options=[],
                            prompt='Select a reporter',
                            id='create-work-item-select-reporter',
                            classes='surface-input-select',
                            type_to_search=True,
                            compact=True,
                        )
                        yield reporter_widget

                    with Vertical(id='assignee-field-container'):
                        assignee_label = Label('Assignee')
                        assignee_label.add_class('field_label')
                        yield assignee_label
                        assignee_widget = LazySelect(
                            lazy_load_callback=lambda: self._lazy_load_users(),
                            options=[],
                            prompt='Select an assignee',
                            id='create-work-item-select-assignee',
                            classes='surface-input-select',
                            type_to_search=True,
                            compact=True,
                        )
                        yield assignee_widget

                    with Vertical(id='sprint-field-container') as sprint_container:
                        sprint_container.display = False
                        sprint_label = Label('Sprint')
                        sprint_label.add_class('field_label')
                        yield sprint_label
                        yield MultiSelect(
                            mode=FieldMode.CREATE,
                            field_id='sprint',
                            options=[],
                            title='Sprint',
                        )

                with Vertical(id='summary-field-container'):
                    label = Label('Summary')
                    label.add_class('field_label')
                    label.add_class('required_field_label')
                    yield label
                    summary_widget = ExtendedInput(
                        id='create-work-item-summary',
                        placeholder='',
                        compact=True,
                    )
                    summary_widget.add_class('required')
                    yield summary_widget

                yield from self.compose_description_field()

                yield DynamicFieldsWidgets()

            with Horizontal(id='modal_footer'):
                yield build_modal_confirm_button(
                    Button,
                    button_id='add-work-item-button-save',
                    disabled=True,
                )
                yield build_modal_cancel_button(Button, button_id='add-work-item-button-quit')

            yield Static(
                'Required fields will appear after selecting a project',
                id='required-fields-tracker',
            )
        yield ExtendedFooter()

    def on_mount(self):
        if self._parent_work_item_key:
            if self._requires_subtask_issue_type:
                self.modal_title.update(f'Create Subtask For {self._parent_work_item_key}')
            else:
                self.modal_title.update(f'Create Work Item For {self._parent_work_item_key}')
        else:
            self.modal_title.update('Create Work Item')

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.project_selector, 'focus')
            set_jump_mode(self.work_item_type_selector, 'focus')
            set_jump_mode(self.reporter_selector, 'focus')
            set_jump_mode(self.assignee_selector, 'focus')
            set_jump_mode(self.sprint_picker_widget, 'focus')

            set_jump_mode(self.summary_field, 'focus')

            self.description_field.make_jumpable()

            set_jump_mode(self.save_button, 'click')
            set_jump_mode(self.cancel_button, 'click')

        self._set_primary_field_containers_display(False)
        self.dynamic_fields_container.display = False
        self.initialize_dynamic_modal()
        if self._project_key:
            self.call_after_refresh(self._initialize_prefilled_form)
        else:
            self.call_after_refresh(lambda: focus_first_available(self.project_selector))

    def apply_dynamic_modal_layout(self) -> None:
        content_height = sum(
            child.outer_size.height
            for child in self.modal_form_scroll.children
            if getattr(child, 'display', True)
        )
        chrome_height = (
            self.modal_title.outer_size.height
            + self.modal_footer.outer_size.height
            + self.required_tracker.outer_size.height
        )
        viewport_cap = max(16, int(self.screen.size.height * 0.9))
        minimum_height = 8
        self.modal_outer.styles.height = min(
            viewport_cap,
            max(minimum_height, content_height + chrome_height),
        )

    def _initialize_prefilled_form(self) -> None:
        """Preload project-dependent fields when the screen opens with a predefined project."""

        self.fetch_projects()

    def _apply_prefilled_subtask_type(self, project_key: str, work_item_type_id: str) -> None:
        """Apply the derived subtask type after the selector options have rendered."""

        with self.prevent(Select.Changed):
            self.work_item_type_selector.value = work_item_type_id
        self.work_item_type_selector.disabled = True

        self._selected_work_item_type_id = work_item_type_id
        self.dynamic_fields_container.display = True

        target = (project_key, work_item_type_id)
        if self._metadata_loaded_for != target and self._loading_metadata_for != target:
            self.run_worker(
                self.fetch_work_item_create_metadata(project_key, work_item_type_id),
                exclusive=False,
            )

        self.schedule_dynamic_modal_layout()
        self.save_button.disabled = not self._validate_required_fields()
        self.call_after_refresh(lambda: focus_first_available(self.summary_field))

    def _apply_single_available_subtask_type(
        self,
        types_list: list[tuple[str, str]],
        project_key: str,
    ) -> None:
        if (
            not self._requires_subtask_issue_type
            or self._selected_work_item_type_id
            or len(types_list) != 1
        ):
            return

        work_item_type_id = types_list[0][1]
        self.call_after_refresh(
            lambda: self._apply_prefilled_subtask_type(project_key, work_item_type_id)
        )

    def _make_dynamic_widgets_jumpable(self) -> None:
        from gojeera.utils.ui.widgets_factory_utils import DynamicFieldWrapper

        for wrapper in self.dynamic_fields_container.query(DynamicFieldWrapper):
            if hasattr(wrapper, 'widget') and wrapper.widget:
                widget = wrapper.widget

                if isinstance(widget, (Select, Input, TextArea)):
                    set_jump_mode(widget, 'focus')
                elif hasattr(widget, 'can_focus') and widget.can_focus:
                    set_jump_mode(widget, 'focus')

    def _populate_project_selector(
        self, projects_list: list[tuple[str, str]], *, project_key: str | None
    ) -> None:
        with self.prevent(Select.Changed):
            self.project_selector.set_options(projects_list)

        if not project_key:
            return

        with self.prevent(Select.Changed):
            self.project_selector.value = project_key

        if self._parent_work_item_key:
            self.project_selector.disabled = True

        self._selected_project_key = project_key
        self._set_primary_field_containers_display(True)
        self._lazy_load_work_item_types()
        self._lazy_load_users()
        self.schedule_dynamic_modal_layout()
        self.save_button.disabled = not self._validate_required_fields()

    def fetch_projects(self) -> None:
        self._fetch_projects_worker()

    @work(exclusive=False, group='fetch-projects')
    async def _fetch_projects_worker(self) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            cached_projects = await run_cache_io(self._cache.get_projects)
            if cached_projects is not None:
                try:
                    projects_list = [(f'{p.name} ({p.key})', p.key) for p in cached_projects]
                    self._populate_project_selector(projects_list, project_key=self._project_key)
                except Exception:
                    pass
                return

            application = cast('JiraApp', self.app)  # noqa: F821
            response = await application.api.search_projects()

            if response.success and response.result:
                projects = response.result or []
                projects.sort(key=lambda x: x.name)

                await run_cache_io(lambda: self._cache.set_projects(projects))

                projects_list = [(f'{p.name} ({p.key})', p.key) for p in projects]

                try:
                    self._populate_project_selector(projects_list, project_key=self._project_key)
                except Exception:
                    pass
            else:
                self.notify(
                    f'Failed to fetch projects: {response.error}',
                    severity='error',
                    title='Create Work Item',
                )

                try:
                    self.project_selector._stop_spinner()
                except Exception:
                    pass

    def _lazy_load_work_item_types(self) -> None:
        if not self._selected_project_key:
            self.notify(
                'Please select a project first', severity='warning', title='Create Work Item'
            )

            try:
                self.work_item_type_selector._stop_spinner()
            except Exception:
                pass
            return

        if self._types_fetched_for_project == self._selected_project_key:
            try:
                self.work_item_type_selector._stop_spinner()
            except Exception:
                pass
            return

        self._fetch_work_item_types_worker(self._selected_project_key)

    @work(exclusive=False, group='fetch-types')
    async def _fetch_work_item_types_worker(self, project_key: str) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            try:
                cached_types = await run_cache_io(
                    lambda: self._cache.get_project_work_item_types(project_key)
                )
                if cached_types is not None:
                    types = self._filter_work_item_types_for_parent(cached_types)
                    types.sort(key=lambda x: x.name)
                    types_list = [(t.name, t.id) for t in types]
                    self._types_fetched_for_project = project_key
                    with self.prevent(Select.Changed):
                        self.work_item_type_selector.set_options(types_list)
                    self._apply_template_work_item_type_selection(types_list, project_key)
                    self._apply_single_available_subtask_type(types_list, project_key)
                    return

                application = cast('JiraApp', self.app)  # noqa: F821
                response = await application.api.get_work_item_types_for_project(project_key)

                if response.success and response.result:
                    types = response.result or []

                    await run_cache_io(
                        lambda: self._cache.set_project_work_item_types(project_key, types)
                    )
                    types = self._filter_work_item_types_for_parent(types)

                    types.sort(key=lambda x: x.name)
                    types_list = [(t.name, t.id) for t in types]

                    with self.prevent(Select.Changed):
                        self.work_item_type_selector.set_options(types_list)
                    self._types_fetched_for_project = project_key
                    self._apply_template_work_item_type_selection(types_list, project_key)
                    self._apply_single_available_subtask_type(types_list, project_key)
                else:
                    self.notify(
                        f'Failed to fetch work item types: {response.error}',
                        severity='error',
                        title='Create Work Item',
                    )
                    self.work_item_type_selector._stop_spinner()
            except Exception as e:
                self.notify(
                    f'Error fetching work item types: {str(e)}',
                    severity='error',
                    title='Create Work Item',
                )
                self.work_item_type_selector._stop_spinner()
        else:
            self.work_item_type_selector._stop_spinner()

    def _apply_template_work_item_type_selection(
        self,
        types_list: list[tuple[str, str]],
        project_key: str,
    ) -> None:
        if not self._initial_template or self._selected_work_item_type_id:
            return
        template_type_name = self._extract_template_work_item_type_name(self._initial_template)
        if not template_type_name:
            return
        for type_name, type_id in types_list:
            if type_name != template_type_name:
                continue
            with self.prevent(Select.Changed):
                self.work_item_type_selector.value = type_id
            self._selected_work_item_type_id = type_id
            self.dynamic_fields_container.display = True
            self._apply_initial_template_primary_fields()
            if self._metadata_loaded_for != (project_key, type_id):
                self.run_worker(
                    self.fetch_work_item_create_metadata(project_key, type_id),
                    exclusive=False,
                )
            self.schedule_dynamic_modal_layout()
            return

    def _lazy_load_users(self) -> None:
        if not self._selected_project_key:
            self.notify(
                'Please select a project first', severity='warning', title='Create Work Item'
            )

            try:
                self.reporter_selector._stop_spinner()
            except Exception:
                pass
            try:
                self.assignee_selector._stop_spinner()
            except Exception:
                pass
            return

        if self._users_fetched_for_project == self._selected_project_key:
            try:
                self.reporter_selector._stop_spinner()
                self.assignee_selector._stop_spinner()
            except Exception:
                pass
            return

        self._fetch_users_worker(self._selected_project_key)

    @work(exclusive=False, group='fetch-users')
    async def _fetch_users_worker(self, project_key: str) -> None:
        worker = get_current_worker()

        def stop_user_spinners() -> None:
            try:
                self.reporter_selector._stop_spinner()
                self.assignee_selector._stop_spinner()
            except Exception:
                pass

        if not worker.is_cancelled:
            try:
                application = cast('JiraApp', self.app)  # noqa: F821
                cached_users = await run_cache_io(
                    lambda: self._cache.get_project_users(project_key)
                )
                if cached_users is not None:
                    users_result = cached_users
                else:
                    response = await application.api.search_users_assignable_to_projects(
                        project_keys=[project_key],
                        active=True,
                    )
                    if not (response.success and response.result):
                        self.notify(
                            f'Failed to fetch users: {response.error}',
                            severity='error',
                            title='Create Work Item',
                        )
                        stop_user_spinners()
                        return
                    users_result = response.result or []
                    await run_cache_io(
                        lambda: self._cache.set_project_users(project_key, users_result)
                    )

                if users_result:
                    users_list = [(user.display_name, user.account_id) for user in users_result]
                    default_reporter_account_id = self._default_reporter_account_id()
                    if (
                        default_reporter_account_id
                        and application.atlassian_context.user_info
                        and all(
                            account_id != default_reporter_account_id
                            for _, account_id in users_list
                        )
                    ):
                        users_list.insert(
                            0,
                            (
                                application.atlassian_context.user_info.display_name,
                                application.atlassian_context.user_info.account_id,
                            ),
                        )

                    try:
                        self.reporter_selector.set_options(users_list)

                        if default_reporter_account_id:
                            self.reporter_selector.value = default_reporter_account_id

                            self.save_button.disabled = not self._validate_required_fields()

                        self.assignee_selector.set_options(users_list)

                        self._users_fetched_for_project = project_key
                    except Exception:
                        pass
            except Exception as e:
                self.notify(
                    f'Error fetching users: {str(e)}', severity='error', title='Create Work Item'
                )
                stop_user_spinners()
        else:
            stop_user_spinners()

    @on(Select.Changed, '#create-work-item-select-project')
    def handle_project_selection(self) -> None:
        project_value = self.project_selector.value
        if project_value and project_value != Select.NULL:
            self._selected_project_key = str(project_value)
        else:
            self._selected_project_key = None

        with self.app.batch_update():
            if self._selected_project_key:
                self._set_primary_field_containers_display(True)

                self._types_fetched_for_project = None
                self._users_fetched_for_project = None
                self._metadata_loaded_for = None
                self._loading_metadata_for = None
                self._selected_work_item_type_id = None

                try:
                    self.work_item_type_selector.clear()
                    self.reporter_selector.clear()
                    self.assignee_selector.clear()

                    self.work_item_type_selector._has_loaded = False
                    self.reporter_selector._has_loaded = False
                    self.assignee_selector._has_loaded = False
                except Exception:
                    pass

                self._lazy_load_users()
                self.schedule_dynamic_modal_layout()

            self.save_button.disabled = not self._validate_required_fields()

    @on(Select.Changed, '#create-work-item-select-type')
    def handle_work_item_type_selection(self) -> None:
        project_value = self.project_selector.value
        work_item_type_value = self.work_item_type_selector.value

        self._selected_work_item_type_id = (
            str(work_item_type_value)
            if work_item_type_value and work_item_type_value != Select.NULL
            else None
        )

        if (
            project_value
            and project_value != Select.NULL
            and work_item_type_value
            and work_item_type_value != Select.NULL
        ):
            self.dynamic_fields_container.display = True
            self.schedule_dynamic_modal_layout()

            combo = (str(project_value), str(work_item_type_value))
            if self._metadata_loaded_for != combo and self._loading_metadata_for != combo:
                self.run_worker(
                    self.fetch_work_item_create_metadata(
                        str(project_value), str(work_item_type_value)
                    ),
                )

        self.save_button.disabled = not self._validate_required_fields()

    @on(Select.Changed, '#create-work-item-select-reporter')
    def handle_reporter_selection(self) -> None:
        self.save_button.disabled = not self._validate_required_fields()

    @on(Input.Blurred, '#create-work-item-summary')
    def handle_summary_blurred(self, event: Input.Blurred) -> None:
        if event.value is not None:
            self.summary_field.value = event.value.strip()
        self.save_button.disabled = not self._validate_required_fields()

    @on(TextArea.Changed, '#description-textarea')
    def handle_description_value_change(self, _event: TextArea.Changed):
        self.save_button.disabled = not self._validate_required_fields()

    @on(Tag.Selected)
    def handle_tag_selected(self):
        self.save_button.disabled = not self._validate_required_fields()

    @on(Tag.Removed)
    def handle_tag_removed(self):
        self.save_button.disabled = not self._validate_required_fields()

    async def fetch_work_item_create_metadata(
        self, project_key: str, work_item_type_id: str
    ) -> None:
        target = (project_key, work_item_type_id)
        if self._metadata_loaded_for == target or self._loading_metadata_for == target:
            return

        self._loading_metadata_for = target

        self._sprint_field_id = None
        try:
            self.sprint_field_container.display = False
            self.sprint_picker_widget.loading = False
            self.sprint_picker_widget.set_options_state(
                {'options': [], 'selection': [], 'field_supports_update': True}
            )
        except Exception:
            pass

        self.dynamic_fields_container.loading = True

        application = cast('JiraApp', self.app)
        config = CONFIGURATION.get()

        response: APIControllerResponse = await application.api.get_work_item_create_metadata(
            project_key, work_item_type_id
        )

        try:
            if isinstance(response, Exception):
                self.dynamic_fields_container.loading = False
                self.notify(
                    f'Error fetching metadata: {str(response)}',
                    severity='error',
                    title='Create Work Item',
                )
                return

            if not response.success or not response.result:
                self.dynamic_fields_container.loading = False

                self.notify(
                    'Unable to find the required information for creating work items.',
                    severity='error',
                    title='Create Work Item',
                )
                return

            fields_data = response.result.get('fields', [])
            self._available_field_keys = {
                str(field_key) for field in fields_data if (field_key := field.get('key'))
            }
            for field in fields_data:
                field_id = field.get('fieldId')
                if field_id:
                    self._field_metadata[field_id] = field

                if field_id == 'description' and field.get('required', False):
                    self.description_field.mark_required()

                    try:
                        desc_container = self.description_field_container
                        desc_label = desc_container.query_one(Label)
                        desc_label.add_class('required_field_label')
                    except Exception:
                        pass

                if field_id == 'reporter':
                    operations = field.get('operations', [])
                    self._reporter_is_editable = 'set' in operations

                    if self._reporter_is_editable:
                        self.reporter_selector.display = True

                        if (
                            self._default_reporter_account_id()
                            and self.reporter_selector.value == Select.NULL
                        ):
                            try:
                                self.reporter_selector.value = self._default_reporter_account_id()
                            except InvalidSelectValueError:
                                pass
                            else:
                                self.save_button.disabled = not self._validate_required_fields()
                    else:
                        self.reporter_selector.display = False

            ignore_list = config.create_additional_fields_ignore_ids or []
            enable_additional = config.enable_creating_additional_fields

            skip_fields = set(SKIP_FIELDS) | set(ignore_list)
            skip_fields.update(get_parent_relation_field_ids_from_fields_data(fields_data))

            sprint_field_id = get_sprint_field_id_from_fields_data(fields_data)
            if sprint_field_id:
                skip_fields.add(sprint_field_id)

            metadata_fields: list[Widget] = build_dynamic_widgets(
                mode=FieldMode.CREATE,
                fields_data=fields_data,
                current_values=self._initial_template,
                skip_fields=skip_fields,
                enable_additional=enable_additional,
                process_optional_fields=set(PROCESS_OPTIONAL_FIELDS),
            )
            self.dynamic_fields_container.loading = False
            await self.dynamic_fields_container.remove_children()
            await self.dynamic_fields_container.mount_all(metadata_fields)
            self.save_button.disabled = not self._validate_required_fields()
            self.schedule_dynamic_modal_layout()

            self._make_dynamic_widgets_jumpable()

            if (
                sprint_field_id
                and config.enable_sprint_selection
                and not self._sprint_inherited_from_parent
            ):
                try:
                    self._sprint_field_id = sprint_field_id
                    self.sprint_field_container.display = True
                    self.sprint_picker_widget.loading = True
                    self.run_worker(
                        self._populate_sprint_picker_widgets(project_key), exclusive=False
                    )
                    self.schedule_dynamic_modal_layout()
                except Exception:
                    pass
            user_picker_widgets = list(self.dynamic_fields_container.query(UserPicker))
            if user_picker_widgets:
                await self._load_project_users_into_pickers(
                    project_key,
                    user_picker_widgets,
                )

            self._metadata_loaded_for = target
        finally:
            if self._loading_metadata_for == target:
                self._loading_metadata_for = None

    def _format_field_value(
        self, field_id: str, value: Any, field_metadata: dict, widget: Widget | None = None
    ) -> Any:

        if not value:
            return None

        schema = field_metadata.get('schema', {})
        custom_type = schema.get('custom')
        schema_type = schema.get('type')

        if schema_type == 'priority':
            if isinstance(value, dict) and 'id' in value:
                return value['id']
            return value

        if widget and isinstance(widget, MultiSelect):
            return value

        if custom_type == CustomFieldType.USER_PICKER.value:
            return {'accountId': value}

        elif custom_type == CustomFieldType.FLOAT.value:
            if value:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            return None

        elif (
            schema.get('type') == 'array'
            and schema.get('items') == 'string'
            and field_id == 'labels'
        ):
            if widget and isinstance(widget, WorkItemLabels):
                return value if isinstance(value, list) else []

            elif isinstance(value, str):
                labels = [label.strip() for label in value.split(',') if label.strip()]
                return labels
            elif isinstance(value, list):
                return value
            else:
                return []

        elif field_metadata.get('allowedValues'):
            if schema_type == 'array':
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    return value
                if isinstance(value, list):
                    return [{'id': v} for v in value]
                else:
                    return [{'id': value}]
            else:
                if isinstance(value, dict):
                    return value
                return {'id': value}

        return value

    async def _populate_user_picker_widgets(self, project_key: str) -> None:
        """Populate user picker widgets with available users for the project.

        Args:
            project_key: The project key to fetch users for
        """
        user_picker_widgets = list(self.dynamic_fields_container.query(UserPicker))

        if not user_picker_widgets:
            return

        try:
            await self._load_project_users_into_pickers(
                project_key,
                user_picker_widgets,
            )
        except Exception:
            logger.warning(
                'Failed to fetch users for project %s',
                project_key,
                exc_info=True,
            )

    async def _load_project_users_into_pickers(
        self,
        project_key: str,
        user_picker_widgets: list[UserPicker],
    ) -> None:
        application = cast('JiraApp', self.app)
        users_response = await application.api.search_users_assignable_to_projects(
            project_keys=[project_key],
            active=True,
        )
        if users_response.success and users_response.result:
            users_data = {'users': users_response.result, 'selection': None}
            for user_picker in user_picker_widgets:
                user_picker.users = users_data

    async def _populate_sprint_picker_widgets(self, project_key: str) -> None:
        application = cast('JiraApp', self.app)

        config = CONFIGURATION.get()
        if not config.enable_sprint_selection or self._sprint_inherited_from_parent:
            try:
                self.sprint_picker_widget.loading = False
            except Exception:
                pass
            return

        try:
            sprint_picker = self.sprint_picker_widget
        except Exception:
            return

        def clear_sprint_picker() -> None:
            sprint_picker.set_options_state(
                {'options': [], 'selection': [], 'field_supports_update': True}
            )
            try:
                self.sprint_field_container.display = False
            except Exception:
                pass

        try:
            sprints_response = await application.api.get_sprints_for_project(project_key)
            if sprints_response.success and sprints_response.result:
                sprints_list = [(sprint.name, str(sprint.id)) for sprint in sprints_response.result]
                sprint_picker.set_options_state(
                    {
                        'options': sprints_list,
                        'selection': [],
                        'field_supports_update': True,
                    }
                )
            else:
                clear_sprint_picker()
        except Exception:
            logger.warning(
                'Failed to fetch sprints for project %s',
                project_key,
                exc_info=True,
            )
            clear_sprint_picker()
        finally:
            try:
                sprint_picker.loading = False
            except Exception:
                pass

    @on(Button.Pressed, '#add-work-item-button-save')
    def handle_save(self) -> None:
        if not self._validate_required_fields():
            self.notify('All required values (*) must be provided.', title='Create Work Item')
            return
        self.run_worker(self._create_work_item(), exclusive=True)

    @on(Button.Pressed, '#add-work-item-button-quit')
    def handle_cancel(self) -> None:
        if self._is_submitting:
            return
        self.dismiss()

    def _set_submitting(self, submitting: bool) -> None:
        self._is_submitting = submitting
        self.modal_footer.loading = submitting
        self.save_button.disabled = submitting
        self.cancel_button.disabled = submitting

    def dismiss_on_backdrop_click(self) -> None:
        if self._is_submitting:
            return
        super().dismiss_on_backdrop_click()

    def _collect_create_payload(self) -> dict[str, object | None]:
        project_value = self.project_selector.value
        work_item_type_value = self.work_item_type_selector.value
        assignee_value = self.assignee_selector.value
        reporter_value = self.reporter_selector.value

        data: dict[str, object | None] = {
            'project_key': project_value if project_value != Select.NULL else None,
            'work_item_type_id': (
                work_item_type_value if work_item_type_value != Select.NULL else None
            ),
            'assignee_account_id': assignee_value if assignee_value != Select.NULL else None,
            'summary': self.summary_field.value,
            'description': self.description_field.text.strip()
            if self.description_field.text
            else None,
        }

        if self._reporter_is_editable:
            data['reporter_account_id'] = reporter_value if reporter_value != Select.NULL else None

        if self._parent_work_item_key:
            data['parent_key'] = self._parent_work_item_key

        from gojeera.utils.ui.widgets_factory_utils import DynamicFieldWrapper

        for wrapper in self.dynamic_fields_container.children:
            if not isinstance(wrapper, DynamicFieldWrapper):
                continue

            widget = wrapper.widget
            if not widget:
                continue

            field_id = widget.id
            if not field_id:
                continue

            value = wrapper.get_value_for_create()
            if field_id == 'duedate':
                if value:
                    data[field_id] = value
                continue

            if value and field_id in self._field_metadata:
                field_meta = self._field_metadata[field_id]
                formatted_value = self._format_field_value(field_id, value, field_meta, widget)
                if formatted_value is not None:
                    data[field_id] = formatted_value
            elif value:
                data[field_id] = value

        sprint_picker = self.sprint_picker_widget
        if (
            self._sprint_field_id
            and sprint_picker.is_mounted
            and not self._sprint_inherited_from_parent
        ):
            sprint_ids = sprint_picker.get_selected_option_int_ids()
            sprint_value = (
                sprint_ids[0] if len(sprint_ids) == 1 else sprint_ids if sprint_ids else None
            )
            if sprint_value is not None:
                data[self._sprint_field_id] = sprint_value

        return data

    async def _create_work_item(self) -> None:
        application = cast('JiraApp', self.app)
        data = self._collect_create_payload()

        base_fields = {
            'project_key',
            'parent_key',
            'work_item_type_id',
            'assignee_account_id',
            'reporter_account_id',
            'summary',
            'description',
            'duedate',
            'priority',
        }
        base_data = {k: v for k, v in data.items() if k in base_fields}
        dynamic_fields = {k: v for k, v in data.items() if k not in base_fields}

        self._set_submitting(True)
        if self._created_work_item_key is None:
            response: APIControllerResponse = await application.api.create_work_item(
                base_data,
                available_fields=self._available_field_keys,
                **dynamic_fields,
            )
            if not response.success or not response.result:
                self.notify(
                    f'Failed to create the work item: {response.error}',
                    severity='error',
                    title='Create Work Item',
                )
                self._set_submitting(False)
                return

            self._created_work_item_key = response.result.key
            self.notify(
                'Work item created successfully',
                title=response.result.key,
            )

        self.dismiss(
            {
                'created_work_item_key': self._created_work_item_key,
                'parent_key': data.get('parent_key'),
            }
        )

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return

        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def action_insert_mention(self) -> None:
        """Show user picker and insert mention at cursor position."""
        from gojeera.utils.ui.mention_helpers import insert_user_mention

        try:
            description_widget = self.description_field
        except Exception:
            logger.error('Failed to get Description widget', exc_info=True)
            return

        await insert_user_mention(
            app=self.app,
            target_widget=description_widget,
            project_key=self._selected_project_key,
            cache=self._cache,
        )
