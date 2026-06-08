from dataclasses import dataclass
from typing import Literal

from typing_extensions import NotRequired, TypedDict
from datetime import datetime
from decimal import Decimal
from enum import Enum

from gojeera.internal.models.base import BaseModel


def _display_user_value(
    email: str | None,
    display_name: str | None,
    account_id: str | None,
) -> str:
    if email:
        return email
    if display_name:
        return display_name
    return account_id or ''


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
    SUBTASKS = 'subtasks'


@dataclass
class JiraProject(BaseModel):
    id: str
    name: str
    key: str
    project_type_key: str | None = None

    @property
    def is_service_desk(self) -> bool:
        return self.project_type_key == 'service_desk'

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
    scope_project: JiraProject | None = None


@dataclass
class JiraUser(BaseModel):
    account_id: str
    active: bool
    display_name: str
    email: str | None = None

    @property
    def display_user(self) -> str:
        return _display_user_value(self.email, self.display_name, self.account_id)

    def get_account_id(self) -> str:
        return self.account_id or ''


@dataclass
class WorkItemWatchers(BaseModel):
    is_watching: bool
    watch_count: int
    watchers: list[JiraUser]


@dataclass
class WorkItemPriority(BaseModel):
    id: str
    name: str


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

    def get_size(self) -> Decimal:
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

    def as_jira_dict(self) -> dict[str, int | str | None]:
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'projectKey': self.projectKey,
        }


class JiraFilterDict(TypedDict):
    """Dictionary representation of a JQL filter used by UI autocomplete."""

    label: str
    expression: str
    source: NotRequired[Literal['local', 'remote'] | str]
    starred: NotRequired[bool]


@dataclass
class JiraFilter(BaseModel):
    """JQL filter from local configuration or Jira remote filters."""

    label: str
    expression: str
    source: str = 'local'
    starred: bool = False

    def as_filter_dict(self) -> JiraFilterDict:
        return {
            'label': self.label,
            'expression': self.expression,
            'source': self.source,
            'starred': self.starred,
        }


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
class WorkItemRemoteLink(BaseModel):
    id: str
    global_id: str
    relationship: str
    title: str
    summary: str
    url: str | None = None
    status_resolved: bool | None = None


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
        return str(self.build_number)

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
        return _display_user_value(self.email, self.display_name, self.account_id)

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
class JiraField(BaseModel):
    """Jira field as returned from API."""

    id: str
    key: str
    name: str
    schema: dict
    description: str | None = None
