from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gojeera.app import JiraApp

from gojeera.config import CONFIGURATION


def _get_base_url(app: 'JiraApp | None' = None) -> str:
    """Get base URL from app.server_info or fallback to api_base_url.

    Args:
        app: Optional JiraApp instance to get server_info from

    Returns:
        Base URL for constructing Jira web links
    """
    if app:
        server_info = getattr(app, 'server_info', None)
        if server_info and hasattr(server_info, 'base_url'):
            return server_info.base_url

    return CONFIGURATION.get().jira.api_base_url


def build_external_url_for_work_item(key: str, app: 'JiraApp | None' = None) -> str | None:
    """Build URL for a Jira issue.

    Args:
        key: Issue key (e.g., 'PROJ-123')
        app: Optional JiraApp instance

    Returns:
        Full URL to the issue, or None if key is empty
    """
    if not key:
        return None
    base_url = _get_base_url(app)
    return f'{base_url}/browse/{key}'


def build_external_url_for_comment(
    key: str, comment_id: str, app: 'JiraApp | None' = None
) -> str | None:
    """Build URL for a Jira comment.

    Args:
        key: Issue key (e.g., 'PROJ-123')
        comment_id: Comment ID
        app: Optional JiraApp instance

    Returns:
        Full URL to the comment, or None if inputs are empty
    """
    if not key or not comment_id:
        return None
    base_url = _get_base_url(app)
    return f'{base_url}/browse/{key}?focusedCommentId={comment_id}'


def build_external_url_for_work_log(
    key: str, work_log_id: str, app: 'JiraApp | None' = None
) -> str | None:
    """Build URL for a Jira work log.

    Args:
        key: Issue key (e.g., 'PROJ-123')
        work_log_id: Work log ID
        app: Optional JiraApp instance

    Returns:
        Full URL to the work log, or None if inputs are empty
    """
    if not key or not work_log_id:
        return None
    base_url = _get_base_url(app)
    return f'{base_url}/browse/{key}?focusedWorklogId={work_log_id}'


def build_external_url_for_attachment(
    attachment_id: str, filename: str, app: 'JiraApp | None' = None
) -> str | None:
    """Build URL for a Jira attachment.

    Args:
        attachment_id: Attachment ID
        filename: Attachment filename
        app: Optional JiraApp instance

    Returns:
        Full URL to the attachment, or None if inputs are empty
    """
    if not attachment_id or not filename:
        return None
    base_url = _get_base_url(app)
    return f'{base_url}/secure/attachment/{attachment_id}/{filename}'
