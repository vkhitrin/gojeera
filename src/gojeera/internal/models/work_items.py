from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from gojeera.internal.models.base import BaseModel
from gojeera.internal.models.jira import (
    Attachment,
    JiraBaseWorkItem,
    JiraSprint,
    JiraUser,
    JiraWorkItemComponent,
    JiraProject,
    TimeTracking,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
)


def _convert_adf_to_markdown(value: dict, base_url: str | None = None) -> str:
    from gojeera.utils.markdown.adf_helpers import convert_adf_to_markdown

    return convert_adf_to_markdown(value, base_url)


def _build_attachment_markdown_details(
    attachments: list[Attachment] | None,
) -> tuple[dict[str, tuple[str, str | None]], list[tuple[str, str | None]]]:
    from gojeera.utils.jira.urls import build_external_url_for_attachment

    media_attachment_details: dict[str, tuple[str, str | None]] = {}
    ordered_attachment_details: list[tuple[str, str | None]] = []

    for attachment in attachments or []:
        if not attachment.id or not attachment.filename:
            continue

        resolved = (
            attachment.filename,
            build_external_url_for_attachment(attachment.id, attachment.filename),
        )
        media_attachment_details[attachment.id] = resolved
        media_attachment_details[attachment.filename] = resolved
        ordered_attachment_details.append(resolved)

    return media_attachment_details, ordered_attachment_details


@dataclass
class WorkItemComment(BaseModel):
    id: str
    author: JiraUser
    created: datetime | None = None
    updated: datetime | None = None
    update_author: JiraUser | None = None
    body: dict | str | None = None
    rendered_body: str | None = None
    jsd_public: bool | None = None

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


@dataclass
class WorkItemHistoryChange(BaseModel):
    field: str
    from_value: str | None = None
    to_value: str | None = None

    def display(self) -> str:
        previous = self.from_value if self.from_value not in (None, '') else 'None'
        current = self.to_value if self.to_value not in (None, '') else 'None'
        return f'{self.field}: {previous} -> {current}'

    def sentence(self) -> str:
        previous = self.from_value if self.from_value not in (None, '') else 'None'
        current = self.to_value if self.to_value not in (None, '') else 'None'
        return f'{self.field}: {previous} -> {current}'


@dataclass
class WorkItemHistoryEntry(BaseModel):
    id: str
    author: JiraUser | None = None
    created: datetime | None = None
    changes: list[WorkItemHistoryChange] | None = None

    @property
    def created_on(self) -> str:
        return self.created.strftime('%Y-%m-%d %H:%M') if self.created else ''

    @property
    def display_author(self) -> str:
        if self.author is None:
            return ''
        return self.author.display_name or self.author.account_id or ''


@dataclass
class PaginatedWorkItemHistory(BaseModel):
    entries: list[WorkItemHistoryEntry]
    max_results: int
    start_at: int
    is_last: bool


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
class JiraWorkItem(JiraBaseWorkItem):
    summary: str
    status: WorkItemStatus
    project: JiraProject | None = None
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
    subtasks: list['JiraWorkItem'] | None = None
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
        from gojeera.utils.markdown.adf_helpers import convert_adf_to_markdown

        media_attachment_details, ordered_attachment_details = _build_attachment_markdown_details(
            self.attachments
        )

        return convert_adf_to_markdown(
            self.description,
            base_url,
            media_attachment_details=media_attachment_details,
            ordered_attachment_details=ordered_attachment_details,
        )

    def __repr__(self) -> str:
        return f'id:{self.id} - key:{self.key}'


@dataclass
class JiraWorkItemSearchResponse(BaseModel):
    work_items: list[JiraWorkItem]
    next_page_token: str | None = None
    is_last: bool | None = None
    total: int | None = None
    offset: int | None = None


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
        return _convert_adf_to_markdown(self.comment, base_url)


@dataclass
class PaginatedJiraWorklog(BaseModel):
    logs: list[JiraWorklog]
    max_results: int
    start_at: int
    total: int


@dataclass
class WorkItemSearchResult(BaseModel):
    """Result of a work item search operation."""

    total: int = 0
    start: int = 0
    end: int = 0
    response: JiraWorkItemSearchResponse | None = None
