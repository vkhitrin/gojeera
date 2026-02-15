import dataclasses
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from gojeera.utils.adf_helpers import convert_adf_to_markdown


def custom_as_dict_factory(data) -> dict:
    def convert_value(obj):
        if isinstance(obj, Enum):
            return obj.value
        return obj

    return {k: convert_value(v) for k, v in data}


def custom_as_json_dict_factory(data) -> dict:
    def convert_value(obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, Decimal):
            return str(obj)
        return obj

    return {k: convert_value(v) for k, v in data}


class JiraWorkItemGenericFields(Enum):
    """
    Common `fields` that are part of the API response of a work item.
    """

    PROJECT = 'project'
    STATUS = 'status'
    ASSIGNEE = 'assignee'
    REPORTER = 'reporter'
    PRIORITY = 'priority'
    PARENT = 'parent'
    TIME_TRACKING = 'timetracking'
    ATTACHMENT = 'attachment'
    SUMMARY = 'summary'
    DESCRIPTION = 'description'
    CREATED = 'created'
    UPDATED = 'updated'
    WORK_ITEM_TYPE = 'issuetype'
    WORK_ITEM_LINKS = 'issuelinks'
    COMMENT = 'comment'
    RESOLUTION_DATE = 'resolutiondate'
    RESOLUTION = 'resolution'
    LABELS = 'labels'
    DUE_DATE = 'duedate'
    COMPONENTS = 'components'


@dataclass
class BaseModel:
    def as_dict(self) -> dict:
        """Dumps dataclass into dictionary.

        Some objects may be dumped differently e.g. Decimal will be dumped to a string.
        """

        return dataclasses.asdict(self, dict_factory=custom_as_dict_factory)

    def as_json(self) -> dict:
        """Dumps dataclass into json dictionary.

        Some objects may be dumped differently eg. Decimal will be dumped to a string.
        """

        return dataclasses.asdict(self, dict_factory=custom_as_json_dict_factory)


@dataclass
class Project(BaseModel):
    id: str
    name: str
    key: str

    def __str__(self):
        return f'[{self.key}] {self.name}'


@dataclass
class WorkItemStatus(BaseModel):
    id: str
    name: str
    description: str | None = None
    status_category_color: str | None = None


@dataclass
class WorkItemType(BaseModel):
    id: str
    name: str
    subtask: bool = False
    hierarchy_level: int | None = None
    scope_project: Project | None = None


@dataclass
class JiraUser(BaseModel):
    account_id: str
    active: bool
    display_name: str
    email: str | None = None

    @property
    def display_user(self) -> str:
        if email := self.email:
            return email
        elif name := self.display_name:
            return name
        return self.get_account_id()

    def get_account_id(self) -> str:
        return self.account_id or ''


@dataclass
class WorkItemPriority(BaseModel):
    id: str
    name: str


@dataclass
class WorkItemComment(BaseModel):
    id: str
    author: JiraUser
    created: datetime | None = None
    updated: datetime | None = None
    update_author: JiraUser | None = None
    body: dict | str | None = None

    def updated_on(self) -> str:
        if not self.update_author:
            return self.updated.strftime('%Y-%m-%d %H:%M') if self.updated else ''
        return (
            f'{self.updated.strftime("%Y-%m-%d %H:%M")} by {self.update_author.display_name}'
            if self.updated
            else ''
        )

    def created_on(self) -> str:
        return self.updated.strftime('%Y-%m-%d %H:%M') if self.updated else ''

    def get_body(self, base_url: str | None = None) -> str:
        if self.body is None:
            return ''
        if isinstance(self.body, str):
            return self.body
        return convert_adf_to_markdown(self.body, base_url)


