from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime
from io import BufferedReader, BytesIO
import json
import logging
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, Any, Awaitable, BinaryIO, Callable, TypeVar, cast

# https://darren.codes/posts/python-startup-time/
sys.modules['httpx._main'] = cast(Any, None)
import httpx  # noqa: E402
import magic  # noqa: E402

from gojeera.internal.jira.client import (  # noqa: E402
    AsyncHTTPClient,
    AsyncJiraClient,
    GraphQLClient,
    JiraClient,
)
from gojeera.internal.models.exceptions import (  # noqa: E402
    FileUploadException,
    ServiceInvalidRequestException,
    ServiceInvalidResponseException,
)
from gojeera.internal.store.cache import get_cache, run_cache_io  # noqa: E402
from gojeera.utils.jira.graphql import (  # noqa: E402
    GRAPHQL_PROJECT_BY_KEY_QUERY,
    GRAPHQL_PROJECT_PULL_REQUEST_MAX_PAGES,
    GRAPHQL_PROJECT_PULL_REQUEST_PAGE_SIZE,
    GRAPHQL_PROJECT_PULL_REQUESTS_OAUTH_ERROR,
    GRAPHQL_PROJECT_REPOSITORIES_OAUTH_ERROR,
    GRAPHQL_PROJECT_REPOSITORIES_QUERY,
    GRAPHQL_PROJECT_REPOSITORY_PAGE_SIZE,
    GRAPHQL_PROJECT_SPACE_PULL_REQUESTS_QUERY,
    GRAPHQL_WORK_ITEM_PULL_REQUESTS_OAUTH_ERROR,
    GRAPHQL_WORK_ITEM_PULL_REQUESTS_QUERY,
)
from gojeera.utils.jira.jql import build_work_item_search_jql  # noqa: E402
from gojeera.utils.system.logging_utils import build_log_extra  # noqa: E402

if TYPE_CHECKING:
    from gojeera.internal.store.config import ApplicationConfiguration, JiraAuthContext

ClientT = TypeVar('ClientT', AsyncJiraClient, JiraClient, AsyncHTTPClient, GraphQLClient)
WORK_ITEM_SEARCH_DEFAULT_MAX_RESULTS = 50
WORK_ITEM_KEY_SEARCH_PATTERN = re.compile(r'(?<![A-Z0-9])([A-Z][A-Z0-9]+-\d+)(?![A-Z0-9])')


