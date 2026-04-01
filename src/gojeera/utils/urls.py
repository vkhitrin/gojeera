import re
from typing import TYPE_CHECKING
from urllib.parse import ParseResult, urlencode, urlparse

if TYPE_CHECKING:
    from gojeera.app import JiraApp

from gojeera.config import CONFIGURATION

WORK_ITEM_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9]+-\d+$', re.IGNORECASE)
WORK_ITEM_BROWSE_TOOLTIP = 'Can be loaded inside gojeera using CTRL+mouse click'


def normalize_work_item_key(value: str) -> str | None:
    """Return a canonical uppercase Jira work item key, or None if invalid."""
    candidate = value.strip()
    if not WORK_ITEM_KEY_PATTERN.fullmatch(candidate):
        return None
    return candidate.upper()


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


def _parse_work_item_browse_url(value: str) -> tuple[ParseResult, list[str], str] | None:
    """Parse a Jira browse URL and return its parsed URL, path parts, and work item key."""
    candidate = value.strip()
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return None

    path_parts = [part for part in parsed.path.split('/') if part]
    if len(path_parts) < 2 or path_parts[-2] != 'browse':
        return None

    normalized_work_item_key = normalize_work_item_key(path_parts[-1])
    if normalized_work_item_key is None:
        return None

    return parsed, path_parts, normalized_work_item_key


def _is_current_jira_browse_url(
    parsed_value: ParseResult, value_parts: list[str], base_url: str
) -> bool:
    parsed_base = urlparse(base_url.strip())
    if parsed_value.scheme != parsed_base.scheme or parsed_value.netloc != parsed_base.netloc:
        return False

    base_parts = [part for part in parsed_base.path.split('/') if part]
    return value_parts[:-2] == base_parts


def extract_work_item_key(value: str, base_url: str | None = None) -> str | None:
    """Extract a Jira work item key from a raw key or browse URL.

    If `base_url` is provided, only browse URLs from the current Jira instance are accepted.
    """
    candidate = value.strip()
    if not candidate:
        return None

    normalized_candidate = normalize_work_item_key(candidate)
    if normalized_candidate is not None:
        return normalized_candidate

    parsed_result = _parse_work_item_browse_url(candidate)
    if parsed_result is None:
        return None

    parsed_value, value_parts, work_item_key = parsed_result
    if base_url and not _is_current_jira_browse_url(parsed_value, value_parts, base_url):
        return None

    return work_item_key


def build_external_url_for_work_item(
    key: str,
    app: 'JiraApp | None' = None,
    *,
    focused_comment_id: str | None = None,
    focused_work_log_id: str | None = None,
) -> str | None:
    """Build a Jira browse URL for a work item, optionally focused on a comment or work log."""
    if not key:
        return None

    query: dict[str, str] = {}
    if focused_comment_id:
        query['focusedCommentId'] = focused_comment_id
    if focused_work_log_id:
        query['focusedWorklogId'] = focused_work_log_id

    base_url = _get_base_url(app)
    url = f'{base_url}/browse/{key}'
    if query:
        return f'{url}?{urlencode(query)}'
    return url


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