@dataclass
class RelatedJiraWorkItem(BaseModel):
    id: str
    key: str
    summary: str
    status: WorkItemStatus
    work_item_type: WorkItemType
    link_type: str = ''
    relation_type: str = ''  # outward/inward
    priority: WorkItemPriority | None = None

    @property
    def priority_name(self) -> str:
        return self.priority.name if self.priority else ''

    def cleaned_summary(self, max_length: int | None = None) -> str:
        if max_length is not None:
            return f'{self.summary.strip()[:max_length]}...'
        return self.summary.strip()

    def display_status(self) -> str:
        if self.status:
            return self.status.name
        return ''


@dataclass
class TimeTracking(BaseModel):
    original_estimate: str | None = None
    remaining_estimate: str | None = None
    time_spent: str | None = None
    original_estimate_seconds: int | None = None
    remaining_estimate_seconds: int | None = None
    time_spent_seconds: int | None = None


@dataclass
class Attachment(BaseModel):
    id: str
    filename: str
    mime_type: str
    size: int
    created: datetime | None = None
    author: JiraUser | None = None

    @property
    def created_date(self) -> str:
        if self.created:
            return datetime.strftime(self.created, '%Y-%m-%d %H:%M')
        return ''

    def get_size(self) -> Decimal | None:
        if self.size is None:
            return None
        return Decimal(self.size / 1024).quantize(Decimal('0.01'))

    @property
    def display_author(self) -> str:
        if author := self.author:
            if email := author.email:
                return email
            elif name := author.display_name:
                return name
            return author.account_id or ''
        return ''

    def get_mime_type(self) -> str:
        return self.mime_type or ''


@dataclass
class JiraSprint(BaseModel):
    id: int
    name: str
    state: str
    boardId: int
    goal: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    completeDate: str | None = None


@dataclass
class JiraBoard(BaseModel):
    id: int
    name: str
    type: str
    projectKey: str | None = None


@dataclass
class JiraBaseWorkItem(BaseModel):
    id: str
    key: str


@dataclass
class JiraWorkItemComponent(BaseModel):
    """A component that can be associated to a work item."""

    id: str
    name: str
    description: str | None = None


@dataclass
class JiraWorkItem(JiraBaseWorkItem):
    summary: str
    status: WorkItemStatus
    project: Project | None = None
    created: datetime | None = None
    updated: datetime | None = None
    due_date: date | None = None
    reporter: JiraUser | None = None
    work_item_type: WorkItemType | None = None
    resolution_date: datetime | None = None
    resolution: str | None = None
    description: dict | str | None = None
    priority: WorkItemPriority | None = None
    assignee: JiraUser | None = None
    comments: list[WorkItemComment] | None = None
    related_work_items: list[RelatedJiraWorkItem] | None = None
    parent_work_item_key: str | None = None
    parent_work_item_type: str | None = None
    time_tracking: TimeTracking | None = None
    labels: list[str] | None = None
    attachments: list[Attachment] | None = None
    sprint: JiraSprint | None = None
    edit_meta: dict | None = None
    custom_fields: dict[str, Any] | None = None
    additional_fields: dict[str, Any] | None = None
    components: list[JiraWorkItemComponent] | None = None

    def cleaned_summary(self, max_length: int | None = None) -> str:
        if max_length is not None:
            if (stripped_summary := self.summary.strip()) and len(
                stripped_summary
            ) > max_length - 3:
                return f'{stripped_summary[: max_length - 3]}...'
        return self.summary.strip()

    def display_status(self) -> str:
        if self.status:
            return f'{self.status.name} ({self.status.id})'
        return ''

    @property
    def status_name(self) -> str:
        if self.status:
            return self.status.name
        return ''

    @property
    def assignee_display_name(self) -> str:
        if self.assignee:
            return self.assignee.display_name
        return ''

    @property
    def work_item_type_name(self) -> str:
        if self.work_item_type:
            return self.work_item_type.name
        return ''

    @property
    def sprint_name(self) -> str:
        if self.sprint:
            return self.sprint.name
        return ''

    @property
    def created_on(self) -> str:
        if self.created:
            return datetime.strftime(self.created, '%Y-%m-%d %H:%M')
        return ''

    @property
    def display_due_date(self) -> str:
        if self.due_date:
            return self.due_date.strftime('%Y-%m-%d')
        return ''

    @property
    def parent_key(self) -> str:
        return self.parent_work_item_key or ''

    @property
    def priority_name(self) -> str:
        return self.priority.name if self.priority else ''

    def get_edit_metadata(self) -> dict | None:
        if not self.edit_meta:
            return None
        return self.edit_meta.get('fields')

    def get_custom_field_value(self, field_id: str) -> Any | None:
        if not field_id:
            return None
        if not self.custom_fields:
            return None
        return self.custom_fields.get(field_id)

    def get_custom_fields(self) -> dict[str, Any]:
        if self.custom_fields is None:
            return {}
        return self.custom_fields

    def get_additional_field_value(self, field_id: str) -> Any | None:
        if not field_id:
            return None
        if not self.additional_fields:
            return None
        return self.additional_fields.get(field_id)

    def get_additional_fields(self) -> dict[str, Any]:
        if self.additional_fields is None:
            return {}
        return self.additional_fields

    def get_description(self, base_url: str | None = None) -> str:
        if self.description is None:
            return ''
        if isinstance(self.description, str):
            return self.description
        return convert_adf_to_markdown(self.description, base_url)

    def __repr__(self) -> str:
        return f'id:{self.id} - key:{self.key}'


