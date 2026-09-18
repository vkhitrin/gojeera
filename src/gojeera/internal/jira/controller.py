import asyncio
from collections import OrderedDict, defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterable, Mapping
from contextlib import asynccontextmanager
import dataclasses
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import partial
import logging
import mimetypes
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, TypedDict, TypeVar, cast

from dateutil.parser import isoparse
import httpx

from gojeera.internal.auth.profiles import OAuth2AuthProfile
from gojeera.internal.auth.service import AuthService
from gojeera.internal.jira.api import JiraAPI
from gojeera.internal.jira.client import AsyncJiraClient
from gojeera.internal.jira.factories import WorkItemFactory
from gojeera.internal.models.base import BaseModel
from gojeera.internal.models.exceptions import (
    ServiceInvalidResponseException,
    ServiceUnavailableException,
    UpdateWorkItemException,
    ValidationError,
)
from gojeera.internal.models.jira import (
    Attachment,
    JiraBaseWorkItem,
    JiraField,
    JiraGlobalSettings,
    JiraMyselfInfo,
    JiraProject,
    JiraProjectFeature,
    JiraProjectRelease,
    JiraProjectRepository,
    JiraRepositoryPullRequest,
    JiraServerInfo,
    JiraSprint,
    JiraTimeTrackingConfiguration,
    JiraUser,
    JiraUserGroup,
    JiraWorkItemGenericFields,
    LinkWorkItemType,
    UpdateWorkItemResponse,
    WorkItemRemoteLink,
    WorkItemStatus,
    WorkItemTransition,
    WorkItemTransitionState,
    WorkItemType,
    WorkItemWatchers,
)
from gojeera.internal.models.work_items import (
    JiraWorkItem,
    JiraWorkItemSearchResponse,
    JiraWorklog,
    PaginatedJiraWorklog,
    PaginatedWorkItemComments,
    PaginatedWorkItemHistory,
    WorkItemComment,
    WorkItemHistoryChange,
    WorkItemHistoryEntry,
)
from gojeera.internal.store.cache import (
    CACHE_TTL_PROJECTS_WITH_RELEASES,
    get_cache,
    run_cache_io,
)
from gojeera.internal.store.config import CONFIGURATION, ApplicationConfiguration
from gojeera.utils.data.mappings import get_nested
from gojeera.utils.jira.jql import work_item_flagged_jql
from gojeera.utils.system.logging_utils import (
    ExceptionLogDetails,
)
from gojeera.utils.system.logging_utils import (
    build_log_extra as shared_build_log_extra,
)
from gojeera.utils.system.logging_utils import (
    extract_exception_details as shared_extract_exception_details,
)

ATTACHMENT_MAXIMUM_FILE_SIZE_IN_BYTES = 10485760
RECORDS_PER_PAGE_SEARCH_PROJECTS = 100
MAXIMUM_PAGE_NUMBER_SEARCH_PROJECTS = 10
RECORDS_PER_PAGE_PROJECT_RELEASES = 50
MAXIMUM_PAGE_NUMBER_PROJECT_RELEASES = 20
MAXIMUM_CONCURRENT_PROJECT_RELEASE_CHECKS = 8
PROJECT_REPOSITORIES_CACHE_TTL_SECONDS = 60.0
PROJECT_RELEASES_CACHE_TTL_SECONDS = 60.0
DEVELOPMENT_PROJECT_FEATURE_KEYS = frozenset({'jsw.classic.code', 'jsw.classic.development'})
RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_PROJECTS = 1000
RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_WORK_ITEMS = 1000
API_TOKEN_FALLBACK_REQUIRED_ERROR = (
    'This feature requires an API-token fallback profile for OAuth2 profiles.'
)
PROJECT_DEVELOPMENT_FEATURE_DISABLED_ERROR = (
    'Development features are not enabled for project {project_key}.'
)
PULL_REQUEST_KEY_LOOKUP_CONCURRENCY = 8
CACHE_REFRESH_FAILURE_RETRY_SECONDS = 60.0
PROJECT_PULL_REQUEST_CACHE_TTL_SECONDS = 60.0
WORK_ITEM_TOOLTIP_CACHE_TTL_SECONDS = 60.0
WORK_ITEM_TOOLTIP_CACHE_MAX_ENTRIES = 256
TRANSIENT_PROJECT_CACHE_MAX_ENTRIES = 64


@dataclass
class APIControllerResponse(BaseModel):
    success: bool = True
    result: Any | None = None
    error: str | None = None

    def as_dict(self):
        return dataclasses.asdict(self)


class SearchWorkItemFilterArgs(TypedDict):
    project_key: str | None
    created_from: date | None
    created_until: date | None
    status: int | None
    assignee: str | None
    work_item_type: int | None
    jql_query: str | None


T = TypeVar('T')
R = TypeVar('R')
DEFERRED_WORK_ITEM_FIELDS = {
    JiraWorkItemGenericFields.COMMENT.value,
    JiraWorkItemGenericFields.SUBTASKS.value,
}
INITIAL_WORK_ITEM_FIELDS = [
    '*all',
    *(f'-{field}' for field in sorted(DEFERRED_WORK_ITEM_FIELDS)),
    'watches',
]


