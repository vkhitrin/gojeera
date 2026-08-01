from datetime import date

from gojeera.internal.models.jira import (
    JiraUser,
    JiraWorkItemComponent,
    WorkItemPriority,
)


def work_item_priority_has_changed(
    current_priority: WorkItemPriority | None = None,
    target_priority: str | None = None,
) -> bool:
    """Determines if the priority of a work item has changed wrt. to a new priority selected by the user from the
    priority dropdown.

    Args:
        current_priority: the current priority of the work item.
        target_priority: the new priority selected by the user.

    Returns:
        `True` id the priority has changed; `False` otherwise.
    """

    if current_priority is None:
        return bool(target_priority)
    if not target_priority:
        return True
    return current_priority.id != target_priority


def work_item_assignee_has_changed(
    current_assignee: JiraUser | None = None,
    target_assignee_account_id: str | None = None,
) -> bool:
    """Determines if the assignee of a work item has changed wrt. to a new assignee selected by the user from the
    assignee/users dropdown.

    Args:
        current_assignee: the work item's current assignee user.
        target_assignee_account_id: the account ID of the new user that we want to assign to the work item.

    Returns:
        `True` if the assignee of the work item has changed; `False` otherwise.
    """

    if current_assignee is None:
        return target_assignee_account_id is not None
    if target_assignee_account_id is None:
        return True
    return current_assignee.account_id != target_assignee_account_id


def work_item_parent_has_changed(
    current_parent_key: str | None = None, target_parent_key: str | None = None
) -> bool:
    """Determines if the parent of a work item has changed wrt. to a new parent key selected by the user.

    Args:
        current_parent_key: the current parent of the work item.
        target_parent_key: the new parent key selected by the user.

    Returns:
        `True` id the priority has changed; `False` otherwise.
    """

    if current_parent_key is None:
        return bool(target_parent_key)
    if not target_parent_key:
        return True
    return current_parent_key != target_parent_key.strip()


def work_item_due_date_has_changed(
    current_due_date: date | None = None, target_due_date: str | None = None
) -> bool:
    """Determines if the due date of a work item has changed wrt. to a new value selected by the user.

    Args:
        current_due_date: the current due date of the work item.
        target_due_date: the new due date set by the user.

    Returns:
        `True` id the due date has changed; `False` otherwise.
    """
    if current_due_date is None:
        return bool(target_due_date)
    if not target_due_date:
        return True
    return str(current_due_date) != target_due_date


def work_item_components_has_changed(
    current_components: list[JiraWorkItemComponent],
    target_components: list[dict],
) -> bool:
    """Determines if the components field of a work item has changed based on the current value and a new selection
    made by the user.

    Args:
        current_components: the list of components currently assigned to a work item.
        target_components: the new list of components.

    Returns:
        `True` if the list of components has changed.
    """

    if not current_components and target_components:
        return True
    if current_components and not target_components:
        return True
    if not current_components and not target_components:
        return False
    if len(current_components) != len(target_components):
        return True
    current_set = {x.id for x in current_components}
    return current_set.intersection({x.get('id') for x in target_components}) != current_set