class JiraAPI:
    """Implements methods to connect to the Jira REST API endpoints."""

    REST_API_PATH_PREFIX = '/rest/api/3/'
    AGILE_API_PATH_PREFIX = '/rest/agile/1.0/'
    SERVICE_DESK_API_PATH_PREFIX = '/rest/servicedeskapi/'

    def __init__(
        self,
        auth: JiraAuthContext,
        configuration: ApplicationConfiguration,
        oauth2_token_refresher: Callable[[bool], str | None] | None = None,
    ):
        rest_api_path_prefix = auth.rest_api_path_prefix or self.REST_API_PATH_PREFIX
        agile_api_path_prefix = auth.agile_api_path_prefix or self.AGILE_API_PATH_PREFIX
        rest_api_base_url = f'{auth.api_base_url.rstrip("/")}{rest_api_path_prefix}'
        self._client = self._build_http_client(
            AsyncJiraClient,
            auth=auth,
            configuration=configuration,
            base_url=rest_api_base_url,
            oauth2_token_refresher=oauth2_token_refresher,
        )
        self._sync_client = self._build_http_client(
            JiraClient,
            auth=auth,
            configuration=configuration,
            base_url=rest_api_base_url,
            oauth2_token_refresher=oauth2_token_refresher,
        )
        self._async_http_client = self._build_http_client(
            AsyncHTTPClient,
            auth=auth,
            configuration=configuration,
            base_url=rest_api_base_url,
            oauth2_token_refresher=oauth2_token_refresher,
        )
        self._agile_client = self._build_http_client(
            AsyncJiraClient,
            auth=auth,
            configuration=configuration,
            base_url=f'{auth.api_base_url.rstrip("/")}{agile_api_path_prefix}',
            oauth2_token_refresher=oauth2_token_refresher,
        )
        service_desk_api_path_prefix = rest_api_path_prefix.replace(
            self.REST_API_PATH_PREFIX,
            self.SERVICE_DESK_API_PATH_PREFIX,
        )
        self._service_desk_client = self._build_http_client(
            AsyncJiraClient,
            auth=auth,
            configuration=configuration,
            base_url=f'{auth.api_base_url.rstrip("/")}{service_desk_api_path_prefix}',
            oauth2_token_refresher=oauth2_token_refresher,
        )
        self._graphql_client = self._build_http_client(
            GraphQLClient,
            auth=auth,
            configuration=configuration,
            base_url=self._graphql_base_url(auth),
            oauth2_token_refresher=oauth2_token_refresher,
        )
        self._base_url = auth.api_base_url
        self._auth = auth
        self.logger = logging.getLogger('gojeera')
        self.cache = get_cache()
        self.cache.set_profile(self._cache_profile_key())

    def _cache_profile_key(self) -> str:
        return f'{self._auth.cloud_id}:{self._auth.account_id}'

    @staticmethod
    def _graphql_base_url(auth: JiraAuthContext) -> str:
        if auth.auth_type == 'oauth2':
            return 'https://api.atlassian.com/graphql'
        instance_base_url = auth.instance_base_url or auth.api_base_url
        return f'{instance_base_url.rstrip("/")}/gateway/api/graphql'

    @staticmethod
    def _build_http_client(
        client_type: type[ClientT],
        *,
        auth: JiraAuthContext,
        configuration: ApplicationConfiguration,
        base_url: str,
        oauth2_token_refresher: Callable[[bool], str | None] | None,
    ) -> ClientT:
        return client_type(
            base_url=base_url,
            instance_base_url=auth.instance_base_url,
            api_email=auth.api_email,
            api_token=auth.api_token.strip() if auth.api_token is not None else None,
            configuration=configuration,
            bearer_token=auth.bearer_token,
            token_refresh_callback=oauth2_token_refresher,
        )

    def set_bearer_token(self, bearer_token: str | None) -> None:
        self._auth = replace(self._auth, bearer_token=bearer_token)
        self._client.set_bearer_token(bearer_token)
        self._sync_client.set_bearer_token(bearer_token)
        self._async_http_client.set_bearer_token(bearer_token)
        self._agile_client.set_bearer_token(bearer_token)
        self._service_desk_client.set_bearer_token(bearer_token)
        self._graphql_client.set_bearer_token(bearer_token)

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def auth(self) -> 'JiraAuthContext':
        return self._auth

    @property
    def client(self) -> AsyncJiraClient:
        return self._client

    @property
    def async_http_client(self) -> AsyncHTTPClient:
        return self._async_http_client

    @property
    def sync_client(self) -> JiraClient:
        return self._sync_client

    @property
    def agile_client(self) -> AsyncJiraClient:
        return self._agile_client

    @property
    def graphql_client(self) -> GraphQLClient:
        return self._graphql_client

    def _graphql_site_context_ari(self) -> str:
        return f'ari:cloud:platform::site/{self._auth.cloud_id}'

    @staticmethod
    def _add_pagination_params(
        params: dict[str, Any],
        offset: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
        return params

    @staticmethod
    def _build_worklog_adjust_estimate_params(time_remaining: str | None) -> dict[str, str]:
        if time_remaining:
            return {'newEstimate': time_remaining, 'adjustEstimate': 'new'}
        return {'adjustEstimate': 'auto'}

    @staticmethod
    def _build_user_search_params(
        offset: int | None = None,
        limit: int | None = None,
        *,
        username: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = JiraAPI._add_pagination_params({}, offset, limit)
        if username is not None:
            params['username'] = username
        if query is not None:
            params['query'] = query
        return params

    async def _request_work_item_remote_link(
        self,
        method: Callable,
        work_item_id_or_key: str,
        *,
        link_id: str | None = None,
        url: str | None = None,
        title: str | None = None,
    ) -> None:
        endpoint = f'issue/{work_item_id_or_key}/remotelink'
        if link_id is not None:
            endpoint = f'{endpoint}/{link_id}'

        data: str | None = None
        if url is not None and title is not None:
            data = json.dumps(self._build_work_item_remote_link_payload(url, title))
        request_kwargs: dict[str, Any] = {}
        if data is not None:
            request_kwargs['data'] = data

        await self._client.make_request(method=method, url=endpoint, **request_kwargs)

    async def _fetch_paginated_agile_values(
        self,
        url: str,
        params: dict[str, Any],
        context_name: str,
    ) -> list[dict]:
        return await self._fetch_paginated_values(
            request_page=lambda page_params: cast(
                Awaitable[dict[str, Any] | None],
                self._agile_client.make_request(
                    method=httpx.AsyncClient.get,
                    url=url,
                    params=page_params,
                ),
            ),
            params=params,
            context_name=context_name,
        )

    async def search_projects(
        self,
        offset: int | None = None,
        limit: int | None = None,
        query: str | None = None,
        keys: list[str] | None = None,
        project_type_key: str | None = None,
    ) -> dict:
        """Retrieves a paginated list of projects visible to the user (making the request).

        Args:
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page. Must be less than or equal to 100.
            query: filter the results using a literal string. Projects with a matching key or name are returned
            (case-insensitive).
            keys: the project keys to filter the results by.
            project_type_key: filter the results by project type.

        Returns:
            A dictionary with the details of the projects.
        """
        params: dict[str, Any] = self._add_pagination_params({}, offset, limit)
        if query is not None:
            params['query'] = query
        if keys:
            params['keys'] = ','.join(keys[:50])
        if project_type_key is not None:
            params['typeKey'] = project_type_key

        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get, url='project/search', params=params
            ),
        )

    async def get_project_statuses(self, project_key: str) -> list[dict]:
        """Retrieves the valid statuses for a project.

        The statuses are grouped by work item type, as each project has a set of valid work item types and each work item type has
        a set of valid statuses.

        Args:
            project_key: the (case-sensitive) project ID or project key.

        Returns:
            A list of dictionaries.
        """
        return cast(
            list[dict],
            await self._client.make_request(
                method=httpx.AsyncClient.get, url=f'project/{project_key}/statuses'
            ),
        )

    async def get_work_items_types_for_user(self) -> list[dict]:
        """Retrieves all the work item types.

        Returns:
            A list of dictionaries with the details of the types of work items.
        """
        return cast(
            list[dict],
            await self._client.make_request(method=httpx.AsyncClient.get, url='issuetype'),
        )

    async def status(self) -> list[dict]:
        return cast(
            list[dict], await self._client.make_request(method=httpx.AsyncClient.get, url='status')
        )

    async def get_project(self, key: str) -> dict:
        """Retrieves the details of a project.

        Args:
            key: the project ID or project key (case-sensitive).

        Returns:
            A dictionary with the details of the project.
        """
        return cast(
            dict,
            await self._client.make_request(method=httpx.AsyncClient.get, url=f'project/{key}'),
        )

    async def get_project_features(self, project_id_or_key: str) -> dict[str, Any]:
        """Retrieves Jira Software feature flags for a project."""
        return cast(
            dict[str, Any],
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'project/{project_id_or_key}/features',
            ),
        )

    async def _get_graphql_project_ari(self, project_key: str) -> str:
        cached_project_ari = await run_cache_io(
            lambda: self.cache.get_project_graphql_ari(project_key)
        )
        if cached_project_ari:
            return cached_project_ari

        project_response = await self._graphql_client.execute(
            GRAPHQL_PROJECT_BY_KEY_QUERY,
            variables={'cloudId': self._auth.cloud_id, 'projectKey': project_key},
        )
        project = project_response.get('data', {}).get('jira_projectByIdOrKey')
        if isinstance(project, dict) and project.get('id'):
            project_ari = str(project['id'])
            await run_cache_io(
                lambda: self.cache.set_project_graphql_ari(
                    project_key=str(project.get('key') or project_key),
                    graphql_ari=project_ari,
                )
            )
            return project_ari
        raise ServiceInvalidResponseException(
            f'Project {project_key} was not found in GraphQL response',
            context={'project_key': project_key},
            remote_payload=project_response,
        )

    @staticmethod
    def _next_graphql_page_cursor(
        connection: dict[str, Any],
        *,
        context: dict[str, Any],
        remote_payload: dict[str, Any],
        missing_cursor_message: str,
    ) -> str | None:
        page_info = connection.get('pageInfo') or {}
        if not page_info.get('hasNextPage'):
            return None
        after = page_info.get('endCursor')
        if after:
            return str(after)
        raise ServiceInvalidResponseException(
            missing_cursor_message,
            context=context,
            remote_payload=remote_payload,
        )

    @staticmethod
    def _extend_graphql_edge_results(
        results: list[dict[str, Any]],
        connection: dict[str, Any],
        build_edge_data: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        for edge in connection.get('edges') or []:
            if isinstance(edge, dict):
                results.append(build_edge_data(edge))

    async def get_project_repositories(self, project_key: str) -> list[dict[str, Any]]:
        if self._auth.auth_type == 'oauth2':
            raise ServiceInvalidRequestException(
                GRAPHQL_PROJECT_REPOSITORIES_OAUTH_ERROR,
                context={'project_key': project_key, 'auth_type': self._auth.auth_type},
            )

        project_ari = await self._get_graphql_project_ari(project_key)
        repositories: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            repositories_response = await self._graphql_client.execute(
                GRAPHQL_PROJECT_REPOSITORIES_QUERY,
                variables={
                    'projectAri': project_ari,
                    'first': GRAPHQL_PROJECT_REPOSITORY_PAGE_SIZE,
                    'after': after,
                },
                headers={'X-Query-Context': self._graphql_site_context_ari()},
            )
            connection = (
                repositories_response.get('data', {})
                .get('graphStore', {})
                .get('projectAssociatedRepo')
            )
            if not isinstance(connection, dict):
                raise ServiceInvalidResponseException(
                    'Project repositories were not found in GraphQL response',
                    context={'project_key': project_key},
                    remote_payload=repositories_response,
                )

            self._extend_graphql_edge_results(
                repositories,
                connection,
                self._build_project_repository_data,
            )

            after = self._next_graphql_page_cursor(
                connection,
                context={'project_key': project_key},
                remote_payload=repositories_response,
                missing_cursor_message='GraphQL repositories page is missing an end cursor',
            )
            if after is None:
                return repositories

    @staticmethod
    def _build_project_repository_data(edge: dict[str, Any]) -> dict[str, Any]:
        node = edge.get('node') or {}
        provider = node.get('provider') or {}
        return {
            'id': str(node.get('id', '')),
            'name': str(node.get('name') or node.get('displayName') or ''),
            'url': node.get('devOpsUrl') or node.get('externalUrl'),
            'provider_id': node.get('providerId') or provider.get('providerId'),
            'provider_name': provider.get('name'),
            'external_id': node.get('externalId')
            or node.get('repositoryId')
            or node.get('thirdPartyId'),
            'relationship_id': edge.get('id'),
            'repository_type': node.get('__typename'),
        }

    async def get_project_space_pull_requests(self, project_key: str) -> list[dict[str, Any]]:
        if self._auth.auth_type == 'oauth2':
            raise ServiceInvalidRequestException(
                GRAPHQL_PROJECT_PULL_REQUESTS_OAUTH_ERROR,
                context={'project_key': project_key, 'auth_type': self._auth.auth_type},
            )

        project_ari = await self._get_graphql_project_ari(project_key)
        pull_requests: list[dict[str, Any]] = []
        after: str | None = None
        page_count = 0
        while page_count < GRAPHQL_PROJECT_PULL_REQUEST_MAX_PAGES:
            pull_requests_response = await self._graphql_client.execute(
                GRAPHQL_PROJECT_SPACE_PULL_REQUESTS_QUERY,
                variables={
                    'projectAri': project_ari,
                    'first': GRAPHQL_PROJECT_PULL_REQUEST_PAGE_SIZE,
                    'after': after,
                },
                headers={'X-Query-Context': self._graphql_site_context_ari()},
            )
            connection = (
                pull_requests_response.get('data', {})
                .get('graphStoreV2', {})
                .get('jiraSpaceLinksExternalPullRequest')
            )
            if not isinstance(connection, dict):
                raise ServiceInvalidResponseException(
                    'Project pull requests were not found in GraphQL response',
                    context={'project_key': project_key},
                    remote_payload=pull_requests_response,
                )

            self._extend_graphql_edge_results(
                pull_requests,
                connection,
                self._build_project_space_pull_request_data,
            )

            after = self._next_graphql_page_cursor(
                connection,
                context={'project_key': project_key},
                remote_payload=pull_requests_response,
                missing_cursor_message='GraphQL pull requests page is missing an end cursor',
            )
            if after is None:
                return pull_requests
            page_count += 1
        return pull_requests

    async def get_work_item_pull_requests(self, work_item_id: str) -> list[dict[str, Any]]:
        if self._auth.auth_type == 'oauth2':
            raise ServiceInvalidRequestException(
                GRAPHQL_WORK_ITEM_PULL_REQUESTS_OAUTH_ERROR,
                context={'work_item_id': work_item_id, 'auth_type': self._auth.auth_type},
            )

        issue_ari = f'ari:cloud:jira:{self._auth.cloud_id}:issue/{work_item_id}'
        pull_requests: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            pull_requests_response = await self._graphql_client.execute(
                GRAPHQL_WORK_ITEM_PULL_REQUESTS_QUERY,
                variables={
                    'issueAri': issue_ari,
                    'first': GRAPHQL_PROJECT_PULL_REQUEST_PAGE_SIZE,
                    'after': after,
                },
                headers={'X-Query-Context': self._graphql_site_context_ari()},
            )
            connection = pull_requests_response.get('data', {}).get(
                'graphStoreV2_jiraWorkItemLinksExternalPullRequest'
            )
            if not isinstance(connection, dict):
                raise ServiceInvalidResponseException(
                    'Work item pull requests were not found in GraphQL response',
                    context={'work_item_id': work_item_id},
                    remote_payload=pull_requests_response,
                )

            self._extend_graphql_edge_results(
                pull_requests,
                connection,
                lambda edge: self._build_graphql_pull_request_data(
                    (edge.get('node') or {}) if isinstance(edge, dict) else {},
                    edge,
                    work_item_id=work_item_id,
                    work_item_ari=issue_ari,
                ),
            )

            after = self._next_graphql_page_cursor(
                connection,
                context={'work_item_id': work_item_id},
                remote_payload=pull_requests_response,
                missing_cursor_message='GraphQL work item pull requests page is missing an end cursor',
            )
            if after is None:
                return pull_requests

    @staticmethod
    def _extract_associated_jira_issue(
        pull_request: dict[str, Any],
    ) -> tuple[str, str]:
        associated_with = pull_request.get('associatedWith') or {}
        for edge in associated_with.get('edges') or []:
            if not isinstance(edge, dict):
                continue

            node = edge.get('node') or {}
            entity = node.get('entity') or {}
            if entity.get('__typename') == 'JiraIssue':
                return str(entity.get('key') or ''), str(entity.get('issueId') or '')
        return '', ''

    @staticmethod
    def _build_project_space_pull_request_data(edge: dict[str, Any]) -> dict[str, Any]:
        pull_request = edge.get('node') or {}
        work_item_key, work_item_id = JiraAPI._extract_associated_jira_issue(pull_request)
        pull_request_data = JiraAPI._build_graphql_pull_request_data(
            pull_request,
            edge,
            work_item_id=work_item_id,
            work_item_ari=None,
        )
        if work_item_key:
            pull_request_data['work_item_key'] = work_item_key
        return pull_request_data

    @staticmethod
    def _extract_work_item_key_from_pull_request_text(
        pull_request: dict[str, Any],
    ) -> str:
        source_branch = pull_request.get('sourceBranch') or {}
        destination_branch = pull_request.get('destinationBranch') or {}
        candidates = (
            pull_request.get('title'),
            source_branch.get('name'),
            destination_branch.get('name'),
        )
        for candidate in candidates:
            if not candidate:
                continue
            if match := WORK_ITEM_KEY_SEARCH_PATTERN.search(str(candidate)):
                return match.group(1).upper()
        return ''

    @staticmethod
    def _build_graphql_pull_request_data(
        pull_request: dict[str, Any],
        edge: dict[str, Any],
        *,
        work_item_id: str,
        work_item_ari: Any,
    ) -> dict[str, Any]:
        provider = pull_request.get('provider') or {}
        source_branch = pull_request.get('sourceBranch') or {}
        destination_branch = pull_request.get('destinationBranch') or {}
        author = pull_request.get('author') or {}
        return {
            'id': str(
                pull_request.get('id')
                or pull_request.get('pullRequestInternalId')
                or pull_request.get('pullRequestId')
                or pull_request.get('thirdPartyId')
                or pull_request.get('url')
                or ''
            ),
            'title': str(pull_request.get('title') or ''),
            'work_item_key': JiraAPI._extract_work_item_key_from_pull_request_text(pull_request),
            'work_item_id': work_item_id,
            'work_item_ari': work_item_ari,
            'status': pull_request.get('devOpsStatus')
            or pull_request.get('externalStatus')
            or pull_request.get('status'),
            'url': pull_request.get('url'),
            'author': author.get('name'),
            'repository_id': pull_request.get('devOpsRepositoryId')
            or pull_request.get('externalRepositoryId')
            or pull_request.get('repositoryId')
            or pull_request.get('repositoryInternalId'),
            'repository_name': pull_request.get('repositoryName'),
            'repository_url': pull_request.get('repositoryUrl'),
            'provider_id': pull_request.get('providerId') or provider.get('providerId'),
            'provider_name': pull_request.get('providerName') or provider.get('name'),
            'source_branch': source_branch.get('name'),
            'destination_branch': destination_branch.get('name'),
            'last_updated': pull_request.get('lastUpdated')
            or pull_request.get('lastUpdate')
            or edge.get('lastUpdated'),
        }

    async def get_project_versions(
        self,
        project_id_or_key: str,
        offset: int | None = None,
        limit: int | None = None,
        *,
        order_by: str | None = 'sequence',
        query: str | None = None,
        status: str | None = None,
        expand: str | None = 'issuesstatus',
    ) -> dict:
        """Retrieves a paginated list of project versions.

        Jira's UI calls these releases.
        """
        params: dict[str, Any] = self._add_pagination_params({}, offset, limit)
        if order_by is not None:
            params['orderBy'] = order_by
        if query is not None:
            params['query'] = query
        if status is not None:
            params['status'] = status
        if expand is not None:
            params['expand'] = expand

        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'project/{project_id_or_key}/version',
                params=params,
            ),
        )

    async def user_assignable_search(
        self,
        project_id_or_key: str | None = None,
        work_item_key: str | None = None,
        work_item_id: str | None = None,
        offset: int | None = None,
        limit: int | None = 50,
        query: str | None = None,
    ) -> list[dict]:
        """Retrieves a list of users that can be assigned to a work item.

        Args:
            project_id_or_key: the project ID or project key (case-sensitive). Required, unless `work_item_key` or
            `work_item_id` is specified.
            work_item_key: the key of the work item. Required, unless issueId or project is specified.
            work_item_id: the ID of the work item. Required, unless issueKey or project is specified.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return. Default is `50`.
            query: optional prefix-matching search text for user attributes such as `displayName` and `emailAddress`.

        Returns:
            A list of dictionaries with the details of the users.
        """
        if not any([project_id_or_key, work_item_id, work_item_key]):
            raise ValueError(
                'One of these parameters is required: project_id, work_item_id, work_item_key'
            )

        params: dict[str, Any] = self._add_pagination_params({}, offset, limit)
        if project_id_or_key:
            params['project'] = project_id_or_key
        if query:
            params['query'] = query
        if work_item_key:
            params['issueKey'] = work_item_key
        if work_item_id:
            params['issueId'] = work_item_id

        return cast(
            list[dict],
            await self._client.make_request(
                method=httpx.AsyncClient.get, url='user/assignable/search', params=params
            ),
        )

    async def user_assignable_multi_projects(
        self,
        project_keys: list[str] | None = None,
        query: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Retrieves the users who can be assigned work items in one or more projects.

        Args:
            project_keys: a list of project keys (case-sensitive). This parameter accepts a comma-separated list.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page. Default is `50`.
            query: optional prefix-matching search text for user attributes such as `displayName` and `emailAddress`.

        Returns:
            A list of dictionaries with the details of the users.
        """
        params: dict[str, Any] = self._add_pagination_params({}, offset, limit)
        if project_keys:
            params['projectKeys'] = ','.join(project_keys)
        if query:
            params['query'] = query
        return cast(
            list[dict],
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url='user/assignable/multiProjectSearch',
                params=params,
            ),
        )

    async def get_work_item(
        self,
        work_item_id_or_key: str,
        fields: str | None = None,
        properties: str | None = None,
    ) -> dict:
        """Retrieves the details of a work item by ID or key.

        The work item is identified by its ID or key, however, if the identifier doesn't match a work item, a case-insensitive
        search and check for moved work items is performed. If a matching work item is found its details are returned, a 302
        or other redirect is not returned. The work item key returned in the response is the key of the work item found.

        Args:
            work_item_id_or_key: the ID or case-sensitive key of the work item to retrieve.
            fields: a list of fields to return for the work. This parameter accepts a comma-separated list. Use it
            to retrieve a subset of fields. Allowed values:
                *all Returns all fields.
                *navigable Returns navigable fields.
            Any work item field, prefixed with a minus to exclude.
            properties: a list of work item properties to return for the work item. This parameter accepts a comma-separated
            list. Allowed values:
                *all Returns all work item properties.
                Any work item property key, prefixed with a minus to exclude.

        Returns:
            A dictionary with the detail sof the work item.
        """
        params: dict[str, Any] = {'expand': 'editmeta'}
        if fields is not None:
            params['fields'] = fields
        if properties is not None:
            params['properties'] = properties
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/{work_item_id_or_key}',
                params=params,
            ),
        )

    async def get_work_item_remote_links(
        self, work_item_id_or_key: str, global_id: str | None = None
    ) -> list[dict]:
        """Retrieves the remote work items links for a work item.

        Args:
            work_item_id_or_key: the key or ID of the work item whose remote links we want to retrieve.
            global_id: the global ID of the remote work item link.

        Returns:
            A list of dictionaries.
        """
        params: dict[str, str] = {}
        if global_id:
            params['globalId'] = global_id
        return cast(
            list[dict],
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/{work_item_id_or_key}/remotelink',
                params=params,
            ),
        )

    async def get_work_item_watchers(self, work_item_id_or_key: str) -> dict:
        """Retrieves the watchers for a work item."""
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/{work_item_id_or_key}/watchers',
            ),
        )

    async def add_work_item_watcher(
        self, work_item_id_or_key: str, account_id: str | None = None
    ) -> None:
        """Adds a watcher to a work item.

        Jira accepts a JSON string account ID. An empty string adds the calling user.
        """
        await self._client.make_request(
            method=httpx.AsyncClient.post,
            url=f'issue/{work_item_id_or_key}/watchers',
            data=json.dumps(account_id or ''),
        )

    async def remove_work_item_watcher(self, work_item_id_or_key: str, account_id: str) -> None:
        """Removes a watcher from a work item."""
        await self._client.make_request(
            method=httpx.AsyncClient.delete,
            url=f'issue/{work_item_id_or_key}/watchers',
            params={'accountId': account_id},
        )

    @staticmethod
    def _build_work_item_remote_link_payload(url: str, title: str) -> dict[str, Any]:
        return {
            'object': {
                'title': title,
                'url': url,
            }
        }

    async def create_work_item_remote_link(
        self, work_item_id_or_key: str, url: str, title: str
    ) -> None:
        """Create a remote link for a work item."""
        await self._request_work_item_remote_link(
            httpx.AsyncClient.post, work_item_id_or_key, url=url, title=title
        )

    async def delete_work_item_remote_link(self, work_item_id_or_key: str, link_id: str) -> None:
        """Deletes a web link associated to a work item.

        Args:
            work_item_id_or_key: the ID or case-sensitive key of the work item
            link_id: the IF of the link.

        Returns:
            Nothing.
        """
        await self._request_work_item_remote_link(
            httpx.AsyncClient.delete,
            work_item_id_or_key,
            link_id=link_id,
        )
        return None

    async def update_work_item_remote_link(
        self, work_item_id_or_key: str, link_id: str, url: str, title: str
    ) -> None:
        """Update a remote link for a work item."""
        await self._request_work_item_remote_link(
            httpx.AsyncClient.put,
            work_item_id_or_key,
            link_id=link_id,
            url=url,
            title=title,
        )

    async def search_work_items(
        self,
        project_key: str | None = None,
        created_from: date | None = None,
        created_until: date | None = None,
        updated_from: date | None = None,
        updated_until: date | None = None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        jql_query: str | None = None,
        search_in_active_sprint: bool = False,
        fields: list[str] | None = None,
        next_page_token: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> dict:
        """Searches for work items using JQL. Recent updates might not be immediately visible in the returned search
        results.

        Args:
            project_key: search items that belong to the project with this (case-sensitive) key.
            created_from: search items created from this date forward.
            created_until: search items created until this date.
            updated_from: search items updated from this date forward.
            updated_until: search items updated until this date
            status: search items with this status id.
            assignee: search items assigned to this user (by account id).
            work_item_type: search items with this type id.
            jql_query: a JQL expression to filter items.
            search_in_active_sprint: if `True` only work items that belong to the currently active sprint will be
            retrieved.
            fields: retrieve these fields for every item found.
            next_page_token: an optional token to retrieve the next page of results.
            offset: N/A
            limit: retrieve this max number of results per page.

        Returns:
            A dictionary with the results.
        """
        del offset
        jql: str = build_work_item_search_jql(
            project_key=project_key,
            created_from=created_from,
            created_until=created_until,
            updated_from=updated_from,
            updated_until=updated_until,
            status=status,
            assignee=assignee,
            work_item_type=work_item_type,
            jql_query=jql_query,
            search_in_active_sprint=search_in_active_sprint,
        )
        payload: dict[str, Any] = {
            'jql': jql,
            'maxResults': limit or WORK_ITEM_SEARCH_DEFAULT_MAX_RESULTS,
        }
        if fields:
            payload['fields'] = fields
        if next_page_token:
            payload['nextPageToken'] = next_page_token

        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.post, url='search/jql', data=json.dumps(payload)
            ),
        )

    async def work_items_search_approximate_count(
        self,
        project_key: str | None = None,
        created_from: date | None = None,
        created_until: date | None = None,
        updated_from: date | None = None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        jql_query: str | None = None,
    ) -> dict:
        """Provides an estimated count of the work items that match the JQL. Recent updates might not be immediately visible
        in the returned output. This endpoint requires JQL to be bounded.

        Args:
            project_key: search items that belong to the project with this (case-sensitive) key.
            created_from: search items created from this date forward.
            created_until: search items created until this date.
            updated_from: search items updated from this date forward.
            status: search items with this status id.
            assignee: search items assigned to this user (by account id).
            work_item_type: search items with this type id.
            jql_query: a JQL expression to filter items.

        Returns:
            A dictionary with the estimated number of items that match the search criteria.
        """
        jql: str = build_work_item_search_jql(
            project_key=project_key,
            created_from=created_from,
            created_until=created_until,
            updated_from=updated_from,
            updated_until=None,
            status=status,
            assignee=assignee,
            work_item_type=work_item_type,
            jql_query=jql_query,
        )

        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.post,
                url='search/approximate-count',
                data=json.dumps({'jql': jql}),
            ),
        )

    async def parse_jql_query(self, jql_query: str) -> dict:
        """Parses and validates a JQL query.

        Args:
            jql_query: the JQL query string to parse and validate.

        Returns:
            A dictionary with the parsing result including any errors.
        """
        payload: dict[str, Any] = {'queries': [jql_query]}
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.post,
                url='jql/parse',
                data=json.dumps(payload),
            ),
        )

    async def global_settings(self) -> dict:
        """Retrieves the global settings in Jira.

        These settings determine whether optional features (for example, subtasks, time tracking, and others) are
        enabled. If time tracking is enabled, this operation also returns the time tracking configuration.

        Returns:
            A dictionary with the settings.
        """
        return cast(
            dict, await self._client.make_request(method=httpx.AsyncClient.get, url='configuration')
        )

    async def server_info(self) -> dict:
        """Retrieves information of the Jira server.

        Returns:
            A dictionary with the details.
        """
        return cast(
            dict, await self._client.make_request(method=httpx.AsyncClient.get, url='serverInfo')
        )

    async def myself(self) -> dict:
        """Retrieves information of the Jira user connecting to the Jira server.

        Returns:
            A dictionary with the details.
        """
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url='myself',
                params={'expand': 'groups,applicationRoles'},
            ),
        )

    async def fetch_user_filters(
        self,
        account_id: str | None = None,
        starred_only: bool = False,
        max_results: int = 50,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch JQL filters from Jira.

        Args:
            account_id: User account ID for fetching owned filters.
            starred_only: If True, only return filters that are starred (marked as favorite).
            max_results: Maximum number of filters to return (default 50).
            include_shared: If True, fetch both personal and shared filters. If False, only personal filters.

        Returns:
            A list of dicts with 'label' (filter name), 'expression' (JQL), and 'source' ('remote').
        """
        filters = []
        seen_ids = set()

        if starred_only:
            self.logger.info('Fetching favourite filters')
            favourite_filters = await self._fetch_favourite_filters()
            filters.extend(self._process_filters(favourite_filters, starred_only, seen_ids))
        elif account_id:
            self.logger.info(
                'Fetching personal filters',
                extra=build_log_extra({'account_id': account_id, 'shared': False}),
            )
            personal_params: dict[str, Any] = {
                'maxResults': max_results,
                'expand': 'jql,favourite',
                'accountId': account_id,
            }

            personal_filters = await self._fetch_paginated_filter_search_results(
                personal_params,
                log_label='personal',
            )
            filters.extend(self._process_filters(personal_filters, starred_only, seen_ids))

        if include_shared:
            self.logger.info(
                'Fetching shared filters',
                extra=build_log_extra({'shared': True}),
            )
            shared_params: dict[str, Any] = {
                'maxResults': max_results,
                'expand': 'jql,favourite',
            }

            shared_filters = await self._fetch_paginated_filter_search_results(
                shared_params,
                log_label='shared',
            )
            filters.extend(self._process_filters(shared_filters, starred_only, seen_ids))

        self.logger.info('Returning filters', extra=build_log_extra({'count': len(filters)}))
        return filters

    async def _fetch_favourite_filters(self) -> list[dict]:
        try:
            response = await self._client.make_request(
                method=httpx.AsyncClient.get,
                url='filter/favourite',
                params={'expand': 'jql,favourite'},
            )
        except Exception:
            self.logger.warning('Failed to fetch favourite filters', exc_info=True)
            return []

        if not response:
            return []
        if isinstance(response, list):
            return cast(list[dict], response)
        if isinstance(response, dict):
            return cast(list[dict], response.get('values', []))
        return []

    async def _fetch_paginated_filter_search_results(
        self,
        params: dict[str, Any],
        *,
        log_label: str,
    ) -> list[dict]:
        return await self._fetch_paginated_values(
            request_page=lambda page_params: cast(
                Awaitable[dict[str, Any] | None],
                self._client.make_request(
                    method=httpx.AsyncClient.get,
                    url='filter/search',
                    params=page_params,
                ),
            ),
            params=params,
            context_name=f'{log_label} filters',
        )

    async def _fetch_paginated_values(
        self,
        request_page: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]],
        params: dict[str, Any],
        context_name: str,
        *,
        max_results: int = 50,
        values_key: str = 'values',
        on_page: Callable[[dict[str, Any], list[dict]], None] | None = None,
        on_error: Callable[[Exception], list[dict] | None] | None = None,
    ) -> list[dict]:
        """Fetch all Jira pages for endpoints using `startAt` / `maxResults` pagination."""
        values: list[dict] = []
        start_at = int(params.get('startAt', 0) or 0)
        effective_max_results = int(params.get('maxResults', max_results) or max_results)

        while True:
            page_params = dict(params)
            self._add_pagination_params(page_params, start_at, effective_max_results)

            try:
                response = await request_page(page_params)
            except Exception as error:
                if on_error is not None:
                    handled_values = on_error(error)
                    if handled_values is not None:
                        return handled_values
                self.logger.warning('Failed to fetch %s', context_name, exc_info=True)
                break

            if not response:
                break

            page_values = cast(list[dict], response.get(values_key, []))
            values.extend(page_values)

            if on_page is not None:
                on_page(response, page_values)

            if response.get('isLast', True) or not page_values:
                break

            response_max_results = int(response.get('maxResults', effective_max_results) or 0)
            start_at = int(response.get('startAt', start_at) or start_at) + len(page_values)
            if response_max_results > 0:
                effective_max_results = response_max_results

        return values

    def _process_filters(
        self, filter_values: list[dict], starred_only: bool, seen_ids: set[str]
    ) -> list[dict[str, Any]]:
        """Process filter data from API response.

        Args:
            filter_values: List of filter dictionaries from API response
            starred_only: If True, only include starred filters
            seen_ids: Set of filter IDs already processed (to avoid duplicates)

        Returns:
            List of processed filter dictionaries
        """
        processed = []

        for filter_data in filter_values:
            filter_id = filter_data.get('id', '')
            name = filter_data.get('name', '')
            is_favourite = filter_data.get('favourite', False)
            jql = filter_data.get('jql', '')

            if filter_id in seen_ids:
                continue

            if starred_only and not is_favourite:
                self.logger.info(
                    'Skipping non-starred filter',
                    extra=build_log_extra({'filter_name': name}),
                )
                continue

            if not name or not jql:
                self.logger.warning(
                    'Filter missing name or JQL',
                    extra=build_log_extra({'filter_data': filter_data}),
                )
                continue

            processed.append(
                {
                    'label': name,
                    'expression': jql,
                    'source': 'remote',
                    'starred': is_favourite,
                }
            )
            seen_ids.add(filter_id)

        return processed

    async def search_users(self, offset: int | None = None, limit: int | None = None) -> list[dict]:
        """Retrieves a list of all users, including active users, inactive users and previously deleted users that have
        an Atlassian account.

        Args:
            offset: the index of the first item to return.
            limit: the maximum number of items to return (limited to 1000).

        Returns:
            A list of dictionaries with the details of the users.
        """
        params = self._build_user_search_params(offset, limit)
        return cast(
            list[dict],
            await self._client.make_request(
                method=httpx.AsyncClient.get, url='users/search', params=params
            ),
        )

    async def user_search(
        self,
        username: str | None = None,
        query: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Retrieves a list of active users that match the search string and property.

        Args:
            username: the username to filter users.
            query: a query string that is matched against user attributes (`displayName`, and `emailAddress`) to
            find relevant users.
            offset: the index of the first item to return.
            limit: the maximum number of items to return (limited to 1000).

        Returns:
            A list of dictionaries with the details of the users.
        """
        params = self._build_user_search_params(offset, limit, username=username, query=query)
        return cast(
            list[dict],
            await self._client.make_request(
                method=httpx.AsyncClient.get, url='user/search', params=params
            ),
        )

    async def add_comment(
        self,
        work_item_id_or_key: str,
        message: str,
        jsd_public: bool | None = None,
    ) -> dict:
        """Adds a comment to a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item whose comment we want to retrieve.
            message: the message of the comment.

        Returns:
            A dictionary with the details of the comment.
        """
        if jsd_public is not None:
            return await self.add_service_desk_comment(
                work_item_id_or_key,
                message,
                public=jsd_public,
            )

        payload = self._build_payload_to_add_comment(message)
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.post,
                url=f'issue/{work_item_id_or_key}/comment',
                data=json.dumps(payload),
            ),
        )

    async def get_my_permissions(
        self,
        *,
        work_item_id_or_key: str,
        permissions: list[str],
    ) -> dict:
        """Retrieves current-user permissions in an issue context."""
        params = {
            'issueKey': work_item_id_or_key,
            'permissions': ','.join(permissions),
        }
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url='mypermissions',
                params=params,
            ),
        )

    @staticmethod
    def _build_payload_to_add_comment(
        message: str,
    ) -> dict:
        """Build payload for adding a comment, converting markdown to ADF.

        Args:
            message: Markdown text to convert to ADF

        Returns:
            Dictionary with ADF body structure
        """
        from gojeera.utils.markdown.adf_helpers import text_to_adf

        adf_doc = text_to_adf(message, track_warnings=False)

        return {'body': adf_doc}

    async def add_service_desk_comment(
        self,
        work_item_id_or_key: str,
        message: str,
        *,
        public: bool,
    ) -> dict:
        """Adds a public or internal Jira Service Management request comment."""
        payload = {'body': message, 'public': public}
        return cast(
            dict,
            await self._service_desk_client.make_request(
                method=httpx.AsyncClient.post,
                url=f'request/{work_item_id_or_key}/comment',
                data=json.dumps(payload),
            ),
        )

    async def update_comment(
        self,
        work_item_id_or_key: str,
        comment_id: str,
        message: str,
    ) -> dict:
        """Updates a comment on a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item whose comment we want to update.
            comment_id: the ID of the comment to update.
            message: the new message content in markdown format.

        Returns:
            A dictionary with the details of the updated comment.
        """
        payload = self._build_payload_to_add_comment(message)
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.put,
                url=f'issue/{work_item_id_or_key}/comment/{comment_id}',
                data=json.dumps(payload),
            ),
        )

    async def get_comment(self, work_item_id_or_key: str, comment_id: str) -> dict:
        """Retrieves the detail sof a comment.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item whose comment we want to retrieve.
            comment_id: the ID of the comment.

        Returns:
            A dictionary with the details of the comment.
        """
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/{work_item_id_or_key}/comment/{comment_id}',
                params={'expand': 'renderedBody'},
            ),
        )

    async def get_comments(
        self, work_item_id_or_key: str, offset: int | None = None, limit: int | None = None
    ) -> dict:
        """Retrieves the comments of a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item whose comment we want to retrieve.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page. Default: 50.

        Returns:
            A dictionary with the details of the comments.
        """
        params: dict[str, Any] = {'orderBy': '-created', 'expand': 'renderedBody'}
        if limit is not None:
            params['maxResults'] = limit
        if offset is not None:
            params['startAt'] = offset
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/{work_item_id_or_key}/comment',
                params=params,
            ),
        )

    async def get_work_item_changelog(
        self, work_item_id_or_key: str, offset: int | None = None, limit: int | None = None
    ) -> dict:
        """Retrieves the changelog history of a work item."""
        params: dict[str, Any] = self._add_pagination_params({}, offset, limit)
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/{work_item_id_or_key}/changelog',
                params=params,
            ),
        )

    async def delete_comment(self, work_item_id_or_key: str, comment_id: str) -> None:
        """Deletes a comment.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item whose comment we want to delete.
            comment_id: the ID of the comment.

        Returns:
            Nothing if the comment is deleted; an exception otherwise.
        """
        await self._client.make_request(
            method=httpx.AsyncClient.delete,
            url=f'issue/{work_item_id_or_key}/comment/{comment_id}',
        )
        return None

    async def work_item_edit_metadata(self, work_item_id_or_key: str) -> dict:
        """Retrieves the edit screen fields for a work item that are visible to and editable by the user.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.

        Returns:
            A dictionary with the metadata.
        """
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get, url=f'issue/{work_item_id_or_key}/editmeta'
            ),
        )

    async def update_work_item(
        self,
        work_item_id_or_key: str,
        payload: dict | None = None,
        fields: dict | None = None,
        override_screen_security: bool = False,
        override_editable_flag: bool = False,
    ) -> dict:
        """Updates a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.
            payload: update operations keyed by field name.
            fields: direct field values for the issue update request.

        Returns:
            A dictionary with the details of the work item after the update.
        """
        data: dict[str, Any] = {}
        if payload:
            data['update'] = payload
        if fields:
            data['fields'] = fields
        params: dict[str, Any] = {'returnIssue': True}
        if override_screen_security:
            params['overrideScreenSecurity'] = True
        if override_editable_flag:
            params['overrideEditableFlag'] = True

        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.put,
                url=f'issue/{work_item_id_or_key}',
                data=json.dumps(data),
                params=params,
            ),
        )

    async def create_work_item(self, fields: dict) -> dict:
        """Creates a work item.

        Args:
            fields: a dictionary with the fields and their values to create the item.

        Returns:
            A dictionary with the details of the new item.
        """
        payload = {'fields': fields}
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.post, url='issue', data=json.dumps(payload)
            ),
        )

    async def clone_work_item(
        self,
        work_item_id_or_key: str,
        fields_to_clone: dict,
        link_to_original: bool = True,
    ) -> dict:
        """Clones a work item by creating a new item with the specified fields.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item to clone.
            fields_to_clone: a dictionary with the fields and their values for the cloned item.
            link_to_original: if True, creates a "Cloners" link between the original and cloned items.

        Returns:
            A dictionary with the details of the cloned item, including its key.
        """

        cloned_item = await self.create_work_item(fields_to_clone)

        if link_to_original and cloned_item.get('key'):
            try:
                link_types_response = await self.work_item_link_types()
                cloners_link_type = None

                for link_type in link_types_response.get('issueLinkTypes', []):
                    if link_type.get('name') == 'Cloners':
                        cloners_link_type = link_type
                        break

                if cloners_link_type:
                    link_payload = {
                        'type': {'id': cloners_link_type.get('id')},
                        'inwardIssue': {'key': work_item_id_or_key},
                        'outwardIssue': {'key': cloned_item.get('key')},
                    }
                    await self._client.make_request(
                        method=httpx.AsyncClient.post,
                        url='issueLink',
                        data=json.dumps(link_payload),
                    )
            except Exception:
                self.logger.warning(
                    'Failed to create link between original and cloned work items',
                    exc_info=True,
                )

        return cloned_item

    async def transitions(self, work_item_id_or_key: str) -> dict:
        """Retrieves the applicable transitions for a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.

        Returns:
            A dictionary with the details of the transitions.
        """
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get, url=f'issue/{work_item_id_or_key}/transitions'
            ),
        )

    async def transition_work_item(self, work_item_id_or_key: str, transition_id: str) -> None:
        """Performs a work item transition.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.
            transition_id: the ID of the status transition.

        Returns:
            Nothing.
        """
        payload = {'transition': transition_id}
        await self._client.make_request(
            method=httpx.AsyncClient.post,
            url=f'issue/{work_item_id_or_key}/transitions',
            data=json.dumps(payload),
        )
        return None

    async def create_work_item_link(
        self,
        left_work_item_key: str,
        right_work_item_key: str,
        link_type: str,
        link_type_id: str,
    ) -> None:
        """Creates a link between two work items. Use this operation to indicate a relationship between two work items and
        optionally add a comment to the "from" (outward) work item

        Args:
            left_work_item: the case-sensitive key of the work item.
            right_work_item_key: the case-sensitive key of the work item.
            link_type: the type of link.
            link_type_id: the ID of the type of link.

        Returns:
            Nothing.
        """
        payload = {
            'type': {
                'id': link_type_id,
            },
        }
        if link_type == 'inward':
            payload['inwardIssue'] = {'key': right_work_item_key}
            payload['outwardIssue'] = {'key': left_work_item_key}
        else:
            payload['inwardIssue'] = {'key': left_work_item_key}
            payload['outwardIssue'] = {'key': right_work_item_key}
        await self._client.make_request(
            method=httpx.AsyncClient.post,
            url='issueLink',
            data=json.dumps(payload),
        )
        return None

    async def work_item_link_types(self) -> dict:
        """Retrieves a list of all work item link types.

        Returns:
            A dictionary with the types of links between work items.
        """
        return cast(
            dict, await self._client.make_request(method=httpx.AsyncClient.get, url='issueLinkType')
        )

    async def delete_work_item_link(self, link_id: str) -> None:
        await self._client.make_request(method=httpx.AsyncClient.delete, url=f'issueLink/{link_id}')
        return None

    async def get_work_item_create_meta(
        self,
        project_id_or_key: str,
        work_item_type_id: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> dict:
        """Retrieves a page of field metadata for a specified project and type of work item id.

        Args:
            project_id_or_key: the case-sensitive key of the project.
            work_item_type_id: the ID of a type of work item.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page.

        Returns:
            A dictionary with the metadata to create work items of a given project and type.
        """
        params: dict[str, Any] = self._add_pagination_params({}, offset, limit)
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/createmeta/{project_id_or_key}/issuetypes/{work_item_type_id}',
                params=params,
            ),
        )

    def add_attachment_to_work_item(
        self,
        work_item_id_or_key: str,
        filename,
        file_name: str,
        mime_type: str | None = None,
    ) -> list[dict]:
        """Adds an attachment to a work item.

        Attachments are posted as multipart/form-data (RFC 1867).

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.
            filename: the full name of the file to upload.
            file_name: the name of the file to upload.
            mime_type: the MIME type of the file.

        Returns:
            A list of dictionaries with the results.
        """
        del mime_type

        try:
            file_to_upload = BufferedReader(BytesIO(Path(filename).read_bytes()))
        except FileNotFoundError as e:
            self.logger.warning(
                f'File not found. Unable to determine the MIME type of he file {filename}.'
            )
            raise FileUploadException(
                f'The file {filename} was not found. Unable to upload it as attachment.'
            ) from e

        detected_mime_type = self._detect_file_mime_type(file_to_upload)
        file_to_upload.seek(0)
        return cast(
            list[dict],
            self._sync_client.make_request(
                method=httpx.post,
                url=f'issue/{work_item_id_or_key}/attachments',
                headers={'X-Atlassian-Token': 'no-check'},
                files={'file': (file_name, file_to_upload, detected_mime_type)},
            ),
        )

    @staticmethod
    def _detect_file_mime_type(file_to_upload: BinaryIO) -> str:
        return magic.from_buffer(file_to_upload.read(2028), mime=True)

    async def delete_attachment(self, attachment_id: str) -> None:
        """Deletes an attachment from a work item.

        Args:
            attachment_id: The ID of the attachment.

        Returns:
            `None`; HTTP 204 if successful or an exception otherwise.
        """
        await self._client.make_request(
            method=httpx.AsyncClient.delete, url=f'attachment/{attachment_id}'
        )
        return None

    async def get_attachment_content(self, attachment_id: str) -> Any:
        """Retrieves the contents of an attachment.

        Args:
            attachment_id: The ID of the attachment.

        Returns:
            A bytes representation of the attachment's content.
        """
        return await self._async_http_client.make_request(
            method=httpx.AsyncClient.get,
            url=f'attachment/content/{attachment_id}',
            follow_redirects=True,
        )

    async def get_work_item_work_log(
        self,
        work_item_id_or_key: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> dict:
        """Retrieves work logs for a work item (ordered by created time), starting from the oldest worklog or from the
        worklog started on or after a date and time.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page. Default: 5000.

        Returns:
            A dictionary with the worklog of the work item.
        """
        params = self._add_pagination_params({}, offset, limit)
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.get,
                url=f'issue/{work_item_id_or_key}/worklog',
                params=params,
            ),
        )

    async def add_work_item_work_log(
        self,
        work_item_id_or_key: str,
        time_spent: str,
        started: datetime,
        time_remaining: str | None = None,
        comment: str | None = None,
    ) -> dict:
        """Adds a worklog to a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.
            comment: a comment about the worklog. Optional when creating or updating a worklog.
            started: the datetime on which the worklog effort was started. Required when creating a worklog. Optional
            when updating a worklog.
            time_spent: the time spent working on the work item as days (#d), hours (#h), or minutes (#m or #). Required
            when creating a worklog if timeSpentSeconds isn't provided. Optional when updating a worklog. Cannot be
            provided if timeSpentSecond is provided.
            time_remaining: the value to set as the work item's remaining time estimate, as days (#d), hours (#h),
            or minutes (#m or #). For example, 2d. Required when adjustEstimate is new.

        Returns:
            A dictionary with the worklog's details.
        """
        payload: dict[str, Any] = {
            'started': started.isoformat(timespec='milliseconds').replace('+00:00', '+0000'),
            'timeSpent': time_spent,
        }
        if comment and (comment_payload := self._build_worklog_comment_payload(comment)):
            payload['comment'] = comment_payload
        params = self._build_worklog_adjust_estimate_params(time_remaining)
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.post,
                url=f'issue/{work_item_id_or_key}/worklog',
                data=json.dumps(payload),
                params=params,
            ),
        )

    async def update_work_log(
        self,
        work_item_id_or_key: str,
        worklog_id: str,
        time_spent: str | None = None,
        started: datetime | None = None,
        time_remaining: str | None = None,
        comment: str | None = None,
    ) -> dict:
        """Updates a worklog for a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.
            worklog_id: the ID of the worklog to update.
            time_spent: the time spent working on the work item as days (#d), hours (#h), or minutes (#m or #). Required
            when creating a worklog if timeSpentSeconds isn't provided. Optional when updating a worklog. Cannot be
            provided if timeSpentSecond is provided.
            started: the datetime on which the worklog effort was started. Required when creating a worklog. Optional
            when updating a worklog.
            comment: a comment about the worklog. Optional when creating or updating a worklog.
            time_remaining: the value to set as the work item's remaining time estimate, as days (#d), hours (#h),
            or minutes (#m or #). For example, 2d. Required when adjustEstimate is new.

        Returns:
            A dictionary with the updated worklog's details.
        """
        payload: dict[str, Any] = {}
        if started:
            payload['started'] = started.isoformat(timespec='milliseconds').replace(
                '+00:00', '+0000'
            )
        if time_spent:
            payload['timeSpent'] = time_spent
        if comment is not None and (
            comment_payload := self._build_worklog_comment_payload(comment)
        ):
            payload['comment'] = comment_payload

        params = self._build_worklog_adjust_estimate_params(time_remaining)

        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.put,
                url=f'issue/{work_item_id_or_key}/worklog/{worklog_id}',
                data=json.dumps(payload),
                params=params,
            ),
        )

    async def delete_work_log(self, work_item_id_or_key: str, worklog_id: str) -> bool:
        """Deletes a worklog from a work item.

        Args:
            work_item_id_or_key: the ID or key of the work item.
            worklog_id: the ID of the worklog.

        Returns:
            True if the operation succeeds.
        """
        await self._client.make_request(
            method=httpx.AsyncClient.delete,
            url=f'issue/{work_item_id_or_key}/worklog/{worklog_id}',
        )
        return True

    @staticmethod
    def _build_worklog_comment_payload(message: str) -> dict:
        """Builds the payload required for adding/set a description/comment to a worklog when a worklog is added to a work item.

        Args:
            message: a comment about the worklog (markdown format). Optional when creating or updating a worklog.

        Returns:
            A dictionary with the payload's data for setting the worklog's comment/description in ADF format.
        """
        from gojeera.utils.markdown.adf_helpers import text_to_adf

        return cast(dict, text_to_adf(message, track_warnings=False))

    async def get_fields(self) -> list[dict]:
        """Retrieves work item fields.

        Returns:
            A list of dictionaries.
        """
        return cast(
            list[dict], await self._client.make_request(method=httpx.AsyncClient.get, url='field')
        )

    async def get_all_fields_paginated(
        self,
        max_results: int = 100,
        query: str | None = None,
        field_ids: list[str] | None = None,
    ) -> list[dict]:
        """Retrieves all paginated work item fields with extended metadata."""
        params: dict[str, Any] = {}
        if query:
            params['query'] = query
        if field_ids:
            params['id'] = field_ids

        return await self._fetch_paginated_values(
            request_page=lambda page_params: cast(
                Awaitable[dict[str, Any] | None],
                self._client.make_request(
                    method=httpx.AsyncClient.get,
                    url='field/search',
                    params=page_params,
                ),
            ),
            params=params,
            context_name='fields',
            max_results=max_results,
        )

    async def get_label_suggestions(self, query: str = '') -> Any | None:
        """Return label suggestions from Jira."""
        return await self._client.get_label_suggestions(query)

    async def get_boards_for_project(
        self,
        project_key_or_id: str,
        board_type: str | None = None,
    ) -> list[dict]:
        """Fetch boards for a project using Jira Software API.

        Args:
            project_key_or_id: Project key (e.g., 'PROJ') or ID
            board_type: Optional filter - 'scrum', 'kanban', 'simple'

        Returns:
            List of board dictionaries
        """
        cached_boards = await run_cache_io(
            lambda: self.cache.get_boards_for_project(str(project_key_or_id), allow_stale=True)
        )
        needs_refresh = await run_cache_io(
            lambda: self.cache.needs_refresh('boards', str(project_key_or_id))
        )
        if cached_boards is not None and not needs_refresh:
            return [
                board.as_jira_dict()
                for board in cached_boards
                if not board_type or board.type == board_type
            ]

        params: dict[str, Any] = {'projectKeyOrId': project_key_or_id}
        if board_type:
            params['type'] = board_type
        boards = await self._fetch_paginated_agile_values(
            url='board',
            params=params,
            context_name=f'boards for project {project_key_or_id}',
        )
        await run_cache_io(
            lambda: self.cache.set_boards_for_project(str(project_key_or_id), boards)
        )
        return boards

    async def get_projects_for_board(self, board_id: int) -> list[dict]:
        """Fetch projects associated with a board using Jira Software API."""
        return await self._fetch_paginated_agile_values(
            url=f'board/{board_id}/project',
            params={},
            context_name=f'projects for board {board_id}',
        )

    async def get_sprints_for_board(
        self,
        board_id: int,
        state: str | None = None,
    ) -> list[dict]:
        """Fetch sprints for a board using Jira Software API.

        Args:
            board_id: The board ID
            state: Optional filter - comma-separated: 'active', 'future', 'closed'
                   Example: 'active,future'

        Returns:
            List of sprint dictionaries
        """
        params: dict[str, Any] = {}
        if state:
            params['state'] = state

        def handle_sprint_error(error: Exception) -> list[dict] | None:
            error_context = getattr(getattr(error, 'details', None), 'remote_payload', {}) or {}
            error_messages = error_context.get('errorMessages', [])
            first_error = error_messages[0] if error_messages else str(error)
            if 'does not support sprints' in first_error.lower():
                self.logger.info(f'Board {board_id} does not support sprints; skipping')
                return []

            self.logger.warning(
                'Failed to fetch sprints for board %s',
                board_id,
                exc_info=True,
            )
            return []

        sprints = await self._fetch_paginated_values(
            request_page=lambda page_params: cast(
                Awaitable[dict[str, Any] | None],
                self._agile_client.make_request(
                    method=httpx.AsyncClient.get,
                    url=f'board/{board_id}/sprint',
                    params=page_params,
                ),
            ),
            params=params,
            context_name=f'sprints for board {board_id}',
            on_error=handle_sprint_error,
        )
        return sprints

    async def get_sprints_for_project(
        self,
        project_key_or_id: str,
        states: list[str] | None = None,
    ) -> list[dict]:
        """Fetch all sprints for a project from all boards.

        Args:
            project_key_or_id: Project key or ID
            states: List of sprint states to filter - ['active', 'future']

        Returns:
            List of sprint dictionaries, sorted by state and name

        Note:
            - Same sprint can appear on multiple boards
            - Returns unique sprints only
            - Active sprints first, then future, then closed
        """
        # Default to active and future sprints only
        if states is None:
            states = ['active', 'future']

        state_filter = ','.join(states) if states else None
        normalized_project = str(project_key_or_id).strip().lower()

        boards = await self.get_boards_for_project(project_key_or_id, board_type='scrum')

        # `projectKeyOrId` filtering on the board endpoint is not sufficient for
        # all real boards. Some boards include the project's issues without their
        # board filter directly referencing the project key, so they are omitted
        # from `/board?projectKeyOrId=...`. Fall back to scanning boards via
        # `/board/{id}/project` when the direct filter misses them.
        if not boards:
            all_boards = await self._fetch_paginated_agile_values(
                url='board',
                params={'type': 'scrum'},
                context_name='all scrum boards',
            )
            matching_boards: list[dict] = []
            matching_board_ids: set[int] = set()
            boards_requiring_project_lookup: list[dict] = []

            for board in all_boards:
                board_id = board.get('id')
                if not board_id:
                    continue

                location = board.get('location')
                if isinstance(location, dict):
                    location_project_key = str(location.get('projectKey') or '').strip().lower()
                    location_project_id = str(location.get('projectId') or '').strip().lower()
                    if normalized_project in {location_project_key, location_project_id}:
                        board_id_int = int(board_id)
                        if board_id_int not in matching_board_ids:
                            matching_boards.append(board)
                            matching_board_ids.add(board_id_int)
                        continue

                boards_requiring_project_lookup.append(board)

            semaphore = asyncio.Semaphore(8)

            async def board_matches_project(board: dict) -> dict | None:
                board_id = board.get('id')
                if not board_id:
                    return None

                try:
                    async with semaphore:
                        board_projects = await self.get_projects_for_board(int(board_id))
                except Exception:
                    return None

                for project in board_projects:
                    project_key = str(project.get('key') or '').strip().lower()
                    project_id = str(project.get('id') or '').strip().lower()
                    if normalized_project in {project_key, project_id}:
                        return board

                return None

            if boards_requiring_project_lookup:
                board_matches = await asyncio.gather(
                    *(board_matches_project(board) for board in boards_requiring_project_lookup)
                )
                for board in board_matches:
                    if not isinstance(board, dict):
                        continue
                    board_id = board.get('id')
                    if not board_id:
                        continue
                    board_id_int = int(board_id)
                    if board_id_int in matching_board_ids:
                        continue
                    matching_boards.append(board)
                    matching_board_ids.add(board_id_int)

            boards = matching_boards

        if not boards:
            self.logger.warning(f'No boards found for project {project_key_or_id}')
            return []

        scrum_boards: list[dict[str, Any]] = []
        for board in boards:
            board_id = board.get('id')
            if not board_id:
                continue
            scrum_boards.append(board)

        semaphore = asyncio.Semaphore(8)

        async def fetch_board_sprints(board: dict[str, Any]) -> list[dict[str, Any]]:
            board_id = board.get('id')
            if not board_id:
                return []

            async with semaphore:
                sprints = await self.get_sprints_for_board(int(board_id), state_filter)
            return [sprint for sprint in sprints if isinstance(sprint, dict)]

        sprint_batches = await asyncio.gather(
            *(fetch_board_sprints(board) for board in scrum_boards)
        )
        all_sprints = [sprint for batch in sprint_batches for sprint in batch]

        unique_sprints: dict[int, dict[str, Any]] = {}
        for sprint in all_sprints:
            sprint_id = sprint.get('id')
            if sprint_id and sprint_id not in unique_sprints:
                unique_sprints[sprint_id] = sprint

        state_priority = {'active': 0, 'future': 1, 'closed': 2}
        sorted_sprints = sorted(
            unique_sprints.values(),
            key=lambda s: (
                state_priority.get(str(s.get('state') or '').lower(), 99),
                str(s.get('name') or ''),
            ),
        )

        return sorted_sprints