@dataclass
class WorkItemRemoteLink(BaseModel):
    id: str
    global_id: str
    relationship: str
    title: str
    summary: str
    url: str | None = None
    status_resolved: bool | None = None


@dataclass
class JiraWorkItemSearchResponse(BaseModel):
    work_items: list[JiraWorkItem]
    next_page_token: str | None = None
    is_last: bool | None = None
    total: int | None = None
    offset: int | None = None


@dataclass
class JiraTimeTrackingConfiguration(BaseModel):
    default_unit: str
    time_format: str
    working_days_per_week: int
    working_hours_per_day: int

    def display_default_unit(self) -> str:
        return self.default_unit or ''

    def display_time_format(self) -> str:
        return self.time_format or ''

    def display_working_days_per_week(self) -> str:
        return str(self.working_days_per_week or '')

    def display_working_hours_per_day(self) -> str:
        return str(self.working_hours_per_day or '')


@dataclass
class JiraGlobalSettings(BaseModel):
    attachments_enabled: bool
    work_item_linking_enabled: bool
    subtasks_enabled: bool
    unassigned_work_items_allowed: bool
    voting_enabled: bool
    watching_enabled: bool
    time_tracking_enabled: bool
    time_tracking_configuration: JiraTimeTrackingConfiguration | None = None

    def display_attachments_enabled(self) -> str:
        return 'Yes' if self.attachments_enabled else 'No'

    def display_subtasks_enabled(self) -> str:
        return 'Yes' if self.subtasks_enabled else 'No'

    def display_work_item_linking_enabled(self) -> str:
        return 'Yes' if self.work_item_linking_enabled else 'No'

    def display_unassigned_work_items_allowed(self) -> str:
        return 'Yes' if self.unassigned_work_items_allowed else 'No'

    def display_voting_enabled(self) -> str:
        return 'Yes' if self.voting_enabled else 'No'

    def display_watching_enabled(self) -> str:
        return 'Yes' if self.watching_enabled else 'No'

    def display_time_tracking_enabled(self) -> str:
        return 'Yes' if self.time_tracking_enabled else 'No'


