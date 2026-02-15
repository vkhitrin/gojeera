import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from gojeera.app import JiraApp

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Footer, Input, Label, Select, Static, TextArea
from textual.worker import get_current_worker
from textual_tags import Tag

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION
from gojeera.constants import PROCESS_OPTIONAL_FIELDS, SKIP_FIELDS, CustomFieldType
from gojeera.utils.fields import FieldMode, get_sprint_field_id_from_fields_data
from gojeera.utils.widgets_factory_utils import (
    DynamicFieldsWidgets,
    StaticFieldsWidgets,
    build_dynamic_widgets,
)
from gojeera.widgets.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.lazy_select import LazySelect
from gojeera.widgets.multi_select import MultiSelect
from gojeera.widgets.sprint_picker import SprintPicker
from gojeera.widgets.user_picker import UserPicker as UserPicker
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.work_item_labels import WorkItemLabels

logger = logging.getLogger('gojeera')


class AddWorkItemScreen(ModalScreen):
    BINDINGS = [
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]
    TITLE = 'New Work Item'

    def __init__(
        self,
        project_key: str | None = None,
        reporter_account_id: str | None = None,
        parent_work_item_key: str | None = None,
    ):
        super().__init__()
        self._project_key = project_key
        self._reporter_account_id = reporter_account_id
        self._parent_work_item_key = parent_work_item_key
        self._field_metadata: dict[str, dict] = {}
        self._reporter_is_editable: bool = True

        self._selected_project_key: str | None = project_key

        self._types_fetched_for_project: str | None = None
        self._users_fetched_for_project: str | None = None
        self._metadata_fetched_for: tuple[str, str] | None = None
        self._sprint_field_id: str | None = None

        self._cache = get_cache()

    @property
    def modal_title(self) -> Static:
        return self.query_one('#modal_title', Static)

    @property
    def save_button(self) -> Button:
        return self.query_one('#add-work-item-button-save', expect_type=Button)

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
    def sprint_picker_widget(self) -> SprintPicker:
        return self.query_one('#sprint', SprintPicker)

    @property
    def required_tracker(self) -> Static:
        return self.query_one('#required-fields-tracker', Static)

    def _validate_required_fields(self) -> bool:
        pending_fields = []

        project_value = self.project_selector.value
        work_item_type_value = self.work_item_type_selector.value
        reporter_value = self.reporter_selector.value if self._reporter_is_editable else True

        if not project_value or project_value == Select.BLANK:
            pending_fields.append('Project')
        if not work_item_type_value or work_item_type_value == Select.BLANK:
            pending_fields.append('Issue Type')
        if not self.summary_field.value:
            pending_fields.append('Summary')

        if self._reporter_is_editable:
            if not reporter_value or reporter_value == Select.BLANK:
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
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        return len(pending_fields) == 0

    def _get_pending_dynamic_fields(self) -> list[str]:
        from gojeera.widgets.date_input import DateInput
        from gojeera.widgets.date_time_input import DateTimeInput
        from gojeera.widgets.multi_select import MultiSelect
        from gojeera.widgets.numeric_input import NumericInput
        from gojeera.widgets.selection import SelectionWidget
        from gojeera.widgets.text_input import TextInput
        from gojeera.widgets.url import URL
        from gojeera.widgets.user_picker import UserPicker
        from gojeera.widgets.work_item_labels import WorkItemLabels

        pending_fields = []

        dynamic_widgets = []

        seen_widget_ids = set()

        def add_unique_widgets(widget_list):
            """Helper to add widgets only if not already seen."""
            for widget in widget_list:
                widget_id = id(widget)
                if widget_id not in seen_widget_ids and widget.is_attached:
                    seen_widget_ids.add(widget_id)
                    dynamic_widgets.append(widget)

        add_unique_widgets(self.dynamic_fields_container.query(TextInput))
        add_unique_widgets(self.dynamic_fields_container.query(NumericInput))
        add_unique_widgets(self.dynamic_fields_container.query(SelectionWidget))
        add_unique_widgets(self.dynamic_fields_container.query(UserPicker))
        add_unique_widgets(self.dynamic_fields_container.query(DateInput))
        add_unique_widgets(self.dynamic_fields_container.query(DateTimeInput))
        add_unique_widgets(self.dynamic_fields_container.query(URL))
        add_unique_widgets(self.dynamic_fields_container.query(MultiSelect))
        add_unique_widgets(self.dynamic_fields_container.query(WorkItemLabels))

        for widget in dynamic_widgets:
            is_required = False
            if hasattr(widget, 'required'):
                is_required = widget.required
            elif hasattr(widget, '_required'):
                is_required = widget._required

            if not is_required:
                continue

            field_name = getattr(
                widget,
                'label_text',
                getattr(widget, 'title', getattr(widget, 'field_id', 'Unknown')),
            )
            is_empty = False

            if isinstance(widget, (TextInput, NumericInput, URL)):
                if not widget.value or not str(widget.value).strip():
                    is_empty = True

            elif isinstance(widget, (SelectionWidget, UserPicker)):
                if not widget.value or widget.value == Select.BLANK:
                    is_empty = True

            elif isinstance(widget, (DateInput, DateTimeInput)):
                if not widget.value or not widget.value.strip():
                    is_empty = True

            elif isinstance(widget, MultiSelect):
                if not widget.selected_tags or len(widget.selected_tags) == 0:
                    is_empty = True

            elif isinstance(widget, WorkItemLabels):
                if not widget.value or len(widget.value) == 0:
                    is_empty = True

            if is_empty:
                pending_fields.append(field_name)

        return pending_fields

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('New Work Item', id='modal_title')
            with VerticalScroll(id='add-work-item-form'):
                with StaticFieldsWidgets():
                    with Vertical(id='project-field-container'):
                        label = Label('Project').add_class('field_label')
                        label.add_class('required_field_label')
                        yield label
                        project_widget = LazySelect(
                            lazy_load_callback=lambda: self.fetch_projects(),
                            options=[],
                            prompt='Select a project',
                            id='create-work-item-select-project',
                            type_to_search=True,
                            compact=True,
                        )
                        yield project_widget

                    with Vertical(id='work-item-type-field-container'):
                        label = Label('Issue Type').add_class('field_label')
                        label.add_class('required_field_label')
                        yield label
                        work_item_type_widget = LazySelect(
                            lazy_load_callback=lambda: self._lazy_load_work_item_types(),
                            options=[],
                            prompt='Select a work item type',
                            id='create-work-item-select-type',
                            type_to_search=True,
                            compact=True,
                        )
                        yield work_item_type_widget

                    with Vertical(id='reporter-field-container'):
                        label = Label('Reporter').add_class('field_label')
                        label.add_class('required_field_label')
                        yield label
                        reporter_widget = LazySelect(
                            lazy_load_callback=lambda: self._lazy_load_users(),
                            options=[],
                            prompt='Select a reporter',
                            id='create-work-item-select-reporter',
                            type_to_search=True,
                            compact=True,
                        )
                        yield reporter_widget

                    with Vertical(id='assignee-field-container'):
                        yield Label('Assignee').add_class('field_label')
                        assignee_widget = LazySelect(
                            lazy_load_callback=lambda: self._lazy_load_users(),
                            options=[],
                            prompt='Select an assignee',
                            id='create-work-item-select-assignee',
                            type_to_search=True,
                            compact=True,
                        )
                        yield assignee_widget

                    with Vertical(id='sprint-field-container') as sprint_container:
                        sprint_container.display = False
                        yield Label('Sprint').add_class('field_label')
                        yield SprintPicker(
                            mode=FieldMode.CREATE,
                            field_id='sprint',
                            title='Sprint',
                        )

                with Vertical(id='summary-field-container'):
                    label = Label('Summary').add_class('field_label')
                    label.add_class('required_field_label')
                    yield label
                    summary_widget = Input(
                        id='create-work-item-summary',
                        placeholder='',
                        compact=True,
                    )
                    summary_widget.add_class(*['work_item_details_input_field', 'required'])
                    yield summary_widget

                with Vertical(id='description-field-container'):
                    yield (Label('Description').add_class('field_label'))

                    yield ExtendedADFMarkdownTextArea(field_id='description', required=False)

                yield DynamicFieldsWidgets()

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id='add-work-item-button-save',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel', variant='error', id='add-work-item-button-quit', compact=True
                )

            yield Static('Required: 0 pending', id='required-fields-tracker')
        yield Footer()

    def on_mount(self):
        if self._parent_work_item_key:
            self.modal_title.update(f'New Subtask For {self._parent_work_item_key}')
        else:
            self.modal_title.update('New Work Item')

        if CONFIGURATION.get().jumper.enabled:
            self.project_selector.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.work_item_type_selector.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.reporter_selector.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.assignee_selector.jump_mode = 'focus'  # type: ignore[attr-defined]

            self.summary_field.jump_mode = 'focus'  # type: ignore[attr-defined]

            self.description_field.make_jumpable()

            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#add-work-item-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

        self.query_one('#work-item-type-field-container').display = False
        self.query_one('#reporter-field-container').display = False
        self.query_one('#assignee-field-container').display = False
        self.query_one('#summary-field-container').display = False
        self.query_one('#description-field-container').display = False
        self.dynamic_fields_container.display = False

        if self._project_key:
            self.fetch_projects()

    def _make_dynamic_widgets_jumpable(self) -> None:
        from gojeera.utils.widgets_factory_utils import DynamicFieldWrapper

        for wrapper in self.dynamic_fields_container.query(DynamicFieldWrapper):
            if hasattr(wrapper, 'widget') and wrapper.widget:
                widget = wrapper.widget

                if isinstance(widget, (Select, Input, TextArea)):
                    widget.jump_mode = 'focus'  # type: ignore[attr-defined]
                elif hasattr(widget, 'can_focus') and widget.can_focus:
                    widget.jump_mode = 'focus'  # type: ignore[attr-defined]

    def fetch_projects(self) -> None:
        cached_projects = self._cache.get('projects')
        if cached_projects is not None:
            try:
                project_selector = self.query_one('#create-work-item-select-project', LazySelect)
                projects_list = [(f'{p.name} ({p.key})', p.key) for p in cached_projects]
                project_selector.set_options(projects_list)

                if self._project_key:
                    project_selector.value = self._project_key

                    if self._parent_work_item_key:
                        project_selector.disabled = True

                    self._selected_project_key = self._project_key

                    self.query_one('#work-item-type-field-container').display = True
                    self.query_one('#reporter-field-container').display = True
                    self.query_one('#assignee-field-container').display = True
                    self.query_one('#summary-field-container').display = True
                    self.query_one('#description-field-container').display = True

                    self._lazy_load_work_item_types()
                    self._lazy_load_users()

                    self.save_button.disabled = not self._validate_required_fields()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')
            return

        self._fetch_projects_worker()

    @work(exclusive=False, group='fetch-projects')
    async def _fetch_projects_worker(self) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            application = cast('JiraApp', self.app)  # noqa: F821
            response = await application.api.search_projects()

            if response.success and response.result:
                projects = response.result or []
                projects.sort(key=lambda x: x.name)

                self._cache.set('projects', projects)

                projects_list = [(f'{p.name} ({p.key})', p.key) for p in projects]

                try:
                    project_selector = self.query_one(
                        '#create-work-item-select-project', LazySelect
                    )
                    project_selector.set_options(projects_list)

                    if self._project_key:
                        project_selector.value = self._project_key

                        if self._parent_work_item_key:
                            project_selector.disabled = True

                        self._selected_project_key = self._project_key

                        self.query_one('#work-item-type-field-container').display = True
                        self.query_one('#reporter-field-container').display = True
                        self.query_one('#assignee-field-container').display = True
                        self.query_one('#summary-field-container').display = True
                        self.query_one('#description-field-container').display = True

                        self._lazy_load_work_item_types()
                        self._lazy_load_users()

                        self.save_button.disabled = not self._validate_required_fields()
                except Exception as e:
                    logger.debug(f'Exception occurred: {e}')
            else:
                self.notify(
                    f'Failed to fetch projects: {response.error}',
                    severity='error',
                    title='Create Work Item',
                )

                try:
                    project_selector = self.query_one(
                        '#create-work-item-select-project', LazySelect
                    )
                    project_selector._stop_spinner()
                except Exception as e:
                    logger.debug(f'Exception occurred: {e}')

    def _lazy_load_work_item_types(self) -> None:
        if not self._selected_project_key:
            self.notify(
                'Please select a project first', severity='warning', title='Create Work Item'
            )

            try:
                type_selector = self.query_one('#create-work-item-select-type', LazySelect)
                type_selector._stop_spinner()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')
            return

        cache_key = self._selected_project_key
        cached_types = self._cache.get('project_types_raw', cache_key)
        if cached_types is not None:
            types = cached_types
            if self._parent_work_item_key:
                types = [t for t in types if t.subtask]
            else:
                types = [t for t in types if not t.subtask]

            types.sort(key=lambda x: x.name)
            types_list = [(t.name, t.id) for t in types]

            self._types_fetched_for_project = cache_key
            try:
                type_selector = self.query_one('#create-work-item-select-type', LazySelect)
                type_selector.set_options(types_list)

                if self._parent_work_item_key and types_list:
                    type_selector.value = types_list[0][1]
                    type_selector.disabled = True

                    self._selected_work_item_type_id = types_list[0][1]
                    self.dynamic_fields_container.display = True

                    if self._metadata_fetched_for != (cache_key, types_list[0][1]):
                        self.run_worker(
                            self.fetch_work_item_create_metadata(cache_key, types_list[0][1]),
                        )

                    self.save_button.disabled = not self._validate_required_fields()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')
            return

        if self._types_fetched_for_project == self._selected_project_key:
            return

        self._fetch_work_item_types_worker(self._selected_project_key)

    @work(exclusive=False, group='fetch-types')
    async def _fetch_work_item_types_worker(self, project_key: str) -> None:
        worker = get_current_worker()
        type_selector = self.query_one('#create-work-item-select-type', LazySelect)

        if not worker.is_cancelled:
            try:
                application = cast('JiraApp', self.app)  # noqa: F821
                response = await application.api.get_work_item_types_for_project(project_key)

                if response.success and response.result:
                    types = response.result or []

                    self._cache.set('project_types_raw', types, project_key)

                    if self._parent_work_item_key:
                        types = [t for t in types if t.subtask]
                    else:
                        types = [t for t in types if not t.subtask]

                    types.sort(key=lambda x: x.name)
                    types_list = [(t.name, t.id) for t in types]

                    type_selector.set_options(types_list)
                    self._types_fetched_for_project = project_key

                    if self._parent_work_item_key and types_list:
                        type_selector.value = types_list[0][1]
                        type_selector.disabled = True

                        self._selected_work_item_type_id = types_list[0][1]
                        self.dynamic_fields_container.display = True

                        if self._metadata_fetched_for != (project_key, types_list[0][1]):
                            await self.fetch_work_item_create_metadata(
                                project_key, types_list[0][1]
                            )

                        self.save_button.disabled = not self._validate_required_fields()
                else:
                    self.notify(
                        f'Failed to fetch work item types: {response.error}',
                        severity='error',
                        title='Create Work Item',
                    )
                    type_selector._stop_spinner()
            except Exception as e:
                self.notify(
                    f'Error fetching work item types: {str(e)}',
                    severity='error',
                    title='Create Work Item',
                )
                type_selector._stop_spinner()
        else:
            type_selector._stop_spinner()

    def _lazy_load_users(self) -> None:
        if not self._selected_project_key:
            self.notify(
                'Please select a project first', severity='warning', title='Create Work Item'
            )

            try:
                self.reporter_selector._stop_spinner()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')
            try:
                self.assignee_selector._stop_spinner()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')
            return

        cache_key = self._selected_project_key
        cached_users = self._cache.get('project_users_tuples', cache_key)
        if cached_users is not None:
            self._users_fetched_for_project = cache_key
            try:
                reporter_selector = self.query_one('#create-work-item-select-reporter', LazySelect)
                reporter_selector.set_options(cached_users)

                if self._reporter_account_id:
                    reporter_selector.value = self._reporter_account_id

                    self.save_button.disabled = not self._validate_required_fields()

                assignee_selector = self.query_one('#create-work-item-select-assignee', LazySelect)
                assignee_selector.set_options(cached_users)
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')
            return

        if self._users_fetched_for_project == self._selected_project_key:
            return

        self._fetch_users_worker(self._selected_project_key)

    @work(exclusive=False, group='fetch-users')
    async def _fetch_users_worker(self, project_key: str) -> None:
        worker = get_current_worker()

        if not worker.is_cancelled:
            try:
                application = cast('JiraApp', self.app)  # noqa: F821
                response = await application.api.search_users_assignable_to_projects(
                    project_keys=[project_key],
                    active=True,
                )

                if response.success and response.result:
                    users_list = [(user.display_name, user.account_id) for user in response.result]

                    self._cache.set('project_users_tuples', users_list, project_key)

                    try:
                        reporter_selector = self.query_one(
                            '#create-work-item-select-reporter', LazySelect
                        )
                        reporter_selector.set_options(users_list)

                        if self._reporter_account_id:
                            reporter_selector.value = self._reporter_account_id

                            self.save_button.disabled = not self._validate_required_fields()

                        assignee_selector = self.query_one(
                            '#create-work-item-select-assignee', LazySelect
                        )
                        assignee_selector.set_options(users_list)

                        self._users_fetched_for_project = project_key
                    except Exception as e:
                        logger.debug(f'Exception occurred: {e}')
                else:
                    self.notify(
                        f'Failed to fetch users: {response.error}',
                        severity='error',
                        title='Create Work Item',
                    )
                    try:
                        self.reporter_selector._stop_spinner()
                        self.assignee_selector._stop_spinner()
                    except Exception as e:
                        logger.debug(f'Exception occurred: {e}')
            except Exception as e:
                self.notify(
                    f'Error fetching users: {str(e)}', severity='error', title='Create Work Item'
                )
                try:
                    self.reporter_selector._stop_spinner()
                    self.assignee_selector._stop_spinner()
                except Exception as e:
                    logger.debug(f'Exception occurred: {e}')
        else:
            try:
                self.reporter_selector._stop_spinner()
                self.assignee_selector._stop_spinner()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

    @on(Select.Changed, '#create-work-item-select-project')
    def handle_project_selection(self) -> None:
        project_value = self.project_selector.value
        if project_value and project_value != Select.BLANK:
            self._selected_project_key = str(project_value)
        else:
            self._selected_project_key = None

        with self.app.batch_update():
            if self._selected_project_key:
                self.query_one('#work-item-type-field-container').display = True
                self.query_one('#reporter-field-container').display = True
                self.query_one('#assignee-field-container').display = True
                self.query_one('#summary-field-container').display = True
                self.query_one('#description-field-container').display = True

                self._types_fetched_for_project = None
                self._users_fetched_for_project = None
                self._metadata_fetched_for = None

                try:
                    work_item_type_sel = self.query_one('#create-work-item-select-type', LazySelect)
                    reporter_sel = self.query_one('#create-work-item-select-reporter', LazySelect)
                    assignee_sel = self.query_one('#create-work-item-select-assignee', LazySelect)

                    work_item_type_sel.clear()
                    reporter_sel.clear()
                    assignee_sel.clear()

                    work_item_type_sel._has_loaded = False
                    reporter_sel._has_loaded = False
                    assignee_sel._has_loaded = False
                except Exception as e:
                    logger.debug(f'Exception occurred: {e}')

                self._lazy_load_users()

            self.save_button.disabled = not self._validate_required_fields()

    @on(Select.Changed, '#create-work-item-select-type')
    def handle_work_item_type_selection(self) -> None:
        project_value = self.project_selector.value
        work_item_type_value = self.work_item_type_selector.value

        if (
            project_value
            and project_value != Select.BLANK
            and work_item_type_value
            and work_item_type_value != Select.BLANK
        ):
            self.dynamic_fields_container.display = True

            combo = (str(project_value), str(work_item_type_value))
            if self._metadata_fetched_for != combo:
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
    def handle_description_value_change(self, event: TextArea.Changed):
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
        if self._metadata_fetched_for == (project_key, work_item_type_id):
            return

        self._metadata_fetched_for = (project_key, work_item_type_id)

        self.dynamic_fields_container.loading = True

        application = cast('JiraApp', self.app)
        config = CONFIGURATION.get()

        response: APIControllerResponse = await application.api.get_work_item_create_metadata(
            project_key, work_item_type_id
        )

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
        else:
            fields_data = response.result.get('fields', [])
            for field in fields_data:
                field_id = field.get('fieldId')
                if field_id:
                    self._field_metadata[field_id] = field

                if field_id == 'description' and field.get('required', False):
                    self.description_field.mark_required()

                    try:
                        desc_container = self.query_one('#description-field-container', Vertical)
                        desc_label = desc_container.query_one(Label)
                        desc_label.add_class('required_field_label')
                    except Exception as e:
                        logger.debug(f'Exception occurred: {e}')

                if field_id == 'reporter':
                    operations = field.get('operations', [])
                    self._reporter_is_editable = 'set' in operations

                    if self._reporter_is_editable:
                        self.reporter_selector.display = True

                        if (
                            self._reporter_account_id
                            and self.reporter_selector.value == Select.BLANK
                        ):
                            self.reporter_selector.value = self._reporter_account_id

                            self.save_button.disabled = not self._validate_required_fields()
                    else:
                        self.reporter_selector.display = False

            ignore_list = config.create_additional_fields_ignore_ids or []
            enable_additional = config.enable_creating_additional_fields

            skip_fields = set(SKIP_FIELDS) | set(ignore_list)

            sprint_field_id = get_sprint_field_id_from_fields_data(fields_data)
            if sprint_field_id:
                skip_fields.add(sprint_field_id)

            metadata_fields: list[Widget] = build_dynamic_widgets(
                mode=FieldMode.CREATE,
                fields_data=fields_data,
                current_values=None,
                skip_fields=skip_fields,
                enable_additional=enable_additional,
                process_optional_fields=set(PROCESS_OPTIONAL_FIELDS),
            )
            self.dynamic_fields_container.loading = False
            await self.dynamic_fields_container.remove_children()
            await self.dynamic_fields_container.mount_all(metadata_fields)

            self._make_dynamic_widgets_jumpable()

            if sprint_field_id and config.enable_sprint_selection:
                try:
                    self._sprint_field_id = sprint_field_id
                    sprint_container = self.query_one('#sprint-field-container')
                    sprint_container.display = True
                    self.sprint_picker_widget.start_loading()
                    self.run_worker(
                        self._populate_sprint_picker_widgets(project_key), exclusive=False
                    )
                except Exception:
                    pass

            user_picker_widgets = self.dynamic_fields_container.query(UserPicker)
            if user_picker_widgets:
                users_response = await application.api.search_users_assignable_to_projects(
                    project_keys=[project_key],
                    active=True,
                )
                if users_response.success and users_response.result:
                    users_data = {'users': users_response.result, 'selection': None}
                    for user_picker in user_picker_widgets:
                        user_picker.users = users_data

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
                if isinstance(value, list):
                    return [{'id': v} for v in value]
                else:
                    return [{'id': value}]
            else:
                return {'id': value}

        return value

    async def _populate_user_picker_widgets(self, project_key: str) -> None:
        """Populate user picker widgets with available users for the project.

        Args:
            project_key: The project key to fetch users for
        """
        application = cast('JiraApp', self.app)
        user_picker_widgets = self.dynamic_fields_container.query(UserPicker)

        if not user_picker_widgets:
            return

        try:
            users_response = await application.api.search_users_assignable_to_projects(
                project_keys=[project_key],
                active=True,
            )
            if users_response.success and users_response.result:
                users_data = {'users': users_response.result, 'selection': None}
                for user_picker in user_picker_widgets:
                    user_picker.users = users_data
        except Exception as e:
            logger.warning(f'Failed to fetch users for project {project_key}: {e}')

    async def _populate_sprint_picker_widgets(self, project_key: str) -> None:
        application = cast('JiraApp', self.app)

        config = CONFIGURATION.get()
        if not config.enable_sprint_selection:
            return

        try:
            sprint_picker = self.sprint_picker_widget
        except Exception:
            return

        try:
            sprints_response = await application.api.get_sprints_for_project(project_key)
            if sprints_response.success and sprints_response.result:
                sprints_list = [(sprint.name, sprint.id) for sprint in sprints_response.result]
                sprints_data = {'sprints': sprints_list, 'selection': None}
                sprint_picker.sprints = sprints_data
            else:
                sprint_picker.sprints = {'sprints': [], 'selection': None}
                try:
                    self.query_one('#sprint-field-container').display = False
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f'Failed to fetch sprints for project {project_key}: {e}')
            sprint_picker.sprints = {'sprints': [], 'selection': None}
            try:
                self.query_one('#sprint-field-container').display = False
            except Exception:
                pass

    @on(Button.Pressed, '#add-work-item-button-save')
    def handle_save(self) -> None:
        if not self._validate_required_fields():
            self.notify('All required values (*) must be provided.', title='Create Work Item')
        else:
            project_value = self.project_selector.value
            work_item_type_value = self.work_item_type_selector.value
            assignee_value = self.assignee_selector.value
            reporter_value = self.reporter_selector.value

            data = {
                'project_key': project_value if project_value != Select.BLANK else None,
                'work_item_type_id': work_item_type_value
                if work_item_type_value != Select.BLANK
                else None,
                'assignee_account_id': assignee_value if assignee_value != Select.BLANK else None,
                'summary': self.summary_field.value,
                'description': self.description_field.text.strip()
                if self.description_field.text
                else None,
            }

            if self._reporter_is_editable:
                data['reporter_account_id'] = (
                    reporter_value if reporter_value != Select.BLANK else None
                )

            if self._parent_work_item_key:
                data['parent_key'] = self._parent_work_item_key

            from gojeera.utils.widgets_factory_utils import DynamicFieldWrapper

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
            if self._sprint_field_id and sprint_picker.is_mounted:
                sprint_value = sprint_picker.get_value_for_create()
                if sprint_value is not None:
                    data[self._sprint_field_id] = sprint_value

            self.notify('Creating the work item...', title='Create Work Item')
            self.dismiss(data)

    @on(Button.Pressed, '#add-work-item-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss({})

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return

        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def action_insert_mention(self) -> None:
        """Show user picker and insert mention at cursor position."""
        from gojeera.utils.mention_helpers import insert_user_mention

        try:
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
        except Exception as e:
            logger.error(f'Failed to get Description widget: {e}')
            return

        await insert_user_mention(
            app=self.app,
            target_widget=description_widget,
            project_key=self._selected_project_key,
            cache=self._cache,
        )

    async def action_insert_decision(self) -> None:
        from textual.widgets import TextArea

        from gojeera.components.decision_picker_screen import DecisionPickerScreen

        try:
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
            textarea = description_widget.query_one(TextArea)
        except Exception as e:
            logger.error(f'Failed to get Description widget or TextArea: {e}')
            return

        cursor_position = textarea.cursor_location

        result = await self.app.push_screen_wait(DecisionPickerScreen())

        if result:
            marker, label = result

            insertion_text = f'> `{marker}` '

            textarea.focus()
            textarea.move_cursor(cursor_position)

            textarea.insert(insertion_text)

    async def action_insert_alert(self) -> None:
        from textual.widgets import TextArea

        from gojeera.components.panel_picker_screen import PanelPickerScreen

        try:
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
            textarea = description_widget.query_one(TextArea)
        except Exception as e:
            logger.error(f'Failed to get Description widget or TextArea: {e}')
            return

        cursor_position = textarea.cursor_location

        result = await self.app.push_screen_wait(PanelPickerScreen())

        if result:
            marker, alert_type = result

            insertion_text = f'> {marker}\n> '

            textarea.focus()
            textarea.move_cursor(cursor_position)

            textarea.insert(insertion_text)

    def on_click(self) -> None:
        self.dismiss({})