class APIController:
    """A controller for the JirAPI to provide some additional functionality and integration of multiple endpoints."""

    def __init__(self, configuration: ApplicationConfiguration | None = None):
        self.config = CONFIGURATION.get() if not configuration else configuration
        self.auth = self.config.jira.build_auth_context()
        self.auth_service = AuthService()
        self._oauth2_refresh_lock = Lock()
        self.client: JiraAPI
        self.identity_api: AsyncJiraClient | None = None
        self.client = JiraAPI(
            auth=self.auth,
            configuration=self.config,
            oauth2_token_refresher=self._refresh_oauth2_access_token,
        )
        if self.auth.auth_type == 'oauth2' and self.auth.identity_base_url is not None:
            self.identity_api = AsyncJiraClient(
                base_url=self.auth.identity_base_url,
                api_email=self.auth.api_email,
                api_token=self.auth.api_token,
                configuration=self.config,
                bearer_token=self.auth.bearer_token,
                token_refresh_callback=self._refresh_oauth2_access_token,
            )
        self.skip_users_without_email = self.config.ignore_users_without_email
        self.logger = logging.getLogger('gojeera')
        client_cache = getattr(self.client, 'cache', None)
        if client_cache is None:
            client_cache = get_cache()
            client_cache.set_profile(self._cache_profile_key())
        self.cache = client_cache
        self._inflight_requests: dict[tuple[Any, ...], asyncio.Task[APIControllerResponse]] = {}
        self._background_refresh_tasks: set[asyncio.Task[APIControllerResponse]] = set()
        self._cache_refresh_retry_after: dict[tuple[Any, ...], float] = {}
        self._project_pull_requests_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._project_repositories_cache: dict[str, tuple[float, list[JiraProjectRepository]]] = {}
        self._project_releases_cache: dict[
            tuple[str, int | None, str | None, str | None],
            tuple[float, list[JiraProjectRelease]],
        ] = {}
        self._project_release_page_callbacks: dict[
            tuple[Any, ...],
            list[Callable[[list[JiraProjectRelease]], Awaitable[None] | None]],
        ] = {}
        self._projects_with_releases_cache: tuple[float, list[JiraProject]] | None = None
        self._work_item_tooltip_cache: OrderedDict[str, tuple[float, tuple[str, str, str]]] = (
            OrderedDict()
        )

    async def _coalesce_request(
        self,
        key: tuple[Any, ...],
        operation: Callable[[], Coroutine[Any, Any, APIControllerResponse]],
    ) -> APIControllerResponse:
        inflight_requests = getattr(self, '_inflight_requests', None)
        if inflight_requests is None:
            inflight_requests = {}
            self._inflight_requests = inflight_requests

        if existing := inflight_requests.get(key):
            return await asyncio.shield(existing)

        task = asyncio.create_task(operation())
        inflight_requests[key] = task

        def remove_completed(completed_task: asyncio.Task[APIControllerResponse]) -> None:
            if inflight_requests.get(key) is completed_task:
                inflight_requests.pop(key, None)

        task.add_done_callback(remove_completed)
        return await asyncio.shield(task)

    def _schedule_background_refresh(
        self,
        key: tuple[Any, ...],
        operation: Callable[[], Coroutine[Any, Any, APIControllerResponse]],
    ) -> None:
        inflight_requests = getattr(self, '_inflight_requests', {})
        if key in inflight_requests:
            return
        retry_after = getattr(self, '_cache_refresh_retry_after', None)
        if retry_after is None:
            retry_after = {}
            self._cache_refresh_retry_after = retry_after
        if retry_after.get(key, 0.0) > monotonic():
            return
        task = asyncio.create_task(self._coalesce_request(key, operation))
        background_tasks = getattr(self, '_background_refresh_tasks', None)
        if background_tasks is None:
            background_tasks = set()
            self._background_refresh_tasks = background_tasks
        background_tasks.add(task)

        def remove_completed(completed_task: asyncio.Task[APIControllerResponse]) -> None:
            self._background_refresh_tasks.discard(completed_task)
            if completed_task.cancelled():
                return
            try:
                response = completed_task.result()
            except Exception:
                retry_after[key] = monotonic() + CACHE_REFRESH_FAILURE_RETRY_SECONDS
                self.logger.exception('Background cache refresh failed', extra={'cache_key': key})
                return
            if not response.success:
                retry_after[key] = monotonic() + CACHE_REFRESH_FAILURE_RETRY_SECONDS
                self.logger.debug(
                    'Background cache refresh returned an error',
                    extra={'cache_key': key, 'error': response.error},
                )
                return
            retry_after.pop(key, None)

        task.add_done_callback(remove_completed)

    @staticmethod
    def _get_transient_cache_entry(
        cache: dict[Any, tuple[float, Any]],
        key: Any,
    ) -> tuple[float, Any] | None:
        entry = cache.get(key)
        if entry is None:
            return None
        if entry[0] <= monotonic():
            cache.pop(key, None)
            return None
        cache.pop(key, None)
        cache[key] = entry
        return entry

    @staticmethod
    def _set_transient_cache_entry(
        cache: dict[Any, tuple[float, Any]],
        key: Any,
        entry: tuple[float, Any],
    ) -> None:
        cache.pop(key, None)
        cache[key] = entry
        while len(cache) > TRANSIENT_PROJECT_CACHE_MAX_ENTRIES:
            cache.pop(next(iter(cache)))

    async def _cached_or_refresh(
        self,
        key: tuple[Any, ...],
        cache_getter: Callable[[bool], Any | None],
        refresh: Callable[[], Coroutine[Any, Any, APIControllerResponse]],
    ) -> APIControllerResponse:
        cached = await run_cache_io(lambda: cache_getter(False))
        if cached is not None:
            return APIControllerResponse(result=cached)

        stale = await run_cache_io(lambda: cache_getter(True))
        if stale is not None:
            self._schedule_background_refresh(key, refresh)
            return APIControllerResponse(result=stale)

        return await self._coalesce_request(key, refresh)

    async def _fresh_cached_or_refresh(
        self,
        key: tuple[Any, ...],
        cache_getter: Callable[[], Any | None],
        refresh: Callable[[], Coroutine[Any, Any, APIControllerResponse]],
    ) -> APIControllerResponse:
        cached = await run_cache_io(cache_getter)
        if cached is not None:
            return APIControllerResponse(result=cached)
        return await self._coalesce_request(key, refresh)

    def _cache_profile_key(self) -> str:
        return f'{self.auth.cloud_id}:{self.auth.account_id}'

    def get_cached_work_item_tooltip(self, work_item_key: str) -> tuple[str, str, str] | None:
        """Return fresh tooltip data shared by every Markdown widget."""
        cache = getattr(self, '_work_item_tooltip_cache', None)
        if cache is None:
            return None

        normalized_key = work_item_key.casefold()
        cached_entry = cache.get(normalized_key)
        if cached_entry is None:
            return None
        if cached_entry[0] <= monotonic():
            cache.pop(normalized_key, None)
            return None

        cache.move_to_end(normalized_key)
        return cached_entry[1]

    def cache_work_item_tooltip(
        self,
        work_item_key: str,
        work_item_type: str,
        summary: str,
        status: str,
    ) -> None:
        """Store bounded, short-lived tooltip data for the active profile."""
        cache = getattr(self, '_work_item_tooltip_cache', None)
        if cache is None:
            cache = OrderedDict()
            self._work_item_tooltip_cache = cache

        normalized_key = work_item_key.casefold()
        cache[normalized_key] = (
            monotonic() + WORK_ITEM_TOOLTIP_CACHE_TTL_SECONDS,
            (work_item_type, summary, status),
        )
        cache.move_to_end(normalized_key)
        while len(cache) > WORK_ITEM_TOOLTIP_CACHE_MAX_ENTRIES:
            cache.popitem(last=False)

    def invalidate_work_item_tooltip(self, work_item_key: str) -> None:
        cache = getattr(self, '_work_item_tooltip_cache', None)
        if cache is not None:
            cache.pop(work_item_key.casefold(), None)

    def _refresh_oauth2_access_token(self, force: bool) -> str | None:
        with self._oauth2_refresh_lock:
            active_profile = self.config.jira.active_profile
            if not isinstance(active_profile, OAuth2AuthProfile):
                return None

            if (
                force
                or getattr(self.config.jira, 'oauth2_access_token', None) is None
                or self.auth_service.should_refresh_oauth2_access_token(active_profile)
            ):
                token_response = self.auth_service.refresh_oauth2_access_token(active_profile)
                self.config.jira.update_active_oauth2_session(
                    access_token=token_response.access_token,
                    refresh_token=token_response.refresh_token,
                    oauth2_access_token_expiration_timestamp=(
                        token_response.access_token_expiration_timestamp
                    ),
                )
                refreshed_token = token_response.access_token
            else:
                refreshed_token = (
                    self.config.jira.oauth2_access_token.get_secret_value()
                    if self.config.jira.oauth2_access_token is not None
                    else self.auth_service.get_oauth2_access_token(active_profile)
                )

        if not refreshed_token:
            return None

        if refreshed_token == self.auth.bearer_token:
            return refreshed_token

        self.auth = self.config.jira.build_auth_context()
        self.client.set_bearer_token(refreshed_token)
        if self.identity_api is not None:
            self.identity_api.set_bearer_token(refreshed_token)
        return refreshed_token

    async def close(self) -> None:
        await self.client.close()
        if self.identity_api is not None:
            await self.identity_api.close_async_client()

    async def _close_jira_api_clients(self, client: JiraAPI) -> None:
        await client.close()

    def _build_api_token_fallback_client(self) -> JiraAPI | None:
        fallback_profile = self.config.jira.api_token_fallback_profile
        if self.auth.auth_type != 'oauth2' or fallback_profile is None:
            return None

        fallback_auth = self.config.jira.build_api_token_auth_context(fallback_profile)
        return JiraAPI(auth=fallback_auth, configuration=self.config)

    @asynccontextmanager
    async def _client_with_api_token_fallback(self) -> AsyncIterator[JiraAPI]:
        fallback_client = self._build_api_token_fallback_client()
        try:
            yield fallback_client or self.client
        finally:
            if fallback_client is not None:
                await self._close_jira_api_clients(fallback_client)

    def _api_token_fallback_required_response(self) -> APIControllerResponse | None:
        if self.auth.auth_type != 'oauth2':
            return None
        if self.config.jira.api_token_fallback_profile is not None:
            return None
        return APIControllerResponse(
            success=False,
            error=API_TOKEN_FALLBACK_REQUIRED_ERROR,
        )

    @staticmethod
    def _extract_exception_details(exception: Exception) -> ExceptionLogDetails:
        return shared_extract_exception_details(exception)

    @staticmethod
    def _build_log_extra(
        base: dict[str, Any] | None = None,
        exception_details: ExceptionLogDetails | None = None,
    ) -> dict[str, Any]:
        return shared_build_log_extra(base, exception_details)

    def _failed_api_response(
        self,
        exception: Exception,
        *,
        error_message: str,
        extra: dict[str, Any] | None = None,
    ) -> APIControllerResponse:
        exception_details = self._extract_exception_details(exception)
        self.logger.error(
            error_message,
            extra=self._build_log_extra(extra, exception_details),
        )
        return APIControllerResponse(success=False, error=exception_details.message)

    def _build_jira_users(self, users_data: list[dict[str, Any]]) -> list[JiraUser]:
        users: list[JiraUser] = []
        for user_data in users_data:
            email = user_data.get('emailAddress')
            if self.skip_users_without_email and not email:
                continue
            built_user = WorkItemFactory.build_jira_user(user_data)
            if built_user is not None:
                users.append(built_user)
        return users

    def _filter_and_sort_jira_users(
        self, users_data: list[dict[str, Any]], *, active: bool | None
    ) -> list[JiraUser]:
        if active is not None:
            users_data = [item for item in users_data if item.get('active') == active]

        return sorted(
            self._build_jira_users(users_data),
            key=lambda item: item.display_name or item.account_id,
        )

    def _build_work_item_comment(self, comment_data: dict[str, Any]) -> WorkItemComment:
        return WorkItemComment(
            id=str(comment_data.get('id', '')),
            created=isoparse(comment_data.get('created')) if comment_data.get('created') else None,
            updated=isoparse(comment_data.get('updated')) if comment_data.get('updated') else None,
            author=cast(JiraUser, WorkItemFactory.build_jira_user(comment_data.get('author'))),
            update_author=WorkItemFactory.build_jira_user(comment_data.get('updateAuthor')),
            body=comment_data.get('body'),
            rendered_body=comment_data.get('renderedBody'),
            jsd_public=comment_data.get('jsdPublic'),
        )

    def _build_worklog(self, worklog_data: dict[str, Any]) -> JiraWorklog:
        return JiraWorklog(
            id=str(worklog_data.get('id', '')),
            work_item_id=str(worklog_data.get('issueId', '')),
            started=isoparse(worklog_data.get('started')) if worklog_data.get('started') else None,
            updated=isoparse(worklog_data.get('updated')) if worklog_data.get('updated') else None,
            time_spent=worklog_data.get('timeSpent'),
            time_spent_seconds=worklog_data.get('timeSpentSeconds'),
            author=WorkItemFactory.build_jira_user(worklog_data.get('author')),
            update_author=WorkItemFactory.build_jira_user(worklog_data.get('updateAuthor')),
            comment=worklog_data.get('comment'),
        )

    @staticmethod
    def _build_work_item_remote_link(remote_link_data: dict[str, Any]) -> WorkItemRemoteLink:
        return WorkItemRemoteLink(
            id=str(remote_link_data.get('id')),
            global_id=str(remote_link_data.get('globalId', '')),
            relationship=str(remote_link_data.get('relationship', '')),
            title=get_nested(remote_link_data, 'object', 'title'),
            summary=get_nested(remote_link_data, 'object', 'summary'),
            url=get_nested(remote_link_data, 'object', 'url'),
            status_resolved=get_nested(remote_link_data, 'object', 'status', 'resolved'),
        )

    @staticmethod
    def _build_project_release(release_data: dict[str, Any]) -> JiraProjectRelease:
        issues_status = release_data.get('issuesStatusForFixVersion') or {}
        return JiraProjectRelease(
            id=str(release_data.get('id', '')),
            name=str(release_data.get('name', '')),
            archived=bool(release_data.get('archived', False)),
            released=bool(release_data.get('released', False)),
            overdue=bool(release_data.get('overdue', False)),
            description=release_data.get('description'),
            start_date=release_data.get('startDate'),
            release_date=release_data.get('releaseDate'),
            todo_count=issues_status.get('toDo'),
            in_progress_count=issues_status.get('inProgress'),
            done_count=issues_status.get('done'),
            unmapped_count=issues_status.get('unmapped'),
        )

    @staticmethod
    def _build_project_repository(
        repository_data: dict[str, Any],
    ) -> JiraProjectRepository:
        return JiraProjectRepository(
            id=str(repository_data.get('id', '')),
            name=str(repository_data.get('name', '')),
            url=repository_data.get('url'),
            provider_id=repository_data.get('provider_id'),
            provider_name=repository_data.get('provider_name'),
            external_id=repository_data.get('external_id'),
            relationship_id=repository_data.get('relationship_id'),
            repository_type=repository_data.get('repository_type'),
        )

    @staticmethod
    def _normalise_repository_match_value(value: str | None) -> str | None:
        if not value:
            return None
        return value.rstrip('/').casefold()

    @classmethod
    def _repository_matches_pull_request(
        cls,
        repository: JiraProjectRepository,
        pull_request: dict[str, Any],
    ) -> bool:
        repository_values = {
            cls._normalise_repository_match_value(repository.id),
            cls._normalise_repository_match_value(repository.external_id),
            cls._normalise_repository_match_value(repository.url),
            cls._normalise_repository_match_value(repository.name),
        }
        repository_values.discard(None)

        pull_request_values = {
            cls._normalise_repository_match_value(pull_request.get('repositoryId')),
            cls._normalise_repository_match_value(pull_request.get('repositoryInternalId')),
            cls._normalise_repository_match_value(pull_request.get('repositoryUrl')),
            cls._normalise_repository_match_value(pull_request.get('repositoryName')),
            cls._normalise_repository_match_value(pull_request.get('repository_id')),
            cls._normalise_repository_match_value(pull_request.get('repository_url')),
            cls._normalise_repository_match_value(pull_request.get('repository_name')),
        }
        pull_request_values.discard(None)
        return bool(repository_values & pull_request_values)

    @staticmethod
    def _pull_request_branch_name(branch: Any) -> str | None:
        if isinstance(branch, dict):
            return branch.get('name')
        if isinstance(branch, str):
            return branch
        return None

    @staticmethod
    def _pull_request_author_name(author: Any) -> str | None:
        if isinstance(author, dict):
            return author.get('name') or author.get('displayName') or author.get('emailAddress')
        if isinstance(author, str):
            return author
        return None

    @classmethod
    def _build_repository_pull_request(
        cls,
        pull_request_data: dict[str, Any],
    ) -> JiraRepositoryPullRequest:
        return JiraRepositoryPullRequest(
            id=str(
                pull_request_data.get('id')
                or pull_request_data.get('pullRequestInternalId')
                or pull_request_data.get('url')
                or ''
            ),
            title=str(pull_request_data.get('title') or pull_request_data.get('name') or ''),
            work_item_key=str(pull_request_data.get('work_item_key') or ''),
            work_item_id=str(pull_request_data.get('work_item_id') or ''),
            status=pull_request_data.get('status'),
            url=pull_request_data.get('url'),
            author=cls._pull_request_author_name(pull_request_data.get('author')),
            repository_id=pull_request_data.get('repository_id')
            or pull_request_data.get('repositoryId')
            or pull_request_data.get('repositoryInternalId'),
            repository_name=pull_request_data.get('repository_name')
            or pull_request_data.get('repositoryName'),
            repository_url=pull_request_data.get('repository_url')
            or pull_request_data.get('repositoryUrl'),
            provider_id=pull_request_data.get('provider_id') or pull_request_data.get('providerId'),
            provider_name=pull_request_data.get('provider_name')
            or pull_request_data.get('providerName'),
            source_branch=cls._pull_request_branch_name(
                pull_request_data.get('sourceBranch') or pull_request_data.get('source_branch')
            ),
            destination_branch=cls._pull_request_branch_name(
                pull_request_data.get('destinationBranch')
                or pull_request_data.get('destination_branch')
            ),
            last_updated=pull_request_data.get('lastUpdated')
            or pull_request_data.get('updatedDate')
            or pull_request_data.get('last_updated'),
        )

    @classmethod
    def _build_pull_request_response(
        cls,
        pull_requests_data: list[dict[str, Any]],
        *,
        include_work_item_key_in_sort: bool,
    ) -> APIControllerResponse:
        pull_requests = [
            cls._build_repository_pull_request(pull_request_data)
            for pull_request_data in pull_requests_data
        ]

        def sort_key(pull_request: JiraRepositoryPullRequest) -> tuple[str, ...]:
            if include_work_item_key_in_sort:
                return (
                    pull_request.last_updated or '',
                    pull_request.work_item_key,
                    pull_request.title,
                )
            return (pull_request.last_updated or '', pull_request.title)

        pull_requests.sort(key=sort_key, reverse=True)
        return APIControllerResponse(result=pull_requests)

    @staticmethod
    def _build_project_feature(
        project_key: str, feature_data: dict[str, Any]
    ) -> JiraProjectFeature:
        return JiraProjectFeature(
            project_key=project_key,
            feature=str(feature_data.get('feature', '')),
            state=str(feature_data.get('state', '')),
            toggle_locked=bool(feature_data.get('toggleLocked', False)),
            localised_name=feature_data.get('localisedName'),
            localised_description=feature_data.get('localisedDescription'),
            image_uri=feature_data.get('imageUri'),
            prerequisites=feature_data.get('prerequisites') or [],
        )

    @staticmethod
    def _project_development_feature_enabled(features: list[JiraProjectFeature]) -> bool:
        return any(
            feature.feature in DEVELOPMENT_PROJECT_FEATURE_KEYS and feature.is_enabled
            for feature in features
        )

    @staticmethod
    def _build_work_item_transition(transition_data: dict[str, Any]) -> WorkItemTransition | None:
        if not (to_state := transition_data.get('to', {})):
            return None

        status_category = to_state.get('statusCategory', {})
        color_name = status_category.get('colorName') if status_category else None
        return WorkItemTransition(
            id=str(transition_data.get('id')),
            name=str(transition_data.get('name', '')),
            to_state=WorkItemTransitionState(
                id=str(to_state.get('id')),
                name=to_state.get('name'),
                description=to_state.get('description'),
                status_category_color=color_name,
            ),
        )

    @staticmethod
    def _resolve_remaining_time_estimate(
        time_remaining: str | None,
        current_remaining_estimate: str | None,
    ) -> str | None:
        if time_remaining and (
            not current_remaining_estimate or time_remaining != current_remaining_estimate
        ):
            return time_remaining
        return None

    @staticmethod
    def _worklog_log_context(
        *,
        time_spent: str | None,
        time_remaining: str | None,
        current_remaining_estimate: str | None,
        started: datetime | None,
        worklog_id: str | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {
            'time_spent': time_spent,
            'time_remaining': time_remaining,
            'current_remaining_estimate': current_remaining_estimate,
            'started': str(started) if started else None,
        }
        if worklog_id is not None:
            extra['worklog_id'] = worklog_id
        return extra

    def _worklog_request_kwargs(
        self,
        worklog_fields: dict[str, Any],
    ) -> dict[str, Any]:
        time_remaining = worklog_fields.get('time_remaining')
        current_remaining_estimate = worklog_fields.get('current_remaining_estimate')
        return {
            'work_item_id_or_key': worklog_fields.get('work_item_key_or_id'),
            'started': worklog_fields.get('started'),
            'time_spent': worklog_fields.get('time_spent'),
            'time_remaining': self._resolve_remaining_time_estimate(
                time_remaining, current_remaining_estimate
            ),
            'comment': worklog_fields.get('comment'),
        }

    async def _execute_void_api_operation(
        self,
        operation: Awaitable[Any],
        *,
        error_message: str,
        extra: dict[str, Any] | None = None,
    ) -> APIControllerResponse:
        try:
            await operation
        except Exception as e:
            return self._failed_api_response(e, error_message=error_message, extra=extra)
        return APIControllerResponse()

    async def _execute_result_api_operation(
        self,
        operation: Awaitable[T],
        *,
        result_builder: Callable[[T], R],
        error_message: str,
        extra: dict[str, Any] | None = None,
    ) -> APIControllerResponse:
        try:
            response = await operation
        except Exception as e:
            return self._failed_api_response(e, error_message=error_message, extra=extra)
        return APIControllerResponse(result=result_builder(response))

    async def _validate_search_criteria_jql(
        self, criteria: dict[str, Any]
    ) -> APIControllerResponse | None:
        if jql_from_criteria := criteria.get('jql'):
            validation_result = await self.validate_jql_query(jql_from_criteria)
            if not validation_result.success:
                self.logger.warning(f'JQL validation failed: {validation_result.error}')
                return APIControllerResponse(success=False, error=validation_result.error)
        return None

    @staticmethod
    def _validate_message_presence(message: str) -> APIControllerResponse | None:
        if not message:
            return APIControllerResponse(success=False, error='Missing required message.')
        return None

    async def validate_add_comment_permissions(
        self,
        work_item_key_or_id: str,
    ) -> APIControllerResponse | None:
        return await self.validate_work_item_permissions(
            work_item_key_or_id=work_item_key_or_id,
            required_permissions=['BROWSE_PROJECTS', 'ADD_COMMENTS'],
            action_name='add comments',
            error_message='Unable to validate comment permissions',
        )

    async def validate_view_watchers_permissions(
        self,
        work_item_key_or_id: str,
    ) -> APIControllerResponse | None:
        return await self.validate_work_item_permissions(
            work_item_key_or_id=work_item_key_or_id,
            required_permissions=['BROWSE_PROJECTS', 'VIEW_VOTERS_AND_WATCHERS'],
            action_name='view watchers',
            error_message='Unable to validate watcher permissions',
        )

    async def validate_work_item_permissions(
        self,
        work_item_key_or_id: str,
        required_permissions: list[str],
        *,
        action_name: str,
        error_message: str = 'Unable to validate work item permissions',
    ) -> APIControllerResponse | None:
        return await self._validate_work_item_permissions(
            work_item_key_or_id=work_item_key_or_id,
            required_permissions=required_permissions,
            action_name=action_name,
            error_message=error_message,
        )

    async def _validate_work_item_permissions(
        self,
        *,
        work_item_key_or_id: str,
        required_permissions: list[str],
        action_name: str,
        error_message: str,
    ) -> APIControllerResponse | None:
        try:
            response = await self.client.get_my_permissions(
                work_item_id_or_key=work_item_key_or_id,
                permissions=required_permissions,
            )
        except Exception as e:
            return self._failed_api_response(
                e,
                error_message=error_message,
                extra={'work_item_key_or_id': work_item_key_or_id},
            )

        permissions = response.get('permissions', {})
        missing_permissions = [
            permission
            for permission in required_permissions
            if not permissions.get(permission, {}).get('havePermission', False)
        ]
        if missing_permissions:
            return APIControllerResponse(
                success=False,
                error=f'Missing required permission(s) to {action_name}: '
                + ', '.join(missing_permissions),
            )
        return None

    def _build_work_item_remote_links(
        self, response: list[dict[str, Any]]
    ) -> list[WorkItemRemoteLink]:
        return [self._build_work_item_remote_link(item) for item in response]

    def _build_work_item_watchers(self, response: dict[str, Any]) -> WorkItemWatchers:
        return WorkItemWatchers(
            is_watching=bool(response.get('isWatching', False)),
            watch_count=int(response.get('watchCount', 0) or 0),
            watchers=self._build_jira_users(response.get('watchers', [])),
        )

    @staticmethod
    def get_work_item_flagged_field(
        work_item: JiraWorkItem,
    ) -> tuple[str, dict[str, Any]] | None:
        edit_metadata = work_item.get_edit_metadata() or {}
        for field_id, field_metadata in edit_metadata.items():
            if str(field_metadata.get('name', '')).casefold() == 'flagged':
                return field_id, field_metadata
        return None

    async def get_work_item_flagged_state(self, work_item_key: str) -> APIControllerResponse:
        """Returns whether Jira considers a work item flagged."""
        # NOTE: Using a workaround to fetch flag field "reliably", in the future we
        # should try to migrate to GraphQL.
        jql_query = work_item_flagged_jql(work_item_key)
        try:
            response = await self.client.search_work_items(
                jql_query=jql_query,
                fields=['key'],
                limit=1,
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve the Flagged state of the work item',
                extra={
                    'work_item_key': work_item_key,
                    'jql_query': jql_query,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        return APIControllerResponse(result=bool(response.get('issues', [])))

    def _build_work_item_transitions(self, response: dict[str, Any]) -> list[WorkItemTransition]:
        transitions: list[WorkItemTransition] = []
        for transition_data in response.get('transitions', []):
            built_transition = self._build_work_item_transition(transition_data)
            if built_transition is not None:
                transitions.append(built_transition)
        return transitions

    def _build_work_item_comments(self, response: dict[str, Any]) -> PaginatedWorkItemComments:
        comments = [
            self._build_work_item_comment(comment_data)
            for comment_data in response.get('comments', [])
        ]
        return PaginatedWorkItemComments(
            comments=comments,
            max_results=int(response.get('maxResults', len(comments)) or 0),
            start_at=int(response.get('startAt', 0) or 0),
            total=int(response.get('total', len(comments)) or 0),
        )

    def _build_work_item_history_entries(
        self, response: dict[str, Any]
    ) -> list[WorkItemHistoryEntry]:
        history: list[WorkItemHistoryEntry] = []
        for history_data in response.get('values', []):
            history.append(
                WorkItemHistoryEntry(
                    id=str(history_data.get('id', '')),
                    author=WorkItemFactory.build_jira_user(history_data.get('author')),
                    created=(
                        isoparse(history_data.get('created'))
                        if history_data.get('created')
                        else None
                    ),
                    changes=[
                        WorkItemHistoryChange(
                            field=str(change_data.get('field') or change_data.get('fieldId') or ''),
                            from_value=change_data.get('fromString') or change_data.get('from'),
                            to_value=change_data.get('toString') or change_data.get('to'),
                        )
                        for change_data in history_data.get('items', [])
                    ],
                )
            )
        return sorted(
            history,
            key=lambda item: item.created or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    def _build_work_item_history(self, response: dict[str, Any]) -> PaginatedWorkItemHistory:
        return PaginatedWorkItemHistory(
            entries=self._build_work_item_history_entries(response),
            max_results=int(response.get('maxResults', 0) or 0),
            start_at=int(response.get('startAt', 0) or 0),
            is_last=bool(response.get('isLast', True)),
        )

    def _server_information_error_response(self, error: Exception) -> APIControllerResponse:
        exception_details: dict = self._extract_exception_details(error)
        self.logger.error(
            'Unable to retrieve information of the Jira server',
            extra=exception_details.get('extra'),
        )
        return APIControllerResponse(success=False, error=exception_details.get('message'))

    def _build_search_work_item_api_kwargs(
        self,
        *,
        search_filters: SearchWorkItemFilterArgs,
        criteria: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            'project_key': search_filters.get('project_key'),
            'created_from': search_filters.get('created_from'),
            'created_until': search_filters.get('created_until'),
            'updated_from': criteria.get('updated_from'),
            'status': search_filters.get('status'),
            'assignee': search_filters.get('assignee'),
            'work_item_type': search_filters.get('work_item_type'),
            'jql_query': criteria.get('jql'),
        }

    async def _prepare_search_work_item_api_kwargs(
        self,
        *,
        project_key: str | None,
        created_from: date | None,
        created_until: date | None,
        status: int | None,
        assignee: str | None,
        work_item_type: int | None,
        jql_query: str | None,
    ) -> tuple[dict[str, Any] | None, APIControllerResponse | None]:
        search_filters: SearchWorkItemFilterArgs = {
            'project_key': project_key,
            'created_from': created_from,
            'created_until': created_until,
            'status': status,
            'assignee': assignee,
            'work_item_type': work_item_type,
            'jql_query': jql_query,
        }
        criteria = self._build_criteria_for_searching_work_items(search_filters)

        if validation_error := await self._validate_search_criteria_jql(criteria):
            return None, validation_error

        return (
            self._build_search_work_item_api_kwargs(
                search_filters=search_filters,
                criteria=criteria,
            ),
            None,
        )

    async def get_project(self, key: str) -> APIControllerResponse:
        """Retrieves the details of a project by key.

        Args:
            key: the case-sensitive key of the project.

        Returns:
            An instance of `APIControllerResponse` with the details of the project in the `result key; `success=False`
            and the detail of the error if the project can not be retrieved.
        """

        try:
            response: dict = await self.client.get_project(key)
        except Exception as e:
            exception_details = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve project',
                extra=self._build_log_extra({'key': key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.message)
        return APIControllerResponse(
            result=JiraProject(
                id=str(response.get('id', '')),
                name=response.get('name', ''),
                key=response.get('key', ''),
                project_type_key=response.get('projectTypeKey'),
            ),
        )

    async def _ensure_project_cached(self, project_key: str) -> None:
        cached_project = await run_cache_io(
            lambda: self.cache.get_stale_project_by_key(project_key)
        )
        if cached_project is not None:
            return

        project_response = await self.get_project(project_key)
        project = project_response.result
        if project_response.success and isinstance(project, JiraProject):
            await run_cache_io(lambda: self.cache.upsert_projects([project]))
            return

        self.logger.debug(
            'Unable to cache project metadata before repository lookup',
            extra=self._build_log_extra(
                {
                    'project_key': project_key,
                    'error': project_response.error,
                }
            ),
        )

    async def get_project_repositories(
        self,
        project_key: str,
        on_page: Callable[[list[JiraProjectRepository]], Awaitable[None] | None] | None = None,
    ) -> APIControllerResponse:
        """Retrieves repositories associated with a Jira project."""

        if fallback_response := self._api_token_fallback_required_response():
            return fallback_response

        feature_response = await self.project_development_feature_enabled(project_key)
        if not feature_response.success:
            return feature_response
        if feature_response.result is not True:
            return APIControllerResponse(
                success=False,
                error=PROJECT_DEVELOPMENT_FEATURE_DISABLED_ERROR.format(
                    project_key=project_key,
                ),
            )

        cache_key = project_key.casefold()
        repositories_cache = getattr(self, '_project_repositories_cache', {})
        cached_entry = self._get_transient_cache_entry(repositories_cache, cache_key)
        if cached_entry is not None:
            cached_repositories = list(cached_entry[1])
            if on_page is not None:
                page_result = on_page(cached_repositories)
                if page_result is not None:
                    await page_result
            return APIControllerResponse(result=cached_repositories)

        try:
            await self._ensure_project_cached(project_key)
            async with self._client_with_api_token_fallback() as client:
                pages_published = False

                async def publish_page(repositories_page: list[dict[str, Any]]) -> None:
                    nonlocal pages_published
                    pages_published = True
                    if on_page is None:
                        return
                    repositories = [
                        self._build_project_repository(repository_data)
                        for repository_data in repositories_page
                    ]
                    page_result = on_page(repositories)
                    if page_result is not None:
                        await page_result

                repositories_data = await client.get_project_repositories(
                    project_key,
                    on_page=publish_page,
                )
        except Exception as e:
            exception_details = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve project repositories',
                extra=self._build_log_extra({'project_key': project_key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.message)

        repositories = [
            self._build_project_repository(repository_data) for repository_data in repositories_data
        ]
        if not pages_published and on_page is not None:
            page_result = on_page(list(repositories))
            if page_result is not None:
                await page_result
        repositories_cache = getattr(self, '_project_repositories_cache', None)
        if repositories_cache is None:
            repositories_cache = {}
            self._project_repositories_cache = repositories_cache
        self._set_transient_cache_entry(
            repositories_cache,
            cache_key,
            (
                monotonic() + PROJECT_REPOSITORIES_CACHE_TTL_SECONDS,
                list(repositories),
            ),
        )
        return APIControllerResponse(result=repositories)

    async def get_repository_pull_requests(
        self,
        project_key: str,
        repository: JiraProjectRepository,
        on_page: Callable[[list[JiraRepositoryPullRequest]], Awaitable[None] | None] | None = None,
    ) -> APIControllerResponse:
        """Retrieves pull requests associated with a project repository."""

        if fallback_response := self._api_token_fallback_required_response():
            return fallback_response

        cache_key = project_key.casefold()
        cached_entry = self._get_transient_cache_entry(
            self._project_pull_requests_cache,
            cache_key,
        )

        try:
            async with self._client_with_api_token_fallback() as client:
                if cached_entry is not None and cached_entry[0] > monotonic():
                    pull_requests_data = [
                        pull_request_data
                        for pull_request_data in cached_entry[1]
                        if self._repository_matches_pull_request(repository, pull_request_data)
                    ]
                    await self._populate_pull_request_work_item_keys(client, pull_requests_data)
                    response = self._build_pull_request_response(
                        pull_requests_data,
                        include_work_item_key_in_sort=True,
                    )
                    if on_page is not None:
                        page_result = on_page(
                            cast(list[JiraRepositoryPullRequest], response.result)
                        )
                        if page_result is not None:
                            await page_result
                    return response

                matching_pull_requests: list[dict[str, Any]] = []
                pages_published = False

                async def publish_page(page: list[dict[str, Any]]) -> None:
                    nonlocal pages_published
                    pages_published = True
                    matching_page = [
                        pull_request_data
                        for pull_request_data in page
                        if self._repository_matches_pull_request(repository, pull_request_data)
                    ]
                    await self._populate_pull_request_work_item_keys(client, matching_page)
                    matching_pull_requests.extend(matching_page)
                    if on_page is not None:
                        page_response = self._build_pull_request_response(
                            matching_page,
                            include_work_item_key_in_sort=True,
                        )
                        page_result = on_page(
                            cast(list[JiraRepositoryPullRequest], page_response.result)
                        )
                        if page_result is not None:
                            await page_result

                project_pull_requests = await client.get_project_space_pull_requests(
                    project_key,
                    on_page=publish_page,
                )
                if not pages_published:
                    matching_pull_requests = [
                        pull_request_data
                        for pull_request_data in project_pull_requests
                        if self._repository_matches_pull_request(repository, pull_request_data)
                    ]
                    await self._populate_pull_request_work_item_keys(
                        client,
                        matching_pull_requests,
                    )
                    if on_page is not None:
                        fallback_page = self._build_pull_request_response(
                            matching_pull_requests,
                            include_work_item_key_in_sort=True,
                        )
                        page_result = on_page(
                            cast(list[JiraRepositoryPullRequest], fallback_page.result)
                        )
                        if page_result is not None:
                            await page_result
                self._set_transient_cache_entry(
                    self._project_pull_requests_cache,
                    cache_key,
                    (
                        monotonic() + PROJECT_PULL_REQUEST_CACHE_TTL_SECONDS,
                        project_pull_requests,
                    ),
                )
                pull_requests_data = matching_pull_requests
        except Exception as e:
            exception_details = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve repository pull requests',
                extra=self._build_log_extra({'project_key': project_key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.message)

        return self._build_pull_request_response(
            pull_requests_data,
            include_work_item_key_in_sort=True,
        )

    async def _populate_pull_request_work_item_keys(
        self,
        client: JiraAPI,
        pull_requests_data: list[dict[str, Any]],
    ) -> None:
        unresolved_work_item_ids = {
            str(pull_request_data.get('work_item_id') or '')
            for pull_request_data in pull_requests_data
            if pull_request_data.get('work_item_id') and not pull_request_data.get('work_item_key')
        }
        if not unresolved_work_item_ids:
            return

        semaphore = asyncio.Semaphore(PULL_REQUEST_KEY_LOOKUP_CONCURRENCY)

        async def resolve_work_item_key(work_item_id: str) -> tuple[str, str]:
            async with semaphore:
                work_item_data = await client.get_work_item(
                    work_item_id_or_key=work_item_id,
                    fields='key',
                )
            return work_item_id, str(work_item_data.get('key') or '')

        resolved_work_item_keys = await asyncio.gather(
            *(resolve_work_item_key(work_item_id) for work_item_id in unresolved_work_item_ids)
        )
        work_item_keys_by_id = {
            work_item_id: work_item_key
            for work_item_id, work_item_key in resolved_work_item_keys
            if work_item_key
        }

        for pull_request_data in pull_requests_data:
            work_item_id = str(pull_request_data.get('work_item_id') or '')
            if work_item_id and not pull_request_data.get('work_item_key'):
                pull_request_data['work_item_key'] = work_item_keys_by_id.get(work_item_id, '')

    async def get_work_item_development_pull_requests(
        self,
        work_item_key: str,
        work_item_id: str | None = None,
        project_key: str | None = None,
    ) -> APIControllerResponse:
        """Retrieves pull requests associated with a work item."""

        if fallback_response := self._api_token_fallback_required_response():
            return fallback_response

        try:
            del project_key
            async with self._client_with_api_token_fallback() as client:
                resolved_work_item_id = str(work_item_id or '')
                resolved_work_item_key = work_item_key

                if not resolved_work_item_id:
                    work_item_data = await client.get_work_item(
                        work_item_id_or_key=work_item_key,
                        fields='key',
                    )
                    resolved_work_item_id = str(work_item_data.get('id') or resolved_work_item_id)
                    resolved_work_item_key = str(
                        work_item_data.get('key') or resolved_work_item_key
                    )

                if not resolved_work_item_id:
                    return APIControllerResponse(
                        success=False,
                        error='Unable to resolve work item id for development details.',
                    )

                pull_requests_data = await client.get_work_item_pull_requests(resolved_work_item_id)
                for pull_request_data in pull_requests_data:
                    pull_request_data['work_item_key'] = resolved_work_item_key
                    pull_request_data['work_item_id'] = resolved_work_item_id
        except Exception as e:
            exception_details = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve work item development pull requests',
                extra=self._build_log_extra({'work_item_key': work_item_key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.message)

        return self._build_pull_request_response(
            pull_requests_data,
            include_work_item_key_in_sort=False,
        )

    async def search_projects(
        self,
        query: str | None = None,
        keys: list[str] | None = None,
        project_type_key: str | None = None,
        on_page: Callable[[list[JiraProject]], None] | None = None,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Searches for projects using different filters.

        Args:
            query: filter the results using a literal string. Projects with a matching key or name are returned
            (case-insensitive).
            keys: the project keys to filter the results by.
            project_type_key: filter the results by project type.
            on_page: optional callback invoked with the accumulated projects after each page.

        Returns:
            An instance of `APIControllerResponse` with the list of `JiraProject` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """

        cache_key = (
            'projects',
            (query or '').casefold(),
            tuple(key.casefold() for key in keys or []),
            (project_type_key or '').casefold(),
        )
        if not _coalesced:
            if query is None and not keys and project_type_key is None:
                response = await self._cached_or_refresh(
                    cache_key,
                    lambda allow_stale: self.cache.get_projects(allow_stale=allow_stale),
                    lambda: self.search_projects(on_page=on_page, _coalesced=True),
                )
                return response

            if query is None and not keys and project_type_key is not None:
                response = await self._cached_or_refresh(
                    cache_key,
                    lambda allow_stale: self.cache.get_projects_by_type(
                        project_type_key,
                        allow_stale=allow_stale,
                    ),
                    lambda: self.search_projects(
                        project_type_key=project_type_key,
                        on_page=on_page,
                        _coalesced=True,
                    ),
                )
                return response

            return await self._coalesce_request(
                cache_key,
                lambda: self.search_projects(
                    query=query,
                    keys=keys,
                    project_type_key=project_type_key,
                    on_page=on_page,
                    _coalesced=True,
                ),
            )

        projects: list[JiraProject] = []
        is_last = False
        i = 0
        while not is_last and i < MAXIMUM_PAGE_NUMBER_SEARCH_PROJECTS:
            try:
                response: dict = await self.client.search_projects(
                    offset=i * RECORDS_PER_PAGE_SEARCH_PROJECTS,
                    limit=RECORDS_PER_PAGE_SEARCH_PROJECTS,
                    query=query,
                    keys=keys,
                    project_type_key=project_type_key,
                )
            except Exception as e:
                exception_details = self._extract_exception_details(e)
                self.logger.error(
                    'There was an error while searching projects',
                    extra=self._build_log_extra(
                        {
                            'error': str(e),
                            'query': query,
                            'keys': keys,
                            'project_type_key': project_type_key,
                            'limit': RECORDS_PER_PAGE_SEARCH_PROJECTS,
                        },
                        exception_details,
                    ),
                )
                return APIControllerResponse(result=projects, error=exception_details.message)
            else:
                for project in response.get('values', []):
                    projects.append(
                        JiraProject(
                            id=project.get('id'),
                            key=project.get('key'),
                            name=project.get('name'),
                            project_type_key=project.get('projectTypeKey'),
                        )
                    )
                is_last = response.get('isLast')
                i += 1
                if on_page is not None:
                    on_page(list(projects))

        if query is None and not keys and project_type_key is None:
            await run_cache_io(lambda: self.cache.set_projects(projects))
        elif query is None and not keys and project_type_key is not None:
            await run_cache_io(lambda: self.cache.sync_projects_by_type(project_type_key, projects))

        return APIControllerResponse(result=projects)

    async def get_project_releases(
        self,
        project_key: str,
        *,
        limit: int | None = None,
        status: str | None = None,
        order_by: str | None = 'sequence',
        on_page: Callable[[list[JiraProjectRelease]], Awaitable[None] | None] | None = None,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves project releases from Jira project versions."""

        cache_key = (project_key.casefold(), limit, status, order_by)
        releases_cache = getattr(self, '_project_releases_cache', {})
        cached_entry = self._get_transient_cache_entry(releases_cache, cache_key)
        if cached_entry is not None:
            cached_releases = list(cached_entry[1])
            if on_page is not None:
                page_result = on_page(cached_releases)
                if page_result is not None:
                    await page_result
            return APIControllerResponse(result=cached_releases)

        request_key = ('project-releases', *cache_key)
        if not _coalesced:
            callbacks = getattr(self, '_project_release_page_callbacks', None)
            if callbacks is None:
                callbacks = {}
                self._project_release_page_callbacks = callbacks
            if on_page is not None:
                callbacks.setdefault(request_key, []).append(on_page)
            try:
                return await self._coalesce_request(
                    request_key,
                    lambda: self.get_project_releases(
                        project_key,
                        limit=limit,
                        status=status,
                        order_by=order_by,
                        on_page=lambda releases: self._publish_project_release_page(
                            request_key, releases
                        ),
                        _coalesced=True,
                    ),
                )
            finally:
                if on_page is not None and request_key in callbacks:
                    callbacks[request_key].remove(on_page)
                    if not callbacks[request_key]:
                        callbacks.pop(request_key, None)

        releases: list[JiraProjectRelease] = []
        is_last = False
        i = 0
        page_size = limit or RECORDS_PER_PAGE_PROJECT_RELEASES

        while not is_last and i < MAXIMUM_PAGE_NUMBER_PROJECT_RELEASES:
            try:
                response: dict = await self.client.get_project_versions(
                    project_key,
                    offset=i * page_size,
                    limit=page_size,
                    status=status,
                    order_by=order_by,
                )
            except Exception as e:
                exception_details = self._extract_exception_details(e)
                self.logger.error(
                    'Unable to retrieve project releases',
                    extra=self._build_log_extra({'project_key': project_key}, exception_details),
                )
                return APIControllerResponse(
                    success=False,
                    result=releases,
                    error=exception_details.message,
                )

            releases.extend(
                self._build_project_release(release_data)
                for release_data in response.get('values', [])
            )
            is_last = bool(response.get('isLast', True))
            i += 1

            if on_page is not None:
                published_releases = releases[:limit] if limit is not None else list(releases)
                page_result = on_page(published_releases)
                if page_result is not None:
                    await page_result

            if limit is not None and len(releases) >= limit:
                result = releases[:limit]
                self._cache_project_releases(cache_key, result)
                return APIControllerResponse(result=result)

        self._cache_project_releases(cache_key, releases)
        return APIControllerResponse(result=releases)

    async def _publish_project_release_page(
        self,
        request_key: tuple[Any, ...],
        releases: list[JiraProjectRelease],
    ) -> None:
        callbacks = getattr(self, '_project_release_page_callbacks', {}).get(request_key, [])
        for callback in list(callbacks):
            page_result = callback(list(releases))
            if page_result is not None:
                await page_result

    def _cache_project_releases(
        self,
        cache_key: tuple[str, int | None, str | None, str | None],
        releases: list[JiraProjectRelease],
    ) -> None:
        cache = getattr(self, '_project_releases_cache', None)
        if cache is None:
            cache = {}
            self._project_releases_cache = cache
        self._set_transient_cache_entry(
            cache,
            cache_key,
            (
                monotonic() + PROJECT_RELEASES_CACHE_TTL_SECONDS,
                list(releases),
            ),
        )

    async def search_projects_with_releases(
        self,
        on_page: Callable[[list[JiraProject]], Awaitable[None] | None] | None = None,
        *,
        _refresh: bool = False,
    ) -> APIControllerResponse:
        """Return software projects with releases, publishing matches as checks finish."""
        cache = getattr(self, 'cache', None)
        if not _refresh:
            cached_entry = getattr(self, '_projects_with_releases_cache', None)
            if cached_entry is not None and cached_entry[0] > monotonic():
                cached_projects = list(cached_entry[1])
                if on_page is not None:
                    page_result = on_page(cached_projects)
                    if page_result is not None:
                        await page_result
                return APIControllerResponse(result=cached_projects)

            if cache is not None:
                cached_projects = await run_cache_io(cache.get_projects_with_releases)
                if cached_projects is not None:
                    self._projects_with_releases_cache = (
                        monotonic() + CACHE_TTL_PROJECTS_WITH_RELEASES,
                        list(cached_projects),
                    )
                    if on_page is not None:
                        page_result = on_page(list(cached_projects))
                        if page_result is not None:
                            await page_result
                    return APIControllerResponse(result=cached_projects)

                stale_projects = await run_cache_io(
                    lambda: cache.get_projects_with_releases(allow_stale=True)
                )
                if stale_projects is not None:
                    if on_page is not None:
                        page_result = on_page(list(stale_projects))
                        if page_result is not None:
                            await page_result
                    self._schedule_background_refresh(
                        ('projects-with-releases',),
                        lambda: self.search_projects_with_releases(_refresh=True),
                    )
                    return APIControllerResponse(result=stale_projects)

        projects_response = await self.search_projects(project_type_key='software')
        if not projects_response.success:
            return projects_response

        projects = cast(list[JiraProject], projects_response.result or [])
        semaphore = asyncio.Semaphore(MAXIMUM_CONCURRENT_PROJECT_RELEASE_CHECKS)

        async def check_project(project: JiraProject) -> tuple[JiraProject, bool]:
            async with semaphore:
                releases_response = await self.get_project_releases(project.key, limit=1)
                return project, bool(releases_response.success and releases_response.result)

        projects_with_releases: list[JiraProject] = []
        checks = [asyncio.create_task(check_project(project)) for project in projects]
        try:
            for completed_check in asyncio.as_completed(checks):
                project, has_releases = await completed_check
                if not has_releases:
                    continue
                projects_with_releases.append(project)
                projects_with_releases.sort(key=lambda item: item.key.casefold())
                if on_page is not None:
                    page_result = on_page(list(projects_with_releases))
                    if page_result is not None:
                        await page_result
        finally:
            for check in checks:
                if not check.done():
                    check.cancel()
            await asyncio.gather(*checks, return_exceptions=True)

        self._projects_with_releases_cache = (
            monotonic() + CACHE_TTL_PROJECTS_WITH_RELEASES,
            list(projects_with_releases),
        )
        if cache is not None:
            await run_cache_io(lambda: cache.set_projects_with_releases(projects_with_releases))

        return APIControllerResponse(result=projects_with_releases)

    async def get_project_features(
        self,
        project_key: str,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves Jira Software project features, using the local SQLite cache when fresh."""

        if not _coalesced:
            return await self._cached_or_refresh(
                ('project-features', project_key.casefold()),
                lambda allow_stale: self.cache.get_project_features(
                    project_key,
                    allow_stale=allow_stale,
                ),
                lambda: self.get_project_features(project_key, _coalesced=True),
            )

        try:
            response = await self.client.get_project_features(project_key)
        except Exception as e:
            exception_details = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve project features',
                extra=self._build_log_extra({'project_key': project_key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.message)

        features = [
            self._build_project_feature(project_key, feature_data)
            for feature_data in response.get('features', [])
            if isinstance(feature_data, dict)
        ]
        await run_cache_io(lambda: self.cache.set_project_features(project_key, features))
        return APIControllerResponse(result=features)

    async def project_development_feature_enabled(self, project_key: str) -> APIControllerResponse:
        """Returns whether Jira Software development features are enabled for a project."""

        features_response = await self.get_project_features(project_key)
        if not features_response.success:
            return features_response

        features = cast(list[JiraProjectFeature], features_response.result or [])
        return APIControllerResponse(result=self._project_development_feature_enabled(features))

    async def get_project_statuses(
        self,
        project_key: str,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves the statues applicable to work items of a project.

        Args:
            project_key: the case-sensitive key of a project.

        Returns:
            An instance of `APIControllerResponse` with the statuses grouped by type of work items. If an error occurs an
            instance of `APIControllerResponse` with the `error` message and `success = False`.
        """

        if not _coalesced:
            return await self._cached_or_refresh(
                ('project-statuses', project_key.casefold()),
                lambda allow_stale: self.cache.get_project_statuses(
                    project_key,
                    allow_stale=allow_stale,
                ),
                lambda: self.get_project_statuses(project_key, _coalesced=True),
            )

        try:
            response: list[dict] = await self.client.get_project_statuses(project_key)
        except Exception as e:
            exception_details = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find status codes associated to a project',
                extra=self._build_log_extra({'project_key': project_key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.message)
        statuses_by_work_item_type: dict[str, dict] = defaultdict(dict)
        for record in response:
            statuses_for_work_item_type: list[WorkItemStatus] = []
            for status in record.get('statuses', []):
                statuses_for_work_item_type.append(
                    WorkItemStatus(
                        id=str(status.get('id')),
                        name=status.get('name'),
                        description=status.get('description'),
                    )
                )

            record_id = str(record.get('id', ''))
            statuses_by_work_item_type[record_id] = {
                'work_item_type_name': record.get('name'),
                'work_item_type_statuses': statuses_for_work_item_type,
            }

        await run_cache_io(
            lambda: self.cache.set_project_statuses(project_key, statuses_by_work_item_type)
        )

        return APIControllerResponse(result=statuses_by_work_item_type)

    async def status(self, *, _coalesced: bool = False) -> APIControllerResponse:
        if not _coalesced:
            return await self._cached_or_refresh(
                ('statuses',),
                lambda allow_stale: self.cache.get_statuses(allow_stale=allow_stale),
                lambda: self.status(_coalesced=True),
            )

        try:
            response: list[dict] = await self.client.status()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find available status codes',
                extra=exception_details.get('extra'),
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        statuses: list[WorkItemStatus] = []
        for item in response:
            statuses.append(
                WorkItemStatus(
                    id=str(item.get('id')),
                    name=str(item.get('name', '')),
                    description=item.get('description'),
                )
            )
        await run_cache_io(lambda: self.cache.set_statuses(statuses))
        return APIControllerResponse(result=statuses)

    async def get_work_item_types_for_project(self, project_key: str) -> APIControllerResponse:
        """Retrieves the types of work items associated to a project.

        Args:
            project_key: the ID or (case-sensitive) key of the project whose work item types we want to retrieve.

        Returns:
            An instance of `APIControllerResponse` with the list of `IssueType` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """

        return await self._cached_or_refresh(
            ('project-work-item-types', project_key.casefold()),
            lambda allow_stale: self.cache.get_project_work_item_types(
                project_key,
                allow_stale=allow_stale,
            ),
            lambda: self._get_work_item_types_for_project_uncached(project_key),
        )

    async def _get_work_item_types_for_project_uncached(
        self, project_key: str
    ) -> APIControllerResponse:

        try:
            project: dict = await self.client.get_project(project_key)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find work item types for the given project',
                extra=self._build_log_extra({'project_key': project_key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        work_item_types = [
            WorkItemType(
                id=str(item.get('id')),
                name=item.get('name'),
                subtask=item.get('subtask', False),
                hierarchy_level=item.get('hierarchyLevel'),
            )
            for item in project.get('issueTypes', []) or []
        ]

        await run_cache_io(
            lambda: self.cache.set_project_work_item_types(project_key, work_item_types)
        )

        return APIControllerResponse(result=work_item_types)

    async def get_work_item_types(self, *, _coalesced: bool = False) -> APIControllerResponse:
        """Retrieves all the types of work items relevant for any project.

        It may contain multiple work item types with the same name (different IDs though).

        Returns:
            An instance of `APIControllerResponse` with the list of `IssueType` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """
        if not _coalesced:
            return await self._cached_or_refresh(
                ('work-item-types',),
                lambda allow_stale: self.cache.get_work_item_types(allow_stale=allow_stale),
                lambda: self.get_work_item_types(_coalesced=True),
            )

        try:
            response, projects = await asyncio.gather(
                self.client.get_work_items_types_for_user(),
                self.search_projects(),
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find work item types', extra=exception_details.get('extra', {})
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        else:
            projects_by_id: dict[str, JiraProject] = {}
            if projects.success:
                projects_by_id = {p.id: p for p in projects.result or []}

            result: list[WorkItemType] = []
            for item in response:
                scope_project: JiraProject | None = None
                if (
                    (scope := item.get('scope', {}))
                    and (scope_type := scope.get('type'))
                    and scope_type.lower() == 'project'
                ):
                    scope_project = projects_by_id.get(
                        str(get_nested(scope, 'project', 'id', default=''))
                    )

                result.append(
                    WorkItemType(
                        id=str(item.get('id')),
                        name=str(item.get('name', '')),
                        scope_project=scope_project,
                    )
                )
            await run_cache_io(lambda: self.cache.set_work_item_types(result))
            return APIControllerResponse(result=result)

    async def search_users(self, email_or_name: str) -> APIControllerResponse:
        """Searches users by email or name

        Args:
            email_or_name: the email or name to filter users

        Returns:
            An instance of `APIControllerResponse` with the list of `JiraUser` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """
        try:
            response: list[dict] = await self.client.user_search(query=f'{email_or_name}')
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find users',
                extra={
                    'email_or_name': email_or_name,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        return APIControllerResponse(result=self._build_jira_users(response))

    async def search_users_assignable_to_work_item(
        self,
        work_item_key: str,
        query: str | None = None,
        active: bool | None = True,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves the users that can be assigned to a work item.

        Args:
            work_item_key: the key (case-sensitive) of a work item.
            query: a string that is matched against user attributes, such as `displayName`, and `emailAddress`, to find
            relevant users. The string can match the prefix of the attribute's value. For example, `query=john` matches
            a user with a `displayName` of John Smith and a user with an `emailAddress` of johnson@example.com.
            active: if set to `True` (default) it will retrieve active users only.

        Returns:
            An instance of `APIControllerResponse` with the list of `JiraUser` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """

        project_key = work_item_key.split('-')[0] if work_item_key else None

        if not _coalesced:
            refresh = lambda: self.search_users_assignable_to_work_item(
                work_item_key,
                query,
                active,
                _coalesced=True,
            )
            return await self._assignable_users_cached_or_coalesced(
                cache_key=(
                    'assignable-work-item-users',
                    work_item_key.casefold(),
                    (query or '').casefold(),
                    active,
                ),
                project_key=project_key,
                query=query,
                refresh=refresh,
            )

        try:
            response: list[dict] = await self.client.user_assignable_search(
                work_item_key=work_item_key,
                query=query,
                offset=0,
                limit=RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_WORK_ITEMS,
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find users assignable to a work item',
                extra={
                    'work_item_key': work_item_key,
                    'query': query,
                    'limit': RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_WORK_ITEMS,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        sorted_users = self._filter_and_sort_jira_users(response, active=active)

        if not query and project_key:
            await run_cache_io(lambda: self.cache.set_project_users(project_key, sorted_users))

        return APIControllerResponse(result=sorted_users)

    async def search_users_assignable_to_projects(
        self,
        project_keys: list[str],
        query: str | None = None,
        active: bool | None = True,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves the users that can be assigned to work items in multiple projects.

        Args:
            project_keys: a list of project keys (case-sensitive).
            query: a string that is matched against user attributes, such as `displayName`, and `emailAddress`, to find
            relevant users. The string can match the prefix of the attribute's value. For example, `query=john` matches
            a user with a `displayName` of John Smith and a user with an `emailAddress` of johnson@example.com.
            active: if set to `True` (default) it will retrieve active users only.

        Returns:
            An instance of `APIFacadeResponse` with a list of `JiraUser` and `success = True`. If an error occurs then
            `success = False` and the error message in the `error` key.
        """

        if not _coalesced:
            refresh = partial(
                self.search_users_assignable_to_projects,
                project_keys=project_keys,
                query=query,
                active=active,
                _coalesced=True,
            )
            return await self._assignable_users_cached_or_coalesced(
                cache_key=(
                    'assignable-users',
                    tuple(project_key.casefold() for project_key in project_keys),
                    (query or '').casefold(),
                    active,
                ),
                project_key=project_keys[0] if len(project_keys) == 1 else None,
                query=query,
                refresh=refresh,
            )

        try:
            response: list[dict] = await self.client.user_assignable_multi_projects(
                project_keys=project_keys,
                query=query,
                offset=0,
                limit=RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_PROJECTS,
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find users assignable to a project',
                extra={
                    'project_keys': project_keys,
                    'query': query,
                    'limit': RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_PROJECTS,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        sorted_users = self._filter_and_sort_jira_users(response, active=active)

        if not query and len(project_keys) == 1:
            await run_cache_io(lambda: self.cache.set_project_users(project_keys[0], sorted_users))

        return APIControllerResponse(result=sorted_users)

    async def _assignable_users_cached_or_coalesced(
        self,
        *,
        cache_key: tuple[Any, ...],
        project_key: str | None,
        query: str | None,
        refresh: Callable[[], Coroutine[Any, Any, APIControllerResponse]],
    ) -> APIControllerResponse:
        if not query and project_key:
            return await self._cached_or_refresh(
                cache_key,
                lambda allow_stale: self.cache.get_project_users(
                    project_key,
                    allow_stale=allow_stale,
                ),
                refresh,
            )
        return await self._coalesce_request(cache_key, refresh)

    async def get_work_item(
        self,
        work_item_id_or_key: str,
        fields: list[str] | None = None,
        properties: str | None = None,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves a work item (aka. Jira work item) by its key or id.

        Args:
            work_item_id_or_key: the ID or case-sensitive key of the work item to retrieve.
            fields: a list of fields to return for the work item. This parameter accepts a comma-separated list. Use it
            to retrieve a subset of fields. Allowed values:
            - *all: Returns all fields.
            - *navigable: Returns navigable fields.
            - Any work item field, prefixed with a minus to exclude.
            properties: a list of work item properties to return for the work item. This parameter accepts a comma-separated
            list. Allowed values:
            - *all Returns all work item properties.
            - Any work item property key, prefixed with a minus to exclude.

        Returns:
            An instance of `APIFacadeResponse` with the work item and `success = True`. If an error occurs then
            `success = False` and the error message in the `error` key.
        """

        if fields is None:
            fields = ['*all', 'watches']
        if not _coalesced:
            requested_fields = list(fields)
            return await self._coalesce_request(
                (
                    'work-item',
                    work_item_id_or_key.casefold(),
                    tuple(requested_fields),
                    properties,
                ),
                lambda: self.get_work_item(
                    work_item_id_or_key,
                    fields=requested_fields,
                    properties=properties,
                    _coalesced=True,
                ),
            )

        fields_strings: str | None = ','.join(fields) if fields else None
        try:
            work_item: dict = await self.client.get_work_item(
                work_item_id_or_key=work_item_id_or_key,
                fields=fields_strings,
                properties=properties,
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve the work item',
                extra={
                    'work_item_id_or_key': work_item_id_or_key,
                    'fields': fields_strings,
                    'properties': properties,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        else:
            try:
                instance: JiraWorkItem = WorkItemFactory.create_work_item(work_item)
                summary = instance.summary or ''
                work_item_type = instance.work_item_type_name or ''
                status = instance.status.name if instance.status else ''
                if instance.key and summary and work_item_type and status:
                    self.cache_work_item_tooltip(
                        instance.key,
                        work_item_type,
                        summary,
                        status,
                    )
            except Exception as e:
                self.logger.error(
                    'There was an error while extracting data from a work item',
                    extra={'error': str(e), 'work_item_id_or_key': work_item_id_or_key},
                )
                return APIControllerResponse(
                    success=False,
                    error=f'Failed to extract the details of the requested work item {work_item_id_or_key}: {e!s}',
                )
            return APIControllerResponse(result=JiraWorkItemSearchResponse(work_items=[instance]))

    def _build_criteria_for_searching_work_items(
        self,
        search_filters: Mapping[str, Any],
    ) -> dict:
        project_key = search_filters.get('project_key')
        created_from = search_filters.get('created_from')
        created_until = search_filters.get('created_until')
        status = search_filters.get('status')
        assignee = search_filters.get('assignee')
        work_item_type = search_filters.get('work_item_type')
        jql_query = search_filters.get('jql_query')
        if jql_query:
            return {'jql': jql_query.strip(), 'updated_from': None}

        criteria_defined = any(
            [project_key, created_from, created_until, status, assignee, work_item_type]
        )
        if criteria_defined:
            return {}

        if (filter_label := self.config.jql_filter_label_for_work_items_search) and (
            jql_filters := self.config.jql_filters
        ):
            for filter_data in jql_filters:
                if (
                    filter_data.get('label') == filter_label
                    and (expression := filter_data.get('expression'))
                    and (cleaned_expression := expression.replace('\n', ' ').replace('\t', ' '))
                    and (jql_expression := cleaned_expression.strip())
                ):
                    return {'jql': jql_expression, 'updated_from': None}

        return {}

    async def _prepared_search_kwargs_or_response(
        self,
        search_filters: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, APIControllerResponse | None]:
        search_kwargs, validation_error = await self._prepare_search_work_item_api_kwargs(
            project_key=search_filters.get('project_key'),
            created_from=search_filters.get('created_from'),
            created_until=search_filters.get('created_until'),
            status=search_filters.get('status'),
            assignee=search_filters.get('assignee'),
            work_item_type=search_filters.get('work_item_type'),
            jql_query=search_filters.get('jql_query'),
        )
        return cast(dict[str, Any], search_kwargs), validation_error

    async def _resolve_search_kwargs(
        self,
        search_filters: dict[str, Any],
        prepared_search_kwargs: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, APIControllerResponse | None]:
        if prepared_search_kwargs is not None:
            return prepared_search_kwargs, None
        return await self._prepared_search_kwargs_or_response(search_filters)

    async def prepare_work_item_search(
        self,
        *,
        project_key: str | None = None,
        created_from: date | None = None,
        created_until: date | None = None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        jql_query: str | None = None,
    ) -> APIControllerResponse:
        """Build and validate reusable arguments for a work-item search."""
        search_kwargs, validation_error = await self._prepared_search_kwargs_or_response(locals())
        if validation_error:
            return validation_error
        return APIControllerResponse(result=search_kwargs)

    @staticmethod
    def _updated_fields_response(response: dict) -> APIControllerResponse:
        updated_fields: list[str] = []
        if fields := response.get('fields', {}):
            updated_fields = list(fields.keys())
        return APIControllerResponse(
            result=UpdateWorkItemResponse(success=True, updated_fields=updated_fields)
        )

    async def validate_jql_query(self, jql_query: str) -> APIControllerResponse:
        """Validates a JQL query by parsing it using Jira's JQL parse API.

        Args:
            jql_query: the JQL query string to validate.

        Returns:
            An instance of `APIControllerResponse` with success=True if valid, or error message if invalid.
        """
        if not jql_query or not jql_query.strip():
            return APIControllerResponse(success=False, error='JQL query cannot be empty.')

        try:
            response: dict = await self.client.parse_jql_query(jql_query=jql_query.strip())

            if 'queries' in response and len(response['queries']) > 0:
                query_result = response['queries'][0]

                if query_result.get('errors'):
                    error_messages = []
                    for error in query_result['errors']:
                        if isinstance(error, str):
                            error_messages.append(error)
                        elif isinstance(error, dict):
                            error_messages.append(error.get('message', str(error)))
                        else:
                            error_messages.append(str(error))

                    error_text = (
                        '; '.join(error_messages) if error_messages else 'Invalid JQL query.'
                    )
                    return APIControllerResponse(
                        success=False, error=f'JQL validation failed: {error_text}'
                    )

            return APIControllerResponse(success=True, result=response)
        except ServiceUnavailableException:
            return APIControllerResponse(
                success=False, error='Unable to connect to the Jira server to validate JQL.'
            )
        except ServiceInvalidResponseException:
            return APIControllerResponse(
                success=False,
                error='The Jira server returned an invalid response during JQL validation.',
            )
        except Exception as e:
            self.logger.warning(f'JQL validation failed with error: {e!s}')
            return APIControllerResponse(
                success=False, error=f'Failed to validate JQL query: {e!s}'
            )

    async def search_work_items(
        self,
        jql_query: str | None = None,
        search_in_active_sprint: bool = False,
        project_key: str | None = None,
        status: int | None = None,
        created_from: date | None = None,
        assignee: str | None = None,
        created_until: date | None = None,
        work_item_type: int | None = None,
        next_page_token: str | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        prepared_search_kwargs: dict[str, Any] | None = None,
    ) -> APIControllerResponse:
        """Searches for work items matching specified JQL query and other criteria.

        Args:
            project_key: the case-sensitive key of the project whose work items we want to search.
            created_from: search work items created from this date forward (inclusive).
            created_until: search work items created until this date (inclusive).
            status: search work items with this status.
            assignee: search work items assigned to this user's account ID.
            work_item_type: search work items of this type.
            search_in_active_sprint: if `True` only work items that belong to the currently active sprint will be
            retrieved.
            jql_query: search work items using this (additional) JQL query.
            next_page_token: the token that identifies the next page of results. This helps implements pagination of
            results.
            limit: the maximum number of items to retrieve.
            fields: the fields to retrieve for every work item. It defaults to: `'id', 'key', 'status', 'summary',
            'issuetype'`

        Returns:
            An instance of `APIControllerResponse` with the work items found or, en error if the search can not be
            performed.
        """
        resolved_kwargs, validation_error = await self._resolve_search_kwargs(
            locals(), prepared_search_kwargs
        )
        if validation_error is not None:
            return validation_error
        search_kwargs = cast(dict[str, Any], resolved_kwargs)

        try:
            response: dict = await self.client.search_work_items(
                **search_kwargs,
                search_in_active_sprint=search_in_active_sprint,
                fields=fields
                if fields
                else [
                    'id',
                    'key',
                    'status',
                    'summary',
                    'issuetype',
                    'parent',
                    'priority',
                    'assignee',
                ],
                next_page_token=next_page_token,
                limit=limit,
            )
        except ServiceUnavailableException:
            return APIControllerResponse(
                success=False, error='Unable to connect to the Jira server.'
            )
        except ServiceInvalidResponseException:
            return APIControllerResponse(
                success=False, error='The response from the server contains errors.'
            )
        except Exception as e:
            return APIControllerResponse(
                success=False,
                error=f'There was an unknown error while searching for work items: {e!s}',
            )
        work_items: list[JiraWorkItem] = []
        work_item: JiraWorkItem
        for work_item in response.get('issues', []):
            try:
                work_item = WorkItemFactory.create_work_item(work_item)
                work_items.append(work_item)
            except Exception as e:
                self.logger.warning(f'Failed to parse work item: {e}')
                continue

        return APIControllerResponse(
            result=JiraWorkItemSearchResponse(
                work_items=work_items,
                next_page_token=response.get('nextPageToken'),
                is_last=response.get('isLast'),
            )
        )

    async def count_work_items(
        self,
        jql_query: str | None = None,
        project_key: str | None = None,
        status: int | None = None,
        created_from: date | None = None,
        work_item_type: int | None = None,
        created_until: date | None = None,
        assignee: str | None = None,
        prepared_search_kwargs: dict[str, Any] | None = None,
    ) -> APIControllerResponse:
        """Estimates the number of work items yield by a search.

        Args:
            jql_query: additional JQL expression used to constrain the count.
            project_key: project key filter.
            status: Jira status id filter.
            created_from: inclusive lower creation date bound.
            work_item_type: Jira work item type id filter.
            created_until: inclusive upper creation date bound.
            assignee: Jira account id filter.

        Returns:
            The approximate count response, or an error response when Jira rejects the query.
        """
        search_kwargs, validation_error = await self._resolve_search_kwargs(
            locals(), prepared_search_kwargs
        )
        if validation_error:
            return validation_error
        assert search_kwargs is not None

        try:
            response: dict = await self.client.work_items_search_approximate_count(**search_kwargs)
        except NotImplementedError:
            return APIControllerResponse(result=0)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to estimate the number of work items', extra=exception_details.get('extra')
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        return APIControllerResponse(result=int(response.get('count', 0)))

    async def get_work_item_remote_links(
        self, work_item_key_or_id: str, global_id: str | None = None
    ) -> APIControllerResponse:
        """Retrieves the web links of a work item.

        Args:
            work_item_key_or_id: the ID or case-sensitive key of a work item whose web links we want to retrieve.
            global_id: an optional global ID that identifies a Web Link.

        Returns:
            An instance of `APIControllerResponse` with the list of `IssueRemoteLink` or, `success = False` with
            an `error` key if there is an error.
        """

        return await self._execute_result_api_operation(
            self.client.get_work_item_remote_links(work_item_key_or_id, global_id),
            result_builder=self._build_work_item_remote_links,
            error_message='Unable to retrieve the web links of a work item',
            extra={
                'work_item_id_or_key': work_item_key_or_id,
                'global_id': global_id,
            },
        )

    async def create_work_item_remote_link(
        self, work_item_key_or_id: str, url: str, title: str
    ) -> APIControllerResponse:
        if 'http' not in url:
            return APIControllerResponse(
                success=False, error='The url must be a full url including the http:// schema.'
            )
        if not title:
            title = url
        return await self._execute_void_api_operation(
            self.client.create_work_item_remote_link(work_item_key_or_id, url, title),
            error_message='Unable to create the web link',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'web_url': url,
                'title': title,
            },
        )

    async def delete_work_item_remote_link(
        self, work_item_key_or_id: str, link_id: str
    ) -> APIControllerResponse:
        """Deletes a web link associated to a work item.

        Args:
            work_item_key_or_id: the (case-sensitive) key of the work item.
            link_id: the ID of the link we want to delete.

        Returns:
           An instance of `APIControllerResponse(success=True)` if the link was
           deleted; `APIControllerResponse(success=False)` otherwise.
        """
        return await self._execute_void_api_operation(
            self.client.delete_work_item_remote_link(work_item_key_or_id, link_id),
            error_message='Unable to delete web link',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'link_id': link_id,
            },
        )

    async def update_work_item_remote_link(
        self, work_item_key_or_id: str, link_id: str, url: str, title: str
    ) -> APIControllerResponse:
        """Updates a web link associated to a work item.

        Args:
            work_item_key_or_id: the (case-sensitive) key of the work item.
            link_id: the ID of the link we want to update.
            url: the URL of the link.
            title: the title of the link.

        Returns:
           An instance of `APIControllerResponse(success=True)` if the link was
           updated; `APIControllerResponse(success=False)` otherwise.
        """
        return await self._execute_void_api_operation(
            self.client.update_work_item_remote_link(work_item_key_or_id, link_id, url, title),
            error_message='Unable to update web link',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'link_id': link_id,
                'url': url,
                'title': title,
            },
        )

    async def get_work_item_watchers(self, work_item_key_or_id: str) -> APIControllerResponse:
        """Retrieves the watchers of a work item."""
        return await self._execute_result_api_operation(
            self.client.get_work_item_watchers(work_item_key_or_id),
            result_builder=self._build_work_item_watchers,
            error_message='Unable to retrieve the watchers of a work item',
            extra={'work_item_key_or_id': work_item_key_or_id},
        )

    async def add_work_item_watcher(
        self, work_item_key_or_id: str, account_id: str | None = None
    ) -> APIControllerResponse:
        """Adds a watcher to a work item. Defaults to the authenticated user."""
        return await self._execute_void_api_operation(
            self.client.add_work_item_watcher(work_item_key_or_id, account_id),
            error_message='Unable to add watcher',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'account_id': account_id,
            },
        )

    async def remove_work_item_watcher(
        self, work_item_key_or_id: str, account_id: str
    ) -> APIControllerResponse:
        """Removes a watcher from a work item."""
        return await self._execute_void_api_operation(
            self.client.remove_work_item_watcher(work_item_key_or_id, account_id),
            error_message='Unable to remove watcher',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'account_id': account_id,
            },
        )

    async def global_settings(self, *, _coalesced: bool = False) -> APIControllerResponse:
        """Retrieves the global settings of the Jira instance.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the details or,
            `APIControllerResponse(success=False)` if there is an error fetching the details.
        """
        if not _coalesced:
            return await self._fresh_cached_or_refresh(
                ('global_settings',),
                self.cache.get_global_settings,
                lambda: self.global_settings(_coalesced=True),
            )

        try:
            response: dict = await self.client.global_settings()
        except Exception as e:
            return self._server_information_error_response(e)

        time_tracking_configuration = None
        if values := response.get('timeTrackingConfiguration'):
            time_tracking_configuration = JiraTimeTrackingConfiguration(
                default_unit=values.get('defaultUnit'),
                time_format=values.get('timeFormat'),
                working_days_per_week=values.get('workingDaysPerWeek'),
                working_hours_per_day=values.get('workingHoursPerDay'),
            )

        global_settings = JiraGlobalSettings(
            attachments_enabled=bool(response.get('attachmentsEnabled', False)),
            work_item_linking_enabled=bool(response.get('issueLinkingEnabled', False)),
            subtasks_enabled=bool(response.get('subTasksEnabled', False)),
            unassigned_work_items_allowed=bool(response.get('unassignedIssuesAllowed', False)),
            voting_enabled=bool(response.get('votingEnabled', False)),
            watching_enabled=bool(response.get('watchingEnabled', False)),
            time_tracking_enabled=bool(response.get('timeTrackingEnabled', False)),
            time_tracking_configuration=time_tracking_configuration,
        )
        await run_cache_io(lambda: self.cache.set_global_settings(global_settings))
        return APIControllerResponse(result=global_settings)

    async def server_info(self, *, _coalesced: bool = False) -> APIControllerResponse:
        """Retrieves details of the Jira server instance.

        Returns:
            Server metadata in a successful response. Failures contain the Jira error details.
        """
        if not _coalesced:
            return await self._fresh_cached_or_refresh(
                ('server_info',),
                self.cache.get_server_info,
                lambda: self.server_info(_coalesced=True),
            )

        try:
            response: dict = await self.client.server_info()
        except Exception as e:
            return self._server_information_error_response(e)
        server_info = JiraServerInfo(
            base_url=str(response.get('baseUrl', '')),
            display_url_servicedesk_help_center=response.get('displayUrlServicedeskHelpCenter'),
            display_url_confluence=response.get('displayUrlConfluence'),
            version=str(response.get('version', '')),
            deployment_type=response.get('deploymentType'),
            build_number=int(response.get('buildNumber', 0)),
            build_date=str(response.get('buildDate', '')),
            server_time=response.get('serverTime'),
            server_title=str(response.get('serverTitle', '')),
            default_locale=get_nested(response, 'defaultLocale', 'locale'),
            server_time_zone=response.get('serverTimeZone'),
        )
        await run_cache_io(lambda: self.cache.set_server_info(server_info))
        return APIControllerResponse(result=server_info)

    async def myself(self) -> APIControllerResponse:
        """Retrieves details of the Jira user connecting to the API.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the details or,
            `APIControllerResponse(success=False)` if there is an error fetching the details.
        """
        try:
            if self.config.jira.auth_type == 'oauth2' and self.identity_api is not None:
                identity_result, jira_result = await asyncio.gather(
                    self.identity_api.make_request(
                        method=httpx.AsyncClient.get,
                        url='me',
                        headers={'Accept': 'application/json'},
                    ),
                    self.client.myself(),
                )
                identity_response = cast(dict, identity_result)
                jira_response = cast(dict, jira_result)
                result = JiraMyselfInfo(
                    account_id=str(
                        identity_response.get('account_id') or jira_response.get('accountId', '')
                    ),
                    account_type=str(
                        identity_response.get('account_type')
                        or jira_response.get('accountType', '')
                    ),
                    active=str(
                        identity_response.get('account_status')
                        or ('active' if jira_response.get('active', False) else 'inactive')
                    ).lower()
                    == 'active',
                    display_name=str(
                        identity_response.get('name')
                        or identity_response.get('nickname')
                        or jira_response.get('displayName')
                        or identity_response.get('account_id')
                        or ''
                    ),
                    email=identity_response.get('email') or jira_response.get('emailAddress'),
                    groups=[
                        JiraUserGroup(id=g.get('id'), name=g.get('name'))
                        for g in get_nested(jira_response, 'groups', 'items', default=[])
                    ],
                )
            else:
                response = await self.client.myself()
                result = JiraMyselfInfo(
                    account_id=str(response.get('accountId', '')),
                    account_type=str(response.get('accountType', '')),
                    active=bool(response.get('active', False)),
                    display_name=str(response.get('displayName', '')),
                    email=response.get('emailAddress'),
                    groups=[
                        JiraUserGroup(id=g.get('id'), name=g.get('name'))
                        for g in get_nested(response, 'groups', 'items', default=[])
                    ],
                )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse(result=result)

    async def update_work_item(
        self, work_item: JiraWorkItem, updates: dict
    ) -> APIControllerResponse:
        """Updates a work item.

        Args:
            work_item: the work item we want to update.
            updates: a dictionary with the Jira fields that we want to update and their corresponding values.

        Returns:
            An instance of `APIControllerResponse` with the result of the update, which may include a list of fields
            that were updated.

        Raises:
            UpdateWorkItemException: if the work item's edit metadata is missing.
            UpdateWorkItemException: if the work item's edit metadata does not include details of the fields that can
            be updated.
            UpdateWorkItemException: When any of the fields that we want to update do not support updates.
            ValidationError: If the summary field is empty.
        """

        if not (edit_work_item_metadata := work_item.edit_meta):
            raise UpdateWorkItemException('Missing expected metadata.')

        if not (metadata_fields := edit_work_item_metadata.get('fields', {})):
            raise UpdateWorkItemException(
                'The selected work item does not include the required fields metadata.'
            )

        if JiraWorkItemGenericFields.SUMMARY.value in updates and (
            not (summary := updates.get(JiraWorkItemGenericFields.SUMMARY.value))
            or not summary.strip()
        ):
            raise ValidationError('The summary field can not be empty.')

        fields_to_update: dict[str, list] = {}
        direct_fields_to_update: dict[str, Any] = {}

        if JiraWorkItemGenericFields.SUMMARY.value in updates:
            if meta_summary := metadata_fields.get(JiraWorkItemGenericFields.SUMMARY.value, {}):
                if 'set' not in meta_summary.get('operations', {}):
                    raise UpdateWorkItemException(
                        f'The field {JiraWorkItemGenericFields.SUMMARY.value} can not be updated for the selected work item.',
                        extra={'work_item_key': work_item.key},
                    )
                fields_to_update[JiraWorkItemGenericFields.SUMMARY.value] = [
                    {'set': updates.get(JiraWorkItemGenericFields.SUMMARY.value)}
                ]
            else:
                raise UpdateWorkItemException(
                    f'The field {JiraWorkItemGenericFields.SUMMARY.value} can not be updated for the selected work item.',
                    extra={'work_item_key': work_item.key},
                )

        if JiraWorkItemGenericFields.DUE_DATE.value in updates:
            if meta_due_date := metadata_fields.get(JiraWorkItemGenericFields.DUE_DATE.value, {}):
                if 'set' not in meta_due_date.get('operations', {}):
                    raise UpdateWorkItemException(
                        f'The field {JiraWorkItemGenericFields.DUE_DATE.value} can not be updated for the selected work item.',
                        extra={'work_item_key': work_item.key},
                    )
                fields_to_update[JiraWorkItemGenericFields.DUE_DATE.value] = [
                    {'set': updates.get(JiraWorkItemGenericFields.DUE_DATE.value) or None}
                ]
            else:
                raise UpdateWorkItemException(
                    f'The field {JiraWorkItemGenericFields.DUE_DATE.value} can not be updated for the selected work item.',
                    extra={'work_item_key': work_item.key},
                )

        if JiraWorkItemGenericFields.PRIORITY.value in updates:
            if meta_priority := metadata_fields.get(JiraWorkItemGenericFields.PRIORITY.value, {}):
                if 'set' not in meta_priority.get('operations', {}):
                    raise UpdateWorkItemException(
                        f'The field {JiraWorkItemGenericFields.PRIORITY.value} can not be updated for the selected work item.',
                        extra={'work_item_key': work_item.key},
                    )
                fields_to_update[JiraWorkItemGenericFields.PRIORITY.value] = [
                    {'set': {'id': updates.get(JiraWorkItemGenericFields.PRIORITY.value)}}
                ]
            else:
                raise UpdateWorkItemException(
                    f'The field {JiraWorkItemGenericFields.PRIORITY.value} can not be updated for the selected work item.',
                    extra={'work_item_key': work_item.key},
                )

        if JiraWorkItemGenericFields.PARENT.value in updates:
            if meta_parent := metadata_fields.get(JiraWorkItemGenericFields.PARENT.value, {}):
                if 'set' not in meta_parent.get('operations', {}):
                    raise UpdateWorkItemException(
                        f'The field {JiraWorkItemGenericFields.PARENT.value} can not be updated for the selected work item.',
                        extra={'work_item_key': work_item.key},
                    )
                parent_key = updates.get(JiraWorkItemGenericFields.PARENT.value)
                if parent_key:
                    direct_fields_to_update[JiraWorkItemGenericFields.PARENT.value] = {
                        'key': parent_key
                    }
                else:
                    fields_to_update[JiraWorkItemGenericFields.PARENT.value] = [
                        {'set': {'none': True}}
                    ]
            else:
                raise UpdateWorkItemException(
                    f'The field {JiraWorkItemGenericFields.PARENT.value} can not be updated for the selected work item.',
                    extra={'work_item_key': work_item.key},
                )

        if 'assignee_account_id' in updates:
            if meta_assignee := metadata_fields.get('assignee', {}):
                if 'set' not in meta_assignee.get('operations', {}):
                    raise UpdateWorkItemException(
                        'The field assignee can not be updated for the selected work item.',
                        extra={'work_item_key': work_item.key},
                    )
                assignee_account_id = updates.get('assignee_account_id')
                fields_to_update[meta_assignee.get('key')] = [
                    {'set': {'accountId': assignee_account_id} if assignee_account_id else None}
                ]
            else:
                raise UpdateWorkItemException(
                    'The field assignee_account_id can not be updated for the selected work item.',
                    extra={'work_item_key': work_item.key},
                )

        if JiraWorkItemGenericFields.LABELS.value in updates:
            if meta_labels := metadata_fields.get(JiraWorkItemGenericFields.LABELS.value, {}):
                if 'set' in meta_labels.get('operations', {}):
                    fields_to_update[JiraWorkItemGenericFields.LABELS.value] = [
                        {'set': updates.get(JiraWorkItemGenericFields.LABELS.value)}
                    ]

        if JiraWorkItemGenericFields.COMPONENTS.value in updates:
            if meta_components := metadata_fields.get(
                JiraWorkItemGenericFields.COMPONENTS.value, {}
            ):
                if 'set' not in meta_components.get('operations', {}):
                    raise UpdateWorkItemException(
                        f'The field {JiraWorkItemGenericFields.COMPONENTS.value} can not be updated for the selected work item.',
                        extra={'work_item_key': work_item.key},
                    )
                fields_to_update[JiraWorkItemGenericFields.COMPONENTS.value] = [
                    {'set': updates.get(JiraWorkItemGenericFields.COMPONENTS.value)}
                ]
            else:
                raise UpdateWorkItemException(
                    f'The field {JiraWorkItemGenericFields.COMPONENTS.value} can not be updated for the selected work item.',
                    extra={'work_item_key': work_item.key},
                )

        if JiraWorkItemGenericFields.DESCRIPTION.value in updates:
            if meta_description := metadata_fields.get(
                JiraWorkItemGenericFields.DESCRIPTION.value, {}
            ):
                if 'set' not in meta_description.get('operations', {}):
                    raise UpdateWorkItemException(
                        f'The field {JiraWorkItemGenericFields.DESCRIPTION.value} can not be updated for the selected work item.',
                        extra={'work_item_key': work_item.key},
                    )

                description_value = updates.get(JiraWorkItemGenericFields.DESCRIPTION.value)
                if description_value:
                    from gojeera.utils.markdown.adf_helpers import text_to_adf

                    adf_content = text_to_adf(description_value)
                    fields_to_update[JiraWorkItemGenericFields.DESCRIPTION.value] = [
                        {'set': adf_content}
                    ]
                else:
                    fields_to_update[JiraWorkItemGenericFields.DESCRIPTION.value] = [{'set': None}]
            else:
                raise UpdateWorkItemException(
                    f'The field {JiraWorkItemGenericFields.DESCRIPTION.value} can not be updated for the selected work item.',
                    extra={'work_item_key': work_item.key},
                )

        if self.config.enable_updating_additional_fields:
            for field_id, field_value in updates.items():
                if field_id in [
                    JiraWorkItemGenericFields.SUMMARY.value,
                    JiraWorkItemGenericFields.DESCRIPTION.value,
                    JiraWorkItemGenericFields.DUE_DATE.value,
                    JiraWorkItemGenericFields.PRIORITY.value,
                    JiraWorkItemGenericFields.PARENT.value,
                    'assignee_account_id',
                    JiraWorkItemGenericFields.LABELS.value,
                    JiraWorkItemGenericFields.COMPONENTS.value,
                ]:
                    continue
                else:
                    if metadata := metadata_fields.get(field_id, {}):
                        if 'set' in metadata.get('operations', {}):
                            fields_to_update[field_id] = [{'set': field_value}]
                    else:
                        raise UpdateWorkItemException(
                            f'The field {field_id} can not be updated for the selected work item.',
                            extra={'work_item_key': work_item.key},
                        )

        if fields_to_update or direct_fields_to_update:
            response: dict = await self.client.update_work_item(
                work_item.key,
                payload=fields_to_update,
                fields=direct_fields_to_update,
            )
            self.invalidate_work_item_tooltip(work_item.key)
            if JiraWorkItemGenericFields.PARENT.value in updates:
                verification_response = await self.get_work_item(
                    work_item_id_or_key=work_item.key,
                    fields=['parent'],
                )
                if not verification_response.success or not verification_response.result:
                    return APIControllerResponse(
                        success=False,
                        error='The parent update request completed but the new parent could not be verified.',
                    )

                refreshed_items = verification_response.result.work_items or []
                if not refreshed_items:
                    return APIControllerResponse(
                        success=False,
                        error='The parent update request completed but the issue could not be reloaded.',
                    )

                refreshed_parent_key = refreshed_items[0].parent_key.strip()
                expected_parent_key = str(
                    updates.get(JiraWorkItemGenericFields.PARENT.value) or ''
                ).strip()
                if refreshed_parent_key != expected_parent_key:
                    return APIControllerResponse(
                        success=False,
                        error='Jira accepted the request but the parent work item was not changed.',
                    )
            return self._updated_fields_response(response)
        return APIControllerResponse(result=UpdateWorkItemResponse(success=True))

    async def set_work_item_flagged(
        self, work_item: JiraWorkItem, flagged: bool
    ) -> APIControllerResponse:
        """Sets or clears the Jira Software Flagged field for a work item."""

        fields_response = await self.get_fields('flagged')
        if not fields_response.success or not fields_response.result:
            return APIControllerResponse(
                success=False,
                error='Unable to flag the item. Missing fields configuration.',
            )

        fields = cast(list[JiraField], fields_response.result)
        if not fields:
            return APIControllerResponse(
                success=False,
                error='Unable to flag the item. Missing fields configuration.',
            )

        field_configuration = fields[0]
        if not field_configuration.key:
            return APIControllerResponse(
                success=False,
                error='Unable to flag the item. Missing configuration for "flagged" field.',
            )

        field_value: list[dict[str, str]]
        if flagged:
            field_value = [{'value': 'Impediment'}]
        else:
            field_value = []

        try:
            response: dict = await self.client.update_work_item(
                work_item.key,
                fields={field_configuration.key: field_value},
            )
            return self._updated_fields_response(response)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to update the Flagged field of the work item',
                extra={
                    'work_item_key': work_item.key,
                    'flagged': flagged,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

    async def transitions(self, work_item_id_or_key: str) -> APIControllerResponse:
        """Retrieves the applicable (status) transitions of a work item.

        Args:
            work_item_id_or_key: the (case-sensitive) key of the work item.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the list of `IssueTransition` instances or,
            `APIControllerResponse(success=False)` if there is an error fetching the data.
        """
        return await self._execute_result_api_operation(
            self.client.transitions(work_item_id_or_key),
            result_builder=self._build_work_item_transitions,
            error_message='Unable to retrieve status transitions for the work item',
            extra={'work_item_id_or_key': work_item_id_or_key},
        )

    async def transition_work_item_status(
        self, work_item_id_or_key: str, transition_id: str
    ) -> APIControllerResponse:
        """Transitions a work item using a Jira transition ID.

        Args:
            work_item_id_or_key: the (case-sensitive) key of the work item.
            transition_id: the ID of the Jira transition to execute.

        Returns:
            An instance of `APIControllerResponse(success=True)` if the work item was transitioned;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            await self.client.transition_work_item(work_item_id_or_key, transition_id)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to update the status of the work item',
                extra={
                    'work_item_id_or_key': work_item_id_or_key,
                    'transition_id': transition_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        self.invalidate_work_item_tooltip(work_item_id_or_key)
        return APIControllerResponse()

    async def get_comment(self, work_item_key_or_id: str, comment_id: str) -> APIControllerResponse:
        """Retrieves the details of a comment.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            comment_id: the id of the comment.

        Returns:
            An instance of `APIControllerResponse` with the `IssueComment` instance in the `result key;
            `success=False` and the detail of the error if one occurs.
        """
        return await self._execute_result_api_operation(
            self.client.get_comment(work_item_key_or_id, comment_id),
            result_builder=self._build_work_item_comment,
            error_message='Unable to fetch the comment',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'comment_id': comment_id,
            },
        )

    async def get_comments(
        self,
        work_item_key_or_id: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> APIControllerResponse:
        """Retrieves the comments of a work item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page.

        Returns:
            An instance of `APIControllerResponse` with the list of `IssueComment` instances in the `result key;
            `success=False` and the detail of the error if one occurs.
        """
        return await self._execute_result_api_operation(
            self.client.get_comments(work_item_key_or_id, offset, limit),
            result_builder=self._build_work_item_comments,
            error_message='Unable to fetch comments',
            extra={'work_item_key_or_id': work_item_key_or_id},
        )

    async def get_work_item_history(
        self,
        work_item_key_or_id: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> APIControllerResponse:
        """Retrieves the changelog history of a work item."""
        return await self._execute_result_api_operation(
            self.client.get_work_item_changelog(work_item_key_or_id, offset, limit),
            result_builder=self._build_work_item_history,
            error_message='Unable to fetch work item history',
            extra={'work_item_key_or_id': work_item_key_or_id},
        )

    async def add_comment(
        self,
        work_item_key_or_id: str,
        message: str,
        jsd_public: bool | None = None,
    ) -> APIControllerResponse:
        """Adds a comment to a work item."""
        if validation_error := self._validate_message_presence(message):
            return validation_error
        return await self._execute_result_api_operation(
            self.client.add_comment(
                work_item_key_or_id,
                message,
                jsd_public=jsd_public,
            ),
            result_builder=self._build_work_item_comment,
            error_message='Unable to create the comment',
            extra={'work_item_key_or_id': work_item_key_or_id},
        )

    async def update_comment(
        self,
        work_item_key_or_id: str,
        comment_id: str,
        message: str,
    ) -> APIControllerResponse:
        """Updates a comment on a work item."""
        if validation_error := self._validate_message_presence(message):
            return validation_error
        return await self._execute_result_api_operation(
            self.client.update_comment(
                work_item_key_or_id,
                comment_id,
                message,
            ),
            result_builder=self._build_work_item_comment,
            error_message='Unable to update the comment',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'comment_id': comment_id,
            },
        )

    async def delete_comment(
        self, work_item_key_or_id: str, comment_id: str
    ) -> APIControllerResponse:
        """Deletes a comment from a work item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            comment_id: the id of a comment.

        Returns:
            An instance of `APIControllerResponse` with the result of the operation.
        """
        return await self._execute_void_api_operation(
            self.client.delete_comment(work_item_key_or_id, comment_id),
            error_message='Unable to delete the comment',
            extra={
                'work_item_key_or_id': work_item_key_or_id,
                'comment_id': comment_id,
            },
        )

    async def link_work_items(
        self,
        left_work_item_key: str,
        right_work_item_key: str,
        link_type: str,
        link_type_id: str,
    ) -> APIControllerResponse:
        """Creates a link between 2 work items.

        Args:
            left_work_item_key: the (case-sensitive) key of the work item.
            right_work_item_key: the (case-sensitive) key of the work item.
            link_type: the type of link to create.
            link_type_id: the ID of the type of link.

        Returns:
            An instance of `APIControllerResponse(success=True)` if the work items were linked successfully;
            `APIControllerResponse(success=False)` if there is an error.
        """
        return await self._execute_void_api_operation(
            self.client.create_work_item_link(
                left_work_item_key=left_work_item_key,
                right_work_item_key=right_work_item_key,
                link_type=link_type,
                link_type_id=link_type_id,
            ),
            error_message='Unable to link items',
            extra={
                'left_work_item_key': left_work_item_key,
                'link_type': link_type,
                'link_type_id': link_type_id,
            },
        )

    async def delete_work_item_link(self, link_id: str) -> APIControllerResponse:
        """Deletes the link between 2 work items.

        Args:
            link_id: the ID of the link to delete.

        Returns:
            An instance of `APIControllerResponse(success=True)` if the work items were unlinked successfully;
            `APIControllerResponse(success=False)` if there is an error.
        """
        return await self._execute_void_api_operation(
            self.client.delete_work_item_link(link_id),
            error_message='Unable to delete link between items',
            extra={'link_id': link_id},
        )

    async def work_item_link_types(self) -> APIControllerResponse:
        """Retrieves the types of links that can be created between 2 work items.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the list of `LinkIssueType` instances;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            response: dict = await self.client.work_item_link_types()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to fetch the type of links',
                extra=exception_details.get('extra'),
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        link_types: list[LinkWorkItemType] = []
        for work_item_link_type in response.get('issueLinkTypes', []):
            link_types.append(
                LinkWorkItemType(
                    id=work_item_link_type.get('id'),
                    name=work_item_link_type.get('name'),
                    inward=work_item_link_type.get('inward'),
                    outward=work_item_link_type.get('outward'),
                )
            )
        return APIControllerResponse(result=link_types)

    async def clone_work_item(
        self,
        work_item: JiraWorkItem,
        link_to_original: bool = True,
        custom_summary: str | None = None,
    ) -> APIControllerResponse:
        """Clones a work item.

        Args:
            work_item: the work item to clone.
            link_to_original: if True, creates a "Cloners" link between the original and cloned items.
            custom_summary: optional custom summary for the cloned work item. If not provided,
                defaults to "CLONE - {original_summary}".

        Returns:
            An instance of `APIControllerResponse(success=True)` with the cloned work item key;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            # Validate required fields
            if not work_item.project or not work_item.work_item_type:
                return APIControllerResponse(
                    success=False, error='Work item must have a project and work item type'
                )

            fields_to_clone: dict[str, Any] = {}

            fields_to_clone['project'] = {'id': work_item.project.id}
            fields_to_clone['issuetype'] = {'id': work_item.work_item_type.id}
            fields_to_clone['summary'] = custom_summary or f'CLONE - {work_item.summary}'

            if work_item.description:
                fields_to_clone['description'] = work_item.description

            if work_item.priority:
                fields_to_clone['priority'] = {'id': work_item.priority.id}

            if work_item.labels:
                fields_to_clone['labels'] = work_item.labels

            if hasattr(work_item, 'components') and work_item.components:
                fields_to_clone['components'] = [{'id': c.id} for c in work_item.components]

            versions = cast(list[Any] | None, getattr(work_item, 'versions', None))
            if versions:
                fields_to_clone['versions'] = [{'id': v.id} for v in versions]

            fix_versions = cast(list[Any] | None, getattr(work_item, 'fix_versions', None))
            if fix_versions:
                fields_to_clone['fixVersions'] = [{'id': v.id} for v in fix_versions]

            if work_item.assignee and work_item.assignee.account_id:
                fields_to_clone['assignee'] = {'accountId': work_item.assignee.account_id}

            if (
                work_item.parent_key
                and work_item.work_item_type
                and work_item.work_item_type.hierarchy_level != 0
            ):
                fields_to_clone['parent'] = {'key': work_item.parent_key}

            create_meta_response = await self.client.get_work_item_create_meta(
                work_item.project.key,
                work_item.work_item_type.id,
            )

            if create_meta_response:
                raw_fields: dict = (
                    cast(dict, work_item.raw_fields) if hasattr(work_item, 'raw_fields') else {}
                )

                create_fields = create_meta_response.get('fields', {})

                if not isinstance(create_fields, dict):
                    if isinstance(create_fields, list) and len(create_fields) > 0:
                        field_list = create_fields
                    else:
                        field_list = create_meta_response.get('values', [])

                    if isinstance(field_list, list) and len(field_list) > 0:
                        create_fields = {}
                        for field_obj in field_list:
                            if field_id := field_obj.get('fieldId'):
                                create_fields[field_id] = field_obj
                    else:
                        self.logger.warning('Could not find valid field metadata in response')
                        create_fields = {}

                if create_fields and isinstance(create_fields, dict):
                    for field_id, field_meta in create_fields.items():
                        if field_id in fields_to_clone:
                            continue

                        if field_id.startswith('customfield_') or field_id not in [
                            'project',
                            'issuetype',
                            'summary',
                            'description',
                            'priority',
                            'labels',
                            'components',
                            'versions',
                            'fixVersions',
                            'assignee',
                            'parent',
                        ]:
                            field_required = field_meta.get('required', False)
                            field_schema = field_meta.get('schema', {})
                            field_type = field_schema.get('type')

                            current_value = raw_fields.get(field_id)

                            if current_value is not None:
                                if field_required or field_type in [
                                    'string',
                                    'number',
                                    'date',
                                    'datetime',
                                    'option',
                                    'array',
                                    'user',
                                    'group',
                                ]:
                                    fields_to_clone[field_id] = current_value
                            elif field_required:
                                if allowed_values := field_meta.get('allowedValues', []):
                                    if allowed_values and isinstance(allowed_values, list):
                                        first_value = allowed_values[0]
                                        if isinstance(first_value, dict) and 'id' in first_value:
                                            value = {'id': first_value['id']}

                                            if field_type == 'array':
                                                value = [value]
                                            fields_to_clone[field_id] = value
                                        elif isinstance(first_value, dict):
                                            value = first_value

                                            if field_type == 'array':
                                                value = [value]
                                            fields_to_clone[field_id] = value

            cloned_item = await self.client.clone_work_item(
                work_item_id_or_key=work_item.key,
                fields_to_clone=fields_to_clone,
                link_to_original=link_to_original,
            )

            cloned_key = cloned_item.get('key')
            return APIControllerResponse(result={'key': cloned_key, 'id': cloned_item.get('id')})

        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)

            error_message = exception_details.get('message', 'Unknown error')
            extra_info = exception_details.get('extra', {})

            if errors := extra_info.get('errors'):
                missing_fields = []

                if isinstance(errors, dict):
                    for field_id, field_error in errors.items():
                        if 'required' in str(field_error).lower():
                            missing_fields.append(f'{field_id}: {field_error}')
                elif isinstance(errors, list):
                    missing_fields = [str(err) for err in errors if 'required' in str(err).lower()]

                if missing_fields:
                    error_message = (
                        f'Clone failed due to missing required fields: {", ".join(missing_fields)}'
                    )

            self.logger.error(
                'Unable to clone work item',
                extra={
                    'work_item_key': work_item.key,
                    **extra_info,
                },
            )
            return APIControllerResponse(success=False, error=error_message)

    async def get_work_item_create_metadata(
        self,
        project_id_or_key: str,
        work_item_type_id: str,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves the metadata relevant for creating work items of a project and of a certain type.

        Args:
            project_id_or_key: the (case-sensitive) key of the project.
            work_item_type_id: the ID of the type of work item.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the metadata;
            `APIControllerResponse(success=False)` if there is an error.
        """
        if not _coalesced:
            return await self._coalesce_request(
                (
                    'work-item-create-metadata',
                    project_id_or_key.casefold(),
                    work_item_type_id,
                ),
                lambda: self.get_work_item_create_metadata(
                    project_id_or_key,
                    work_item_type_id,
                    _coalesced=True,
                ),
            )

        try:
            response = await self.client.get_work_item_create_meta(
                project_id_or_key, work_item_type_id
            )
            return APIControllerResponse(result=response)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to get the metadata to create work items',
                extra={
                    'work_item_type_id': work_item_type_id,
                    'project_id_or_key': project_id_or_key,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

    async def create_work_item(
        self,
        data: dict,
        available_fields: Iterable[str] | None = None,
        **dynamic_fields,
    ) -> APIControllerResponse:
        """Creates a work item.

        Args:
            data: the data that includes the fields and values to create the work item.

        Returns:
            An instance of `APIControllerResponse` with an instance of `JiraBaseIssue` as the result. This includes the
            item id and key. If an error occurs then  `APIControllerResponse.success == False` and
            `APIControllerResponse.error` indicates the error.
        """
        fields: dict[str, Any] = {}

        project_key = data.get('project_key')
        work_item_type_id = data.get('work_item_type_id')
        resolved_available_fields: set[str] = set()
        if available_fields is not None:
            resolved_available_fields = {str(field) for field in available_fields}

        if not resolved_available_fields and project_key and work_item_type_id:
            metadata_response = await self.get_work_item_create_metadata(
                project_key, work_item_type_id
            )
            if metadata_response.success and metadata_response.result:
                metadata_fields = metadata_response.result.get('fields', [])
                resolved_available_fields = {
                    field.get('key') for field in metadata_fields if field.get('key')
                }

        if assignee_account_id := data.get('assignee_account_id'):
            fields['assignee'] = {'id': assignee_account_id}

        if reporter_account_id := data.get('reporter_account_id'):
            if not resolved_available_fields or 'reporter' in resolved_available_fields:
                fields['reporter'] = {'id': reporter_account_id}

        if work_item_type_id := data.get('work_item_type_id'):
            fields['issuetype'] = {'id': work_item_type_id}

        if parent_key := data.get('parent_key'):
            fields['parent'] = {'key': parent_key}

        if project_key := data.get('project_key'):
            fields['project'] = {'key': project_key}

        if due_date := data.get('duedate'):
            fields['duedate'] = due_date

        if summary := data.get('summary'):
            fields['summary'] = summary

        if priority_id := data.get('priority'):
            fields['priority'] = {'id': priority_id}

        description = data.get('description')
        if isinstance(description, str) and description.strip():
            from gojeera.utils.markdown.adf_helpers import text_to_adf

            fields['description'] = text_to_adf(description)

        if not fields:
            return APIControllerResponse(
                success=False,
                error='The work item was not created because there are no details to create it.',
            )

        for field_key, field_value in dynamic_fields.items():
            if field_key == 'components':
                if isinstance(field_value, list):
                    if field_value and isinstance(field_value[0], str):
                        fields['components'] = [{'id': comp_id} for comp_id in field_value]
                    else:
                        fields['components'] = field_value
                else:
                    fields['components'] = [{'id': field_value}]
            else:
                fields[field_key] = field_value

        try:
            result: dict = await self.client.create_work_item(fields)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)

            error_message = exception_details.get('message', str(e))

            if 'cannot be set' in str(e).lower() or (
                get_nested(exception_details, 'extra', 'errors')
                and any(
                    'cannot be set' in str(err).lower()
                    for err in get_nested(exception_details, 'extra', 'errors', default={}).values()
                )
            ):
                error_message = (
                    f'{error_message}. Note: Some fields may not be available based on your '
                    'project configuration. Check your project screens and field configurations.'
                )

            self.logger.error(
                'An error occurred while trying to create an item',
                extra={
                    'error_message': str(e),
                    'assignee_account_id': data.get('assignee_account_id'),
                    'work_item_type_id': data.get('work_item_type_id'),
                    'parent_key': data.get('parent_key'),
                    'project_key': data.get('project_key'),
                    'duedate': data.get('duedate'),
                    'summary': data.get('summary'),
                    'priority': data.get('priority'),
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=error_message)
        return APIControllerResponse(
            result=JiraBaseWorkItem(id=str(result.get('id', '')), key=str(result.get('key', '')))
        )

    def add_attachment(self, work_item_key_or_id: str, filename: str) -> APIControllerResponse:
        """Adds a file attachment to a work item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            filename: the name of the file to attach.

        Returns:
            An instance of `APIControllerResponse` with the details of the attachment in the `result key; `success=False`
            and the detail of the error if the file can not be attached.
        """
        if not filename:
            return APIControllerResponse(
                success=False, error='Missing required filename parameter.'
            )

        file_path = Path(filename)
        if not file_path.exists():
            self.logger.error(
                'Add attachment: the file provided does not exist', extra={'file_path': file_path}
            )
            return APIControllerResponse(success=False, error='The file provided does not exist.')

        if not file_path.is_file():
            self.logger.error(
                'Add attachment: the resource is not a file', extra={'file_path': file_path}
            )
            return APIControllerResponse(success=False, error='The path provided is not a file.')

        if (stats := file_path.stat()) and stats.st_size > ATTACHMENT_MAXIMUM_FILE_SIZE_IN_BYTES:
            self.logger.error(
                'Add attachment: file size exceeds the maximum allowed.',
                extra={
                    'file_path': file_path,
                    'size': stats.st_size,
                    'allowed': ATTACHMENT_MAXIMUM_FILE_SIZE_IN_BYTES,
                },
            )
            return APIControllerResponse(
                success=False, error='The file provided is larger than the maximum allowed size.'
            )

        _, name = os.path.split(filename)
        mime_type, _ = mimetypes.guess_type(filename)
        try:
            response: list[dict] = self.client.add_attachment_to_work_item(
                work_item_key_or_id, filename, name, mime_type
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to attach files',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'attachment_filename': filename,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        else:
            creator = WorkItemFactory.build_jira_user(response[0].get('author'))
            attachment = Attachment(
                id=str(response[0].get('id', '')),
                filename=str(response[0].get('filename', '')),
                size=int(response[0].get('size', 0)),
                mime_type=str(response[0].get('mimeType', '')),
                created=isoparse(response[0].get('created'))
                if response[0].get('created')
                else None,
                author=creator,
            )
        return APIControllerResponse(result=attachment)

    async def delete_attachment(self, attachment_id: str) -> APIControllerResponse:
        """Deletes an attachment.

        Args:
            attachment_id: the id of the attachment to delete.

        Returns:
            An instance of `APIControllerResponse` with the result of the operation.
        """
        try:
            await self.client.delete_attachment(attachment_id)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to delete attachment',
                extra={
                    'attachment_id': attachment_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse()

    async def get_attachment_content(self, attachment_id: str) -> APIControllerResponse:
        """Downloads the content of an attachment.

        Args:
            attachment_id: the ID of the attachment

        Returns:
            An instance of `APIControllerResponse` with the bytes representation of the attached file or, an error if
            the file can not be downloaded.
        """
        try:
            content: bytes = await self.client.get_attachment_content(attachment_id)
            return APIControllerResponse(result=content)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'An error occurred while trying to get the contents of an attachment',
                extra={
                    'error_message': str(e),
                    'attachment_id': attachment_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

    async def get_work_item_worklog(
        self,
        work_item_key_or_id: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> APIControllerResponse:
        """Retrieves the work log of a work item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the `JiraWorklog` entries;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            response: dict = await self.client.get_work_item_work_log(
                work_item_key_or_id, offset, limit
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to to retrieve the worklog', extra=exception_details.get('extra')
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        logs = [self._build_worklog(work_log) for work_log in response.get('worklogs', [])]

        return APIControllerResponse(
            result=PaginatedJiraWorklog(
                logs=logs,
                start_at=int(response.get('startAt', 0)),
                max_results=int(response.get('maxResults', 0)),
                total=int(response.get('total', 0)),
            )
        )

    async def add_work_item_worklog(
        self,
        work_item_key_or_id: str,
        started: datetime,
        time_spent: str,
        time_remaining: str | None = None,
        comment: str | None = None,
        current_remaining_estimate: str | None = None,
    ) -> APIControllerResponse:
        """Adds a worklog to an item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            current_remaining_estimate: the work item's current remaining time estimate, as days (#d), hours
            (#h), or minutes (#m or #). For example, 2d.
            started: the datetime on which the worklog effort was started. Required when creating a worklog. Optional
            when updating a worklog.
            time_spent: the time spent working on the work item as days (#d), hours (#h), or minutes (#m or #). E.g. `2d 1h`
            time_remaining: the value to set as the work item's remaining time estimate, as days (#d), hours
            (#h), or minutes (#m or #). For example, 2d.
            comment: a comment about the worklog.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the `JiraWorklog` entries;
            `APIControllerResponse(success=False)` if there is an error.
        """

        return await self._execute_result_api_operation(
            self.client.add_work_item_work_log(**self._worklog_request_kwargs(locals())),
            result_builder=self._build_worklog,
            error_message='Unable to add worklog',
            extra=self._worklog_log_context(
                time_spent=time_spent,
                time_remaining=time_remaining,
                current_remaining_estimate=current_remaining_estimate,
                started=started,
            ),
        )

    async def update_worklog(
        self,
        work_item_key_or_id: str,
        worklog_id: str,
        started: datetime | None = None,
        time_spent: str | None = None,
        time_remaining: str | None = None,
        comment: str | None = None,
        current_remaining_estimate: str | None = None,
    ) -> APIControllerResponse:
        """Updates a worklog for an work item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            worklog_id: the ID of the worklog to update.
            started: the datetime on which the worklog effort was started. Optional when updating a worklog.
            time_spent: the time spent working on the work item as days (#d), hours (#h), or minutes (#m or #). E.g. `2d 1h`
            time_remaining: the value to set as the work item's remaining time estimate, as days (#d), hours
            (#h), or minutes (#m or #). For example, 2d.
            comment: a comment about the worklog.
            current_remaining_estimate: the work item's current remaining time estimate, as days (#d), hours
            (#h), or minutes (#m or #). For example, 2d.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the updated `JiraWorklog` entry;
            `APIControllerResponse(success=False)` if there is an error.
        """

        return await self._execute_result_api_operation(
            self.client.update_work_log(
                worklog_id=worklog_id,
                **self._worklog_request_kwargs(locals()),
            ),
            result_builder=self._build_worklog,
            error_message='Unable to update worklog',
            extra=self._worklog_log_context(
                time_spent=time_spent,
                time_remaining=time_remaining,
                current_remaining_estimate=current_remaining_estimate,
                started=started,
                worklog_id=worklog_id,
            ),
        )

    async def remove_worklog(
        self, work_item_id_or_key: str, worklog_id: str
    ) -> APIControllerResponse:
        """Deletes a worklog from an work item.

        Args:
            work_item_id_or_key: the ID or key of the work item.
            worklog_id: the ID of the worklog.

        Returns:
            `APIControllerResponse(success=True)` if the operation was successful;
            `APIControllerResponse(success=False)` if there is an error.
        """
        return await self._execute_void_api_operation(
            self.client.delete_work_log(
                work_item_id_or_key=work_item_id_or_key,
                worklog_id=worklog_id,
            ),
            error_message='Unable to delete worklog',
            extra={'worklog_id': worklog_id},
        )

    async def get_fields(
        self,
        field_name: str | None = None,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Retrieves system and custom work item fields.

        Returns:
            `APIControllerResponse(success=True, result=fields)` if the operation was successful;
            `APIControllerResponse(success=False)` if there is an error.
        """
        if not _coalesced:
            response = await self._cached_or_refresh(
                ('fields',),
                lambda allow_stale: self.cache.get_fields(allow_stale=allow_stale),
                lambda: self.get_fields(_coalesced=True),
            )
            if field_name and isinstance(response.result, list):
                response.result = [
                    field
                    for field in response.result
                    if str(field.name).lower() == field_name.lower()
                ]
            return response

        async def get_paginated_fields() -> list[dict]:
            try:
                return await self.client.get_all_fields_paginated(max_results=100)
            except Exception:
                return []

        try:
            response, paginated_fields = await asyncio.gather(
                self.client.get_fields(),
                get_paginated_fields(),
            )
        except Exception as e:
            exception_details = self._extract_exception_details(e)
            self.logger.error(
                'Unable to fetch fields',
                extra=self._build_log_extra(exception_details=exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.message)

        descriptions_by_id: dict[str, str] = {}
        for field in paginated_fields:
            field_id = field.get('id')
            description = field.get('description')
            if field_id and description:
                descriptions_by_id[str(field_id)] = str(description)

        fields: list[JiraField] = []
        for field in response:
            field_id = field.get('id', '')
            fields.append(
                JiraField(
                    id=field_id,
                    key=field.get('key', ''),
                    name=str(field.get('name', '')),
                    description=descriptions_by_id.get(str(field_id)),
                    schema=field.get('schema', {}),
                )
            )
        await run_cache_io(lambda: self.cache.set_fields(fields))
        return APIControllerResponse(result=fields)

    async def get_label_suggestions(self, query: str = '') -> APIControllerResponse:
        """Get label suggestions from Jira.

        Args:
            query: Optional query string to filter label suggestions.

        Returns:
            An instance of `APIControllerResponse` with a list of label suggestions and `success = True`.
            If an error occurs then `success = False` and the error message in the `error` key.
        """
        try:
            response: Any | None = await self.client.get_label_suggestions(query=query)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to get label suggestions',
                extra={
                    'query': query,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        if not response or not isinstance(response, dict):
            return APIControllerResponse(
                success=False, error='Invalid response from label suggestions API'
            )

        suggestions = response.get('suggestions', [])

        return APIControllerResponse(result=suggestions)

    async def get_sprints_for_project(
        self,
        project_key: str,
        *,
        _coalesced: bool = False,
    ) -> APIControllerResponse:
        """Get active and future sprints for a project with caching.

        Args:
            project_key: The project key

        Returns:
            An instance of `APIControllerResponse` with a list of JiraSprint models and `success = True`.
            If an error occurs then `success = False` and the error message in the `error` key.
        """
        if not _coalesced:
            return await self._cached_or_refresh(
                ('sprints', project_key.casefold()),
                lambda allow_stale: self.cache.get_sprints_for_project(
                    project_key,
                    allow_stale=allow_stale,
                ),
                lambda: self.get_sprints_for_project(project_key, _coalesced=True),
            )

        try:
            sprints_data = await self.client.get_sprints_for_project(
                project_key, states=['active', 'future']
            )

            sprints: list[JiraSprint] = []
            for sprint_data in sprints_data:
                try:
                    sprint_id = sprint_data.get('id')
                    sprint_name = sprint_data.get('name')
                    sprint_state = sprint_data.get('state')
                    sprint_board_id = sprint_data.get('boardId')

                    if not sprint_id or not sprint_name or not sprint_state:
                        self.logger.warning(
                            f'Skipping sprint with missing required fields: {sprint_data}'
                        )
                        continue

                    sprint = JiraSprint(
                        id=sprint_id,
                        name=sprint_name,
                        state=sprint_state,
                        boardId=sprint_board_id if sprint_board_id is not None else 0,
                        goal=sprint_data.get('goal'),
                        startDate=sprint_data.get('startDate'),
                        endDate=sprint_data.get('endDate'),
                        completeDate=sprint_data.get('completeDate'),
                    )
                    sprints.append(sprint)
                except Exception as e:
                    self.logger.warning(f'Failed to parse sprint: {e}')
                    continue

            await run_cache_io(
                lambda: self.cache.set_sprints_for_project(
                    project_key,
                    sprints,
                    ttl_seconds=None if sprints else 120,
                )
            )

            return APIControllerResponse(result=sprints)

        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                f'Failed to fetch sprints for project {project_key}: {exception_details.get("message")}',
                extra=self._build_log_extra({'project_key': project_key}, exception_details),
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