@dataclass
class JiraServerInfo(BaseModel):
    base_url: str
    version: str
    build_number: int
    build_date: str
    server_title: str
    deployment_type: str | None = None
    default_locale: str | None = None
    server_time_zone: str | None = None
    server_time: str | None = None
    display_url_servicedesk_help_center: str | None = None
    display_url_confluence: str | None = None

    def get_display_url_servicedesk_help_center(self) -> str:
        return self.display_url_servicedesk_help_center or ''

    def get_display_url_confluence(self) -> str:
        return self.display_url_confluence or ''

    def get_server_time(self) -> str:
        return self.server_time or ''

    def get_server_time_zone(self) -> str:
        return self.server_time_zone or ''

    def get_deployment_type(self) -> str:
        return self.deployment_type or ''

    def get_default_locale(self) -> str:
        return self.default_locale or ''

    def get_server_title(self) -> str:
        return self.server_title or ''

    def get_build_date(self) -> str:
        return self.build_date or ''

    def get_build_number(self) -> str:
        return str(self.build_number) if self.build_number is not None else ''

    def get_version(self) -> str:
        return self.version or ''


@dataclass
class JiraUserGroup(BaseModel):
    id: str
    name: str


@dataclass
class JiraMyselfInfo(BaseModel):
    account_type: str
    account_id: str
    active: bool
    display_name: str
    email: str | None = None
    groups: list[JiraUserGroup] | None = None

    @property
    def display_user(self) -> str:
        if email := self.email:
            return email
        elif name := self.display_name:
            return name
        return self.account_id

    @property
    def user_groups(self) -> str | None:
        if not self.groups:
            return None
        return ','.join([g.name for g in self.groups])

    def get_account_id(self) -> str:
        return self.account_id or ''


@dataclass
class UpdateWorkItemResponse(BaseModel):
    success: bool
    updated_fields: list[str] | None = None


@dataclass
class WorkItemTransitionState(BaseModel):
    id: str
    name: str
    description: str | None = None
    status_category_color: str | None = None


@dataclass
class WorkItemTransition(BaseModel):
    id: str
    name: str
    to_state: WorkItemTransitionState | None = None


@dataclass
class LinkWorkItemType(BaseModel):
    id: str
    name: str
    outward: str
    inward: str


@dataclass
class JiraWorklog(BaseModel):
    id: str
    work_item_id: str
    started: datetime | None = None
    updated: datetime | None = None
    time_spent: str | None = None
    time_spent_seconds: int | None = None
    author: JiraUser | None = None
    update_author: JiraUser | None = None
    comment: dict | str | None = None

    def updated_on(self) -> str:
        if self.update_author:
            if self.updated:
                return f'{datetime.strftime(self.updated, "%Y-%m-%d %H:%M")} by {self.update_author.display_user}'
            else:
                return f'by {self.update_author.display_user}'
        return datetime.strftime(self.updated, '%Y-%m-%d %H:%M') if self.updated else ''

    def created_on(self) -> str:
        if self.author:
            if self.started:
                return f'{datetime.strftime(self.started, "%Y-%m-%d %H:%M")} by {self.author.display_user}'
            else:
                return f'by {self.author.display_user}'
        return datetime.strftime(self.started, '%Y-%m-%d %H:%M') if self.started else ''

    def display(self) -> str:
        if self.author:
            if self.updated:
                return f'{self.author.display_user} logged {self.time_spent} on {self.updated.strftime("%Y-%m-%d %H:%M")}'
            else:
                return f'{self.author.display_user} logged {self.time_spent}'
        else:
            if self.updated:
                return f'Logged {self.time_spent} on {self.updated.strftime("%Y-%m-%d %H:%M")}'
            else:
                return f'Logged {self.time_spent}'

    def get_comment(self, base_url: str | None = None) -> str:
        if self.comment is None:
            return ''
        if isinstance(self.comment, str):
            return self.comment
        return convert_adf_to_markdown(self.comment, base_url)


@dataclass
class PaginatedJiraWorklog(BaseModel):
    logs: list[JiraWorklog]
    max_results: int
    start_at: int
    total: int


@dataclass
class JiraField(BaseModel):
    """Jira field as returned from API."""

    id: str
    key: str
    name: str
    schema: dict


@dataclass
class WorkItemSearchResult(BaseModel):
    """Result of a work item search operation."""

    total: int = 0
    start: int = 0
    end: int = 0
    response: JiraWorkItemSearchResponse | None = None
