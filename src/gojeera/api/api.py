from datetime import date, datetime
from io import BufferedReader
import json
import logging
from typing import Any, cast

import httpx
import magic

from gojeera.api.client import AsyncHTTPClient, AsyncJiraClient, JiraClient
from gojeera.api.utils import build_work_item_search_jql
from gojeera.config import ApplicationConfiguration
from gojeera.constants import LOGGER_NAME, WORK_ITEM_SEARCH_DEFAULT_MAX_RESULTS
from gojeera.exceptions import FileUploadException
from gojeera.utils.adf_helpers import text_to_adf
from gojeera.utils.obfuscation import obfuscate_account_id


class JiraAPI:
    """Implements methods to connect to the Jira REST API provided by the Jira Cloud Platform."""

    API_PATH_PREFIX = '/rest/api/3/'

    def __init__(
        self,
        base_url: str,
        api_username: str,
        api_token: str,
        configuration: ApplicationConfiguration,
    ):
        self._client = AsyncJiraClient(
            base_url=f'{base_url.rstrip("/")}{self.API_PATH_PREFIX}',
            api_username=api_username,
            api_token=api_token.strip(),
            configuration=configuration,
        )

        self._sync_client = JiraClient(
            base_url=f'{base_url.rstrip("/")}{self.API_PATH_PREFIX}',
            api_username=api_username,
            api_token=api_token.strip(),
            configuration=configuration,
        )

        self._async_http_client = AsyncHTTPClient(
            base_url=f'{base_url.rstrip("/")}{self.API_PATH_PREFIX}',
            api_username=api_username,
            api_token=api_token.strip(),
            configuration=configuration,
        )
        self._base_url = base_url
        self.logger = logging.getLogger(LOGGER_NAME)

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def client(self) -> AsyncJiraClient:
        return self._client

    @property
    def async_http_client(self) -> AsyncHTTPClient:
        return self._async_http_client

    @property
    def sync_client(self) -> JiraClient:
        return self._sync_client

    async def search_projects(
        self,
        offset: int | None = None,
        limit: int | None = None,
        query: str | None = None,
        keys: list[str] | None = None,
    ) -> dict:
        """Retrieves a paginated list of projects visible to the user (making the request).

        Args:
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page. Must be less than or equal to 100.
            query: filter the results using a literal string. Projects with a matching key or name are returned
            (case-insensitive).
            keys: the project keys to filter the results by.

        Returns:
            A dictionary with the details of the projects.
        """
        params: dict[str, Any] = {}
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
        if query is not None:
            params['query'] = query
        if keys:
            params['keys'] = ','.join(keys[:50])

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
            query: a string that is matched against user attributes, such as `displayName`, and `emailAddress`, to find
            relevant users. The string can match the prefix of the attribute's value. For example, `query=john` matches
            a user with a `displayName` of John Smith and a user with an `emailAddress` of johnson@example.com.
            Required, unless `username` or `accountId` is specified.

        Returns:
            A list of dictionaries with the details of the users.
        """
        if not any([project_id_or_key, work_item_id, work_item_key]):
            raise ValueError(
                'One of these parameters is required: project_id, work_item_id, work_item_key'
            )

        params: dict[str, Any] = {}
        if project_id_or_key:
            params['project'] = project_id_or_key
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
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
            query: a string that is matched against user attributes, such as `displayName`, and `emailAddress`, to find
            relevant users. The string can match the prefix of the attribute's value. For example, `query=john` matches
            a user with a `displayName` of John Smith and a user with an `emailAddress` of johnson@example.com.
            Required, unless `username` or `accountId` is specified.

        Returns:
            A list of dictionaries with the details of the users.
        """
        params: dict[str, Any] = {}
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
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

    async def create_work_item_remote_link(
        self, work_item_id_or_key: str, url: str, title: str
    ) -> None:
        """Creates or updates a remote work item link for a work item.

        Args:
            work_item_id_or_key: the ID or case-sensitive key of the work item
            url: the URL of the link.
            title: the title of the link.

        Returns:
            Nothing.
        """
        payload: dict[str, Any] = {
            'object': {
                'title': title,
                'url': url,
            }
        }
        await self._client.make_request(
            method=httpx.AsyncClient.post,
            url=f'issue/{work_item_id_or_key}/remotelink',
            data=json.dumps(payload),
        )

    async def delete_work_item_remote_link(self, work_item_id_or_key: str, link_id: str) -> None:
        """Deletes a web link associated to a work item.

        Args:
            work_item_id_or_key: the ID or case-sensitive key of the work item
            link_id: the IF of the link.

        Returns:
            Nothing.
        """
        await self._client.make_request(
            method=httpx.AsyncClient.delete,
            url=f'issue/{work_item_id_or_key}/remotelink/{link_id}',
        )
        return None

    async def update_work_item_remote_link(
        self, work_item_id_or_key: str, link_id: str, url: str, title: str
    ) -> None:
        """Updates a remote work item link for a work item.

        Args:
            work_item_id_or_key: the ID or case-sensitive key of the work item
            link_id: the ID of the link to update.
            url: the URL of the link.
            title: the title of the link.

        Returns:
            Nothing.
        """
        payload: dict[str, Any] = {
            'object': {
                'title': title,
                'url': url,
            }
        }
        await self._client.make_request(
            method=httpx.AsyncClient.put,
            url=f'issue/{work_item_id_or_key}/remotelink/{link_id}',
            data=json.dumps(payload),
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
    ) -> list[dict[str, str]]:
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

        if account_id:
            self.logger.info(
                f'Fetching personal filters for account_id={obfuscate_account_id(account_id)}'
            )
            personal_params: dict[str, Any] = {
                'maxResults': max_results,
                'expand': 'jql,favourite',
                'accountId': account_id,
            }

            personal_response = await self._client.make_request(
                method=httpx.AsyncClient.get,
                url='filter/search',
                params=personal_params,
            )

            if personal_response and 'values' in personal_response:
                self.logger.info(f'Received {len(personal_response["values"])} personal filters')
                filters.extend(
                    self._process_filters(personal_response['values'], starred_only, seen_ids)
                )

        if include_shared:
            self.logger.info('Fetching shared filters (accessible via groups/projects)')
            shared_params: dict[str, Any] = {
                'maxResults': max_results,
                'expand': 'jql,favourite',
            }

            shared_response = await self._client.make_request(
                method=httpx.AsyncClient.get,
                url='filter/search',
                params=shared_params,
            )

            if shared_response and 'values' in shared_response:
                self.logger.info(f'Received {len(shared_response["values"])} shared filters')
                filters.extend(
                    self._process_filters(shared_response['values'], starred_only, seen_ids)
                )

        self.logger.info(f'Returning {len(filters)} total filters')
        return filters

    def _process_filters(
        self, filter_values: list[dict], starred_only: bool, seen_ids: set[str]
    ) -> list[dict[str, str]]:
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
                self.logger.info(f'Skipping non-starred filter: {name}')
                continue

            if not name or not jql:
                self.logger.warning(f'Filter missing name or JQL: {filter_data}')
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
        params: dict[str, Any] = {}
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
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
        params: dict[str, Any] = {}
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
        if username is not None:
            params['username'] = username
        if query is not None:
            params['query'] = query
        return cast(
            list[dict],
            await self._client.make_request(
                method=httpx.AsyncClient.get, url='user/search', params=params
            ),
        )

    async def add_comment(self, work_item_id_or_key: str, message: str) -> dict:
        """Adds a comment to a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item whose comment we want to retrieve.
            message: the message of the comment.

        Returns:
            A dictionary with the details of the comment.
        """
        payload = self._build_payload_to_add_comment(message)
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.post,
                url=f'issue/{work_item_id_or_key}/comment',
                data=json.dumps(payload),
            ),
        )

    @staticmethod
    def _build_payload_to_add_comment(message: str) -> dict:
        """Build payload for adding a comment, converting markdown to ADF.

        Args:
            message: Markdown text to convert to ADF

        Returns:
            Dictionary with ADF body structure
        """

        adf_doc = text_to_adf(message, track_warnings=False)

        return {'body': adf_doc}

    async def update_comment(self, work_item_id_or_key: str, comment_id: str, message: str) -> dict:
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
            ),
        )

    async def get_comments(
        self, work_item_id_or_key: str, offset: int | None = None, limit: int | None = None
    ) -> dict:
        """Retrieves the comments of a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item whose comment we want to retrieve.
            offset: the index of the first item to return in a page of results (page offset).
            limit: the maximum number of items to return per page. The default is 50.

        Returns:
            A dictionary with the details of the comments.
        """
        params: dict[str, Any] = {'orderBy': '-created'}
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

    async def update_work_item(self, work_item_id_or_key: str, payload: dict) -> dict:
        """Updates a work item.

        Args:
            work_item_id_or_key: the case-sensitive key of the work item.
            payload: the fields and their values.

        Returns:
            A dictionary with the details of the work item after the update.
        """
        data = {'update': payload}
        return cast(
            dict,
            await self._client.make_request(
                method=httpx.AsyncClient.put,
                url=f'issue/{work_item_id_or_key}',
                data=json.dumps(data),
                params={'returnIssue': True},
            ),
        )

    async def new_work_item(self, fields: dict) -> dict:
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

        cloned_item = await self.new_work_item(fields_to_clone)

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
            except Exception as e:
                self.logger.warning(
                    f'Failed to create link between original and cloned work items: {e}'
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
        params: dict[str, Any] = {}
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
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

        with open(filename, 'rb') as file_to_upload:
            try:
                detected_mime_type: str = self._detect_file_mime_type(file_to_upload)
            except FileNotFoundError as e:
                self.logger.warning(
                    f'File not found. Unable to determine the MIME type of he file {filename}.'
                )
                raise FileUploadException(
                    f'The file {filename} was not found. Unable to upload it as attachment.'
                ) from e
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
    def _detect_file_mime_type(file_to_upload: BufferedReader) -> str:
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
            limit: the maximum number of items to return per page. The default is 5000.

        Returns:
            A dictionary with the worklog of the work item.
        """
        params = {}
        if offset is not None:
            params['startAt'] = offset
        if limit is not None:
            params['maxResults'] = limit
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
        params = {'adjustEstimate': 'auto'}
        if time_remaining:
            params = {'newEstimate': time_remaining, 'adjustEstimate': 'new'}
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

        params = {'adjustEstimate': 'auto'}
        if time_remaining:
            params = {'newEstimate': time_remaining, 'adjustEstimate': 'new'}

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

        return cast(dict, text_to_adf(message, track_warnings=False))

    async def get_fields(self) -> list[dict]:
        """Retrieves work item fields.

        Returns:
            A list of dictionaries.
        """
        return cast(
            list[dict], await self._client.make_request(method=httpx.AsyncClient.get, url='field')
        )

    async def get_label_suggestions(self, query: str = '') -> Any | None:
        """Get label suggestions from Jira.

        Args:
            query: search query to filter label suggestions

        Returns:
            List of label suggestions or None if request fails
        """
        return await self._client.get_label_suggestions(query)
