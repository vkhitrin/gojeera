from datetime import datetime
import logging
from typing import Any

from dateutil.parser import isoparse

from gojeera.internal.models.jira import (
    Attachment,
    JiraSprint,
    JiraProject,
    JiraUser,
    JiraWorkItemComponent,
    JiraWorkItemGenericFields,
    TimeTracking,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
)
from gojeera.internal.models.work_items import (
    JiraWorkItem,
    RelatedJiraWorkItem,
    WorkItemComment,
)
from gojeera.utils.data.fields import (
    get_additional_fields_values,
    get_custom_fields_values,
    get_sprint_field_id_from_editmeta,
)
from gojeera.utils.data.mappings import get_nested

logger = logging.getLogger('gojeera')


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


class WorkItemFactory:
    @staticmethod
    def build_required_jira_user(user_data: dict[str, Any]) -> JiraUser:
        return JiraUser(
            account_id=str(user_data.get('accountId', '')),
            active=bool(user_data.get('active', True)),
            display_name=str(user_data.get('displayName', '')),
            email=user_data.get('emailAddress'),
        )

    @staticmethod
    def build_jira_user(user_data: dict[str, Any] | None) -> JiraUser | None:
        if not user_data:
            return None
        return WorkItemFactory.build_required_jira_user(user_data)

    @staticmethod
    def build_required_work_item_type(work_item_type_data: dict[str, Any]) -> WorkItemType:
        return WorkItemType(
            id=str(work_item_type_data.get('id', '')),
            name=work_item_type_data.get('name', ''),
            subtask=bool(work_item_type_data.get('subtask', False)),
            hierarchy_level=work_item_type_data.get('hierarchyLevel'),
        )

    @staticmethod
    def build_work_item_type(
        work_item_type_data: dict[str, Any] | None,
    ) -> WorkItemType | None:
        if not work_item_type_data:
            return None
        return WorkItemFactory.build_required_work_item_type(work_item_type_data)

    @staticmethod
    def create_work_item(data: dict) -> JiraWorkItem:
        """Creates an instance of `JiraIssue` for a work item as returned by the API.

        Args:
            data: the work item as returned by the API.

        Returns:
            An instance of `JiraIssue` with the value of the work item's fields supported by the app.
        """

        fields: dict = data.get('fields', {})
        project: dict = fields.get(JiraWorkItemGenericFields.PROJECT.value, {})
        status: dict = fields.get(JiraWorkItemGenericFields.STATUS.value, {})
        assignee: dict | None = fields.get(JiraWorkItemGenericFields.ASSIGNEE.value)
        reporter: dict | None = fields.get(JiraWorkItemGenericFields.REPORTER.value)
        priority: dict | None = fields.get(JiraWorkItemGenericFields.PRIORITY.value)

        parent_work_item_key = None
        parent_work_item_type = None
        if parent := fields.get(JiraWorkItemGenericFields.PARENT.value):
            parent_work_item_key = parent.get('key')
            if parent_fields := parent.get('fields'):
                if work_item_issuetype := parent_fields.get('issuetype'):
                    parent_work_item_type = work_item_issuetype.get('name')

        tracking = None
        if time_tracking := fields.get(JiraWorkItemGenericFields.TIME_TRACKING.value):
            tracking = TimeTracking(
                original_estimate=time_tracking.get('originalEstimate'),
                remaining_estimate=time_tracking.get('remainingEstimate'),
                time_spent=time_tracking.get('timeSpent'),
                original_estimate_seconds=time_tracking.get('originalEstimateSeconds'),
                remaining_estimate_seconds=time_tracking.get('remainingEstimateSeconds'),
                time_spent_seconds=time_tracking.get('timeSpentSeconds'),
            )

        attachments: list[Attachment] = []
        for item in fields.get(JiraWorkItemGenericFields.ATTACHMENT.value, []):
            creator = WorkItemFactory.build_jira_user(item.get('author'))
            attachments.append(
                Attachment(
                    id=item.get('id'),
                    filename=item.get('filename'),
                    size=item.get('size'),
                    created=isoparse(item.get('created')) if item.get('created') else None,
                    mime_type=item.get('mimeType'),
                    author=creator,
                )
            )

        components: list[JiraWorkItemComponent] = []
        for component in fields.get(JiraWorkItemGenericFields.COMPONENTS.value, []) or []:
            components.append(
                JiraWorkItemComponent(
                    id=component.get('id'),
                    name=component.get('name'),
                    description=component.get('description'),
                )
            )

        watches: dict[str, Any] = fields.get('watches', {}) or {}

        custom_fields_values: dict[str, Any] | None = None
        if editmeta := data.get('editmeta', {}):
            custom_fields_values = get_custom_fields_values(fields, editmeta.get('fields', {}))

        additional_fields: dict[str, Any] = get_additional_fields_values(
            fields,
            [item.value for item in JiraWorkItemGenericFields],
        )

        sprint: JiraSprint | None = None
        if editmeta := data.get('editmeta', {}):
            edit_fields = editmeta.get('fields', {})
            sprint_field_id = get_sprint_field_id_from_editmeta(edit_fields)
            if sprint_field_id:
                sprint_value = fields.get(sprint_field_id)
                if sprint_value and isinstance(sprint_value, list) and len(sprint_value) > 0:
                    sprint_data = sprint_value[-1]
                    if isinstance(sprint_data, dict):
                        try:
                            sprint = JiraSprint(
                                id=sprint_data.get('id'),
                                name=sprint_data.get('name'),
                                state=sprint_data.get('state', 'unknown'),
                                boardId=sprint_data.get('boardId', 0),
                                goal=sprint_data.get('goal'),
                                startDate=sprint_data.get('startDate'),
                                endDate=sprint_data.get('endDate'),
                                completeDate=sprint_data.get('completeDate'),
                            )
                        except Exception:
                            logger.warning('Failed to parse sprint data', exc_info=True)

        return JiraWorkItem(
            id=str(data.get('id', '')),
            key=str(data.get('key', '')),
            summary=fields.get(JiraWorkItemGenericFields.SUMMARY.value, ''),
            description=fields.get(JiraWorkItemGenericFields.DESCRIPTION.value),
            project=JiraProject(
                id=_optional_string(project.get('id')) or '',
                name=_optional_string(project.get('name')) or '',
                key=_optional_string(project.get('key')) or '',
                project_type_key=_optional_string(project.get('projectTypeKey')),
            )
            if project
            else None,
            created=(
                isoparse(fields.get(JiraWorkItemGenericFields.CREATED.value))
                if fields.get(JiraWorkItemGenericFields.CREATED.value)
                else None
            ),
            updated=(
                isoparse(fields.get(JiraWorkItemGenericFields.UPDATED.value))
                if fields.get(JiraWorkItemGenericFields.UPDATED.value)
                else None
            ),
            priority=WorkItemPriority(
                id=_optional_string(priority.get('id')) or '',
                name=_optional_string(priority.get('name')) or '',
            )
            if priority
            else None,
            status=WorkItemStatus(
                id=str(status.get('id')),
                name=_optional_string(status.get('name')) or '',
                status_category_color=get_nested(status, 'statusCategory', 'colorName'),
            ),
            assignee=WorkItemFactory.build_jira_user(assignee),
            reporter=WorkItemFactory.build_jira_user(reporter),
            work_item_type=WorkItemFactory.build_work_item_type(
                fields.get(JiraWorkItemGenericFields.WORK_ITEM_TYPE.value)
            ),
            comments=build_comments(
                get_nested(fields, JiraWorkItemGenericFields.COMMENT.value, 'comments', default=[])
            ),
            subtasks=build_subtasks(fields.get(JiraWorkItemGenericFields.SUBTASKS.value, [])),
            related_work_items=build_related_work_items(
                fields.get(JiraWorkItemGenericFields.WORK_ITEM_LINKS.value, [])
            ),
            parent_work_item_key=parent_work_item_key,
            parent_work_item_type=parent_work_item_type,
            time_tracking=tracking,
            resolution=(
                get_nested(fields, JiraWorkItemGenericFields.RESOLUTION.value, 'name')
                if fields.get(JiraWorkItemGenericFields.RESOLUTION.value)
                else None
            ),
            resolution_date=isoparse(fields.get(JiraWorkItemGenericFields.RESOLUTION_DATE.value))
            if fields.get(JiraWorkItemGenericFields.RESOLUTION_DATE.value)
            else None,
            labels=fields.get(JiraWorkItemGenericFields.LABELS.value, [])
            if fields.get(JiraWorkItemGenericFields.LABELS.value)
            else None,
            attachments=attachments,
            sprint=sprint,
            edit_meta=data.get('editmeta', {}),
            due_date=datetime.strptime(
                str(fields.get(JiraWorkItemGenericFields.DUE_DATE.value)), '%Y-%m-%d'
            ).date()
            if fields.get(JiraWorkItemGenericFields.DUE_DATE.value)
            else None,
            custom_fields=custom_fields_values,
            additional_fields=additional_fields,
            components=components,
            watch_count=int(watches.get('watchCount', 0) or 0) if watches else None,
            is_watching=bool(watches.get('isWatching')) if watches else None,
        )


