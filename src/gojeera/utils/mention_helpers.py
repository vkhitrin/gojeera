"""Helper utilities for user mention insertion across screens."""

import logging
from typing import TYPE_CHECKING, Any, cast

from textual.widgets import TextArea

from gojeera.cache import ApplicationCache, get_cache
from gojeera.components.user_mention_picker_screen import UserMentionPickerScreen
from gojeera.models import JiraUser

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')


async def insert_user_mention(
    app: Any,
    target_widget: Any,
    project_key: str | None = None,
    work_item_key: str | None = None,
    cache: ApplicationCache | None = None,
) -> None:
    if TYPE_CHECKING:
        app = cast('JiraApp', app)  # noqa: F821

    if cache is None:
        cache = get_cache()

    try:
        textarea = target_widget.query_one(TextArea)
        saved_cursor_location = textarea.cursor_location
    except Exception:
        return

    try:
        users: list[JiraUser] = []

        if work_item_key and not project_key:
            project_key = work_item_key.split('-')[0]

        cache_key = project_key if project_key else 'global'
        cached_users_data = cache.get('project_users', cache_key)

        if cached_users_data:
            users = cached_users_data
        else:
            if work_item_key:
                response = await app.api.search_users_assignable_to_work_item(
                    work_item_key=work_item_key
                )
            elif project_key:
                response = await app.api.search_users_assignable_to_projects(
                    project_keys=[project_key]
                )
            else:
                response = await app.api.search_users('')

            if not response.success or not response.result:
                return

            users = response.result

        base_url = app.api.api.base_url

        result = await app.push_screen_wait(UserMentionPickerScreen(base_url, users))

        if result:
            account_id, display_name = result

            textarea.focus()
            textarea.move_cursor(saved_cursor_location)

            target_widget.insert_mention(account_id, display_name, base_url)
    except Exception:
        app.notify('Failed to insert mention', severity='error')
