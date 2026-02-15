from datetime import datetime
import logging
from typing import Any

from dateutil.parser import isoparse

from gojeera.constants import LOGGER_NAME
from gojeera.models import (
    Attachment,
    JiraSprint,
    JiraUser,
    JiraWorkItem,
    JiraWorkItemComponent,
    JiraWorkItemGenericFields,
    Project,
    RelatedJiraWorkItem,
    TimeTracking,
    WorkItemComment,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
)
from gojeera.utils.fields import (
    get_additional_fields_values,
    get_custom_fields_values,
    get_sprint_field_id_from_editmeta,
)

logger = logging.getLogger(LOGGER_NAME)


class WorkItemFactory:
    @staticmethod
    def new_work_item(data: dict) -> JiraWorkItem:
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
            creator = None
            if author := item.get('author'):
                creator = JiraUser(
                    account_id=author.get('accountId'),
                    active=author.get('active'),
                    display_name=author.get('displayName'),
                    email=author.get('emailAddress'),
                )
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
                    sprint_data = sprint_value[0]
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
                        except Exception as e:
                            logger.warning(f'Failed to parse sprint data: {e}')

        return JiraWorkItem(
            id=str(data.get('id', '')),
            key=str(data.get('key', '')),
            summary=fields.get(JiraWorkItemGenericFields.SUMMARY.value, ''),
            description=fields.get(JiraWorkItemGenericFields.DESCRIPTION.value),
            project=Project(
                id=project.get('id'),
                name=project.get('name'),
                key=project.get('key'),
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
                id=priority.get('id'),
                name=priority.get('name'),
            )
            if priority
            else None,
            status=WorkItemStatus(
                id=str(status.get('id')),
                name=status.get('name'),
                status_category_color=(
                    status.get('statusCategory', {}).get('colorName')
                    if status.get('statusCategory')
                    else None
                ),
            ),
            assignee=JiraUser(
                account_id=assignee.get('accountId'),
                active=assignee.get('active'),
                display_name=assignee.get('displayName'),
                email=assignee.get('emailAddress'),
            )
            if assignee
            else None,
            reporter=JiraUser(
                account_id=reporter.get('accountId'),
                active=reporter.get('active'),
                display_name=reporter.get('displayName'),
                email=reporter.get('emailAddress'),
            )
            if reporter
            else None,
            work_item_type=WorkItemType(
                id=fields.get(JiraWorkItemGenericFields.WORK_ITEM_TYPE.value, {}).get('id'),
                name=fields.get(JiraWorkItemGenericFields.WORK_ITEM_TYPE.value, {}).get('name'),
                subtask=fields.get(JiraWorkItemGenericFields.WORK_ITEM_TYPE.value, {}).get(
                    'subtask', False
                ),
                hierarchy_level=fields.get(JiraWorkItemGenericFields.WORK_ITEM_TYPE.value, {}).get(
                    'hierarchyLevel'
                ),
            ),
            comments=build_comments(
                fields.get(JiraWorkItemGenericFields.COMMENT.value, {}).get('comments', [])
            ),
            related_work_items=build_related_work_items(
                fields.get(JiraWorkItemGenericFields.WORK_ITEM_LINKS.value, [])
            ),
            parent_work_item_key=parent_work_item_key,
            parent_work_item_type=parent_work_item_type,
            time_tracking=tracking,
            resolution=(
                fields.get(JiraWorkItemGenericFields.RESOLUTION.value).get('name')
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
                fields.get(JiraWorkItemGenericFields.DUE_DATE.value), '%Y-%m-%d'
            ).date()
            if fields.get(JiraWorkItemGenericFields.DUE_DATE.value)
            else None,
            custom_fields=custom_fields_values,
            additional_fields=additional_fields,
            components=components,
        )


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
                    author=JiraUser(
                        account_id=author.get('accountId'),
                        display_name=author.get('displayName'),
                        active=author.get('active'),
                        email=author.get('emailAddress'),
                    ),
                    created=isoparse(comment.get('created')) if comment.get('created') else None,
                    updated=isoparse(comment.get('updated')) if comment.get('updated') else None,
                    update_author=JiraUser(
                        account_id=update_author.get('accountId'),
                        display_name=update_author.get('displayName'),
                        active=update_author.get('active'),
                        email=update_author.get('emailAddress'),
                    )
                    if update_author
                    else None,
                    body=comment.get('body'),
                )
            )
        except Exception as e:
            logger.warning(f'Failed to parse comment: {e}')
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
            except Exception as e:
                logger.warning(f'Failed to parse inward work item: {e}')
                continue
        if outward_work_item := item.get('outwardIssue', {}):
            try:
                related_work_items.append(_build_related_outward_work_item(item, outward_work_item))
            except Exception as e:
                logger.warning(f'Failed to parse outward work item: {e}')
                continue
    return related_work_items


def _build_related_inward_work_item(item: dict, inward_work_item: dict) -> RelatedJiraWorkItem:
    return RelatedJiraWorkItem(
        id=str(item.get('id', '')),
        key=str(inward_work_item.get('key', '')),
        summary=inward_work_item.get('fields', {}).get('summary'),
        priority=WorkItemPriority(
            id=inward_work_item.get('fields', {}).get('priority').get('id'),
            name=inward_work_item.get('fields', {}).get('priority').get('name'),
        )
        if inward_work_item.get('fields', {}).get('priority')
        else None,
        status=WorkItemStatus(
            id=str(inward_work_item.get('fields', {}).get('status', {}).get('id')),
            name=inward_work_item.get('fields', {}).get('status', {}).get('name'),
            status_category_color=(
                inward_work_item.get('fields', {})
                .get('status', {})
                .get('statusCategory', {})
                .get('colorName')
            ),
        ),
        work_item_type=WorkItemType(
            id=inward_work_item.get('fields', {}).get('issuetype', {}).get('id'),
            name=inward_work_item.get('fields', {}).get('issuetype', {}).get('name'),
            subtask=inward_work_item.get('fields', {}).get('issuetype', {}).get('subtask', False),
        ),
        link_type=item.get('type', {}).get('inward'),
        relation_type='inward',
    )


def _build_related_outward_work_item(item: dict, outward_work_item: dict) -> RelatedJiraWorkItem:
    return RelatedJiraWorkItem(
        id=str(item.get('id', '')),
        key=str(outward_work_item.get('key', '')),
        summary=outward_work_item.get('fields', {}).get('summary'),
        priority=WorkItemPriority(
            id=outward_work_item.get('fields', {}).get('priority').get('id'),
            name=outward_work_item.get('fields', {}).get('priority').get('name'),
        )
        if outward_work_item.get('fields', {}).get('priority')
        else None,
        status=WorkItemStatus(
            id=str(outward_work_item.get('fields', {}).get('status', {}).get('id')),
            name=outward_work_item.get('fields', {}).get('status', {}).get('name'),
            status_category_color=(
                outward_work_item.get('fields', {})
                .get('status', {})
                .get('statusCategory', {})
                .get('colorName')
            ),
        ),
        work_item_type=WorkItemType(
            id=outward_work_item.get('fields', {}).get('issuetype', {}).get('id'),
            name=outward_work_item.get('fields', {}).get('issuetype', {}).get('name'),
            subtask=outward_work_item.get('fields', {}).get('issuetype', {}).get('subtask', False),
        ),
        link_type=item.get('type', {}).get('outward'),
        relation_type='outward',
    )