def build_subtasks(raw_subtasks: list[dict]) -> list[JiraWorkItem]:
    subtasks: list[JiraWorkItem] = []
    for item in raw_subtasks or []:
        fields: dict = item.get('fields', {})
        status: dict = fields.get(JiraWorkItemGenericFields.STATUS.value, {})
        assignee: dict | None = fields.get(JiraWorkItemGenericFields.ASSIGNEE.value)
        work_item_type: dict = fields.get(JiraWorkItemGenericFields.WORK_ITEM_TYPE.value, {})
        subtasks.append(
            JiraWorkItem(
                id=str(item.get('id', '')),
                key=str(item.get('key', '')),
                summary=fields.get(JiraWorkItemGenericFields.SUMMARY.value, ''),
                status=WorkItemStatus(
                    id=str(status.get('id', '')),
                    name=status.get('name', ''),
                    status_category_color=get_nested(status, 'statusCategory', 'colorName'),
                ),
                assignee=WorkItemFactory.build_jira_user(assignee),
                work_item_type=WorkItemFactory.build_work_item_type(work_item_type),
            )
        )
    return subtasks


def build_comments(raw_comments: list[dict]) -> list[WorkItemComment]:
    """Builds a list of `IssueComment`.

    Args:
        raw_comments: a list of dictionaries with the details of comments.

    Returns:
        A list of instances `IssueComment`.
    """
    comments: list[WorkItemComment] = []
    for comment in raw_comments:
        try:
            author = comment.get('author', {})
            update_author = comment.get('updateAuthor')
            comments.append(
                WorkItemComment(
                    id=str(comment.get('id', '')),
                    author=WorkItemFactory.build_required_jira_user(author),
                    created=isoparse(comment.get('created')) if comment.get('created') else None,
                    updated=isoparse(comment.get('updated')) if comment.get('updated') else None,
                    update_author=WorkItemFactory.build_jira_user(update_author),
                    body=comment.get('body'),
                    rendered_body=comment.get('renderedBody'),
                    jsd_public=comment.get('jsdPublic'),
                )
            )
        except Exception:
            logger.warning('Failed to parse comment', exc_info=True)
            continue
    return comments


def build_related_work_items(links: list[dict]) -> list[RelatedJiraWorkItem]:
    """Builds a list of `RelatedJiraIssue` representing the items related to another item.

    Args:
        links: a dictionary with the details of the related items.

    Returns:
        A list of `RelatedJiraIssue`.
    """
    related_work_items: list[RelatedJiraWorkItem] = []
    for item in links:
        if inward_work_item := item.get('inwardIssue', {}):
            try:
                related_work_items.append(_build_related_inward_work_item(item, inward_work_item))
            except Exception:
                logger.warning('Failed to parse inward work item', exc_info=True)
                continue
        if outward_work_item := item.get('outwardIssue', {}):
            try:
                related_work_items.append(_build_related_outward_work_item(item, outward_work_item))
            except Exception:
                logger.warning('Failed to parse outward work item', exc_info=True)
                continue
    return related_work_items


def _build_related_inward_work_item(item: dict, inward_work_item: dict) -> RelatedJiraWorkItem:
    inward_fields = get_nested(inward_work_item, 'fields', default={})
    return RelatedJiraWorkItem(
        id=str(item.get('id', '')),
        key=str(inward_work_item.get('key', '')),
        summary=get_nested(inward_fields, 'summary'),
        priority=WorkItemPriority(
            id=get_nested(inward_fields, 'priority', 'id'),
            name=get_nested(inward_fields, 'priority', 'name'),
        )
        if get_nested(inward_fields, 'priority')
        else None,
        status=WorkItemStatus(
            id=str(get_nested(inward_fields, 'status', 'id')),
            name=get_nested(inward_fields, 'status', 'name'),
            status_category_color=get_nested(
                inward_fields, 'status', 'statusCategory', 'colorName'
            ),
        ),
        work_item_type=WorkItemFactory.build_required_work_item_type(
            get_nested(inward_fields, 'issuetype')
        ),
        link_type=get_nested(item, 'type', 'inward'),
        relation_type='inward',
    )


def _build_related_outward_work_item(item: dict, outward_work_item: dict) -> RelatedJiraWorkItem:
    outward_fields = get_nested(outward_work_item, 'fields', default={})
    return RelatedJiraWorkItem(
        id=str(item.get('id', '')),
        key=str(outward_work_item.get('key', '')),
        summary=get_nested(outward_fields, 'summary'),
        priority=WorkItemPriority(
            id=get_nested(outward_fields, 'priority', 'id'),
            name=get_nested(outward_fields, 'priority', 'name'),
        )
        if get_nested(outward_fields, 'priority')
        else None,
        status=WorkItemStatus(
            id=str(get_nested(outward_fields, 'status', 'id')),
            name=get_nested(outward_fields, 'status', 'name'),
            status_category_color=get_nested(
                outward_fields, 'status', 'statusCategory', 'colorName'
            ),
        ),
        work_item_type=WorkItemFactory.build_required_work_item_type(
            get_nested(outward_fields, 'issuetype')
        ),
        link_type=get_nested(item, 'type', 'outward'),
        relation_type='outward',
    )
