from collections import defaultdict
import dataclasses
from dataclasses import dataclass
from datetime import date, datetime
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, cast

from dateutil.parser import isoparse

from gojeera.api.api import JiraAPI
from gojeera.api_controller.factories import WorkItemFactory
from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION, ApplicationConfiguration
from gojeera.constants import (
    ATTACHMENT_MAXIMUM_FILE_SIZE_IN_BYTES,
    LOGGER_NAME,
    MAXIMUM_PAGE_NUMBER_SEARCH_PROJECTS,
    RECORDS_PER_PAGE_SEARCH_PROJECTS,
    RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_PROJECTS,
    RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_WORK_ITEMS,
)
from gojeera.exceptions import (
    ServiceInvalidResponseException,
    ServiceUnavailableException,
    UpdateWorkItemException,
    ValidationError,
)
from gojeera.models import (
    Attachment,
    BaseModel,
    JiraBaseWorkItem,
    JiraField,
    JiraGlobalSettings,
    JiraMyselfInfo,
    JiraServerInfo,
    JiraSprint,
    JiraTimeTrackingConfiguration,
    JiraUser,
    JiraUserGroup,
    JiraWorkItem,
    JiraWorkItemGenericFields,
    JiraWorkItemSearchResponse,
    JiraWorklog,
    LinkWorkItemType,
    PaginatedJiraWorklog,
    Project,
    UpdateWorkItemResponse,
    WorkItemComment,
    WorkItemRemoteLink,
    WorkItemStatus,
    WorkItemTransition,
    WorkItemTransitionState,
    WorkItemType,
)


@dataclass
class APIControllerResponse(BaseModel):
    success: bool = True
    result: Any | None = None
    error: str | None = None

    def as_dict(self):
        return dataclasses.asdict(self)


class APIController:
    """A controller for the JirAPI to provide some additional functionality and integration of multiple endpoints."""

    def __init__(self, configuration: ApplicationConfiguration | None = None):
        self.config = CONFIGURATION.get() if not configuration else configuration
        self.api: JiraAPI

        self.api = JiraAPI(
            base_url=self.config.jira.api_base_url,
            api_username=self.config.jira.api_username,
            api_token=self.config.jira.api_token.get_secret_value(),
            configuration=self.config,
        )
        self.skip_users_without_email = self.config.ignore_users_without_email
        self.logger = logging.getLogger(LOGGER_NAME)
        self.cache = get_cache()

    @staticmethod
    def _extract_exception_details(exception: Exception) -> dict:
        extra: dict = getattr(exception, 'extra', {}) or {}
        error_messages = extra.get('errorMessages', [])
        message = error_messages[0] if error_messages else str(exception)
        return {'message': message, 'extra': extra}

    async def get_project(self, key: str) -> APIControllerResponse:
        """Retrieves the details of a project by key.

        Args:
            key: the case-sensitive key of the project.

        Returns:
            An instance of `APIControllerResponse` with the details of the project in the `result key; `success=False`
            and the detail of the error if the project can not be retrieved.
        """

        try:
            response: dict = await self.api.get_project(key)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve project',
                extra={
                    'key': key,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse(
            result=Project(
                id=str(response.get('id', '')),
                name=response.get('name', ''),
                key=response.get('key', ''),
            ),
        )

    async def search_projects(
        self,
        query: str | None = None,
        keys: list[str] | None = None,
    ) -> APIControllerResponse:
        """Searches for projects using different filters.

        Args:
            query: filter the results using a literal string. Projects with a matching key or name are returned
            (case-insensitive).
            keys: the project keys to filter the results by.

        Returns:
            An instance of `APIControllerResponse` with the list of `Project` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """

        projects: list[Project] = []
        is_last = False
        i = 0
        while not is_last and i < MAXIMUM_PAGE_NUMBER_SEARCH_PROJECTS:
            try:
                response: dict = await self.api.search_projects(
                    offset=i * RECORDS_PER_PAGE_SEARCH_PROJECTS,
                    limit=RECORDS_PER_PAGE_SEARCH_PROJECTS,
                    query=query,
                    keys=keys,
                )
            except Exception as e:
                exception_details: dict = self._extract_exception_details(e)
                self.logger.error(
                    'There was an error while searching projects',
                    extra={
                        'error': str(e),
                        'query': query,
                        'keys': keys,
                        'limit': RECORDS_PER_PAGE_SEARCH_PROJECTS,
                        **exception_details.get('extra', {}),
                    },
                )
                return APIControllerResponse(
                    result=projects, error=exception_details.get('message')
                )
            else:
                for project in response.get('values', []):
                    projects.append(
                        Project(
                            id=project.get('id'), key=project.get('key'), name=project.get('name')
                        )
                    )
                is_last = response.get('isLast')
                i += 1
        return APIControllerResponse(result=projects)

    async def get_project_statuses(self, project_key: str) -> APIControllerResponse:
        """Retrieves the statues applicable to work items of a project.

        Args:
            project_key: the case-sensitive key of a project.

        Returns:
            An instance of `APIControllerResponse` with the statuses grouped by type of work items. If an error occurs an
            instance of `APIControllerResponse` with the `error` message and `success = False`.
        """

        cached_statuses = self.cache.get('project_statuses', project_key)
        if cached_statuses is not None:
            return APIControllerResponse(result=cached_statuses)

        try:
            response: list[dict] = await self.api.get_project_statuses(project_key)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find status codes associated to a project',
                extra={
                    'project_key': project_key,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
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

        self.cache.set('project_statuses', statuses_by_work_item_type, project_key)

        return APIControllerResponse(result=statuses_by_work_item_type)

    async def status(self) -> APIControllerResponse:
        try:
            response: list[dict] = await self.api.status()
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
        return APIControllerResponse(result=statuses)

    async def get_work_item_types_for_project(self, project_key: str) -> APIControllerResponse:
        """Retrieves the types of work items associated to a project.

        Args:
            project_key: the ID or (case-sensitive) key of the project whose work item types we want to retrieve.

        Returns:
            An instance of `APIControllerResponse` with the list of `IssueType` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """

        cached_types = self.cache.get('project_types', project_key)
        if cached_types is not None:
            return APIControllerResponse(result=cached_types)

        try:
            project: dict = await self.api.get_project(project_key)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find work item types for the given project',
                extra={
                    'project_key': project_key,
                    **exception_details.get('extra', {}),
                },
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

        self.cache.set('project_types', work_item_types, project_key)

        return APIControllerResponse(result=work_item_types)

    async def get_work_item_types(self) -> APIControllerResponse:
        """Retrieves all the types of work items relevant for any project.

        It may contain multiple work item types with the same name (different IDs though).

        Returns:
            An instance of `APIControllerResponse` with the list of `IssueType` instances. If an error occurs an
            instance of `APIControllerResponse` with the `error` message.
        """
        try:
            response: list[dict] = await self.api.get_work_items_types_for_user()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to find work item types', extra=exception_details.get('extra', {})
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        else:
            projects_by_id: dict[str, Project] = {}
            projects: APIControllerResponse = await self.search_projects()
            if projects.success:
                projects_by_id = {p.id: p for p in projects.result or []}

            result: list[WorkItemType] = []
            for item in response:
                scope_project: Project | None = None
                if (scope := item.get('scope', {})) and scope.get('type').lower() == 'project':
                    scope_project = projects_by_id.get(str(scope.get('project').get('id')))

                result.append(
                    WorkItemType(
                        id=str(item.get('id')),
                        name=str(item.get('name', '')),
                        scope_project=scope_project,
                    )
                )
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
            response: list[dict] = await self.api.user_search(query=f'{email_or_name}')
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

        users: list[JiraUser] = []
        for user in response:
            email = user.get('emailAddress')
            if self.skip_users_without_email and not email:
                continue
            users.append(
                JiraUser(
                    email=email,
                    account_id=str(user.get('accountId', '')),
                    active=bool(user.get('active', True)),
                    display_name=str(user.get('displayName', '')),
                )
            )
        return APIControllerResponse(result=users)

    async def search_users_assignable_to_work_item(
        self,
        work_item_key: str,
        query: str | None = None,
        active: bool | None = True,
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

        if not query and project_key:
            cached_users = self.cache.get('project_users', project_key)
            if cached_users:
                return APIControllerResponse(result=cached_users)

        try:
            response: list[dict] = await self.api.user_assignable_search(
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

        if active is not None:
            response = [item for item in response if item.get('active') == active]

        users: list[JiraUser] = []
        for user in response:
            email = user.get('emailAddress')
            if self.skip_users_without_email and not email:
                continue
            users.append(
                JiraUser(
                    email=email,
                    account_id=str(user.get('accountId', '')),
                    active=bool(user.get('active', True)),
                    display_name=str(user.get('displayName', '')),
                )
            )

        sorted_users = sorted(users, key=lambda item: item.display_name or item.account_id)

        if not query and project_key:
            self.cache.set('project_users', sorted_users, project_key)

        return APIControllerResponse(result=sorted_users)

    async def search_users_assignable_to_projects(
        self,
        project_keys: list[str],
        query: str | None = None,
        active: bool | None = True,
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

        if not query and len(project_keys) == 1:
            cached_users = self.cache.get('project_users', project_keys[0])
            if cached_users is not None:
                return APIControllerResponse(result=cached_users)

        try:
            response: list[dict] = await self.api.user_assignable_multi_projects(
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

        if active is not None:
            response = [item for item in response if item.get('active') == active]

        users: list[JiraUser] = []
        for user in response:
            email = user.get('emailAddress')
            if self.skip_users_without_email and not email:
                continue
            users.append(
                JiraUser(
                    email=email,
                    account_id=str(user.get('accountId', '')),
                    active=bool(user.get('active', True)),
                    display_name=str(user.get('displayName', '')),
                )
            )

        sorted_users = sorted(users, key=lambda item: item.display_name or item.account_id)

        if not query and len(project_keys) == 1:
            self.cache.set('project_users', sorted_users, project_keys[0])

        return APIControllerResponse(result=sorted_users)

    async def get_work_item(
        self,
        work_item_id_or_key: str,
        fields: list[str] | None = None,
        properties: str | None = None,
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

        fields_strings: str | None = ','.join(fields) if fields else None
        try:
            work_item: dict = await self.api.get_work_item(
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
                instance: JiraWorkItem = WorkItemFactory.new_work_item(work_item)
            except Exception as e:
                self.logger.error(
                    'There was an error while extracting data from a work item',
                    extra={'error': str(e), 'work_item_id_or_key': work_item_id_or_key},
                )
                return APIControllerResponse(
                    success=False,
                    error=f'Failed to extract the details of the requested work item {work_item_id_or_key}: {str(e)}',
                )
            return APIControllerResponse(result=JiraWorkItemSearchResponse(work_items=[instance]))

    def _build_criteria_for_searching_work_items(
        self,
        project_key: str | None = None,
        created_from: date | None = None,
        created_until: date | None = None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        jql_query: str | None = None,
    ) -> dict:
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
                if filter_data.get('label') == filter_label and (
                    expression := filter_data.get('expression')
                ):
                    if (
                        cleaned_expression := expression.replace('\n', ' ').replace('\t', ' ')
                    ) and (jql_expression := cleaned_expression.strip()):
                        return {'jql': jql_expression, 'updated_from': None}

        return {}

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
            response: dict = await self.api.parse_jql_query(jql_query=jql_query.strip())

            if 'queries' in response and len(response['queries']) > 0:
                query_result = response['queries'][0]

                if 'errors' in query_result and query_result['errors']:
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
            self.logger.warning(f'JQL validation failed with error: {str(e)}')
            return APIControllerResponse(
                success=False, error=f'Failed to validate JQL query: {str(e)}'
            )

    async def search_work_items(
        self,
        project_key: str | None = None,
        created_from: date | None = None,
        created_until: date | None = None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        search_in_active_sprint: bool = False,
        jql_query: str | None = None,
        next_page_token: str | None = None,
        limit: int | None = None,
        fields: list[str] | None = None,
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
        criteria: dict = self._build_criteria_for_searching_work_items(
            project_key=project_key,
            created_from=created_from,
            created_until=created_until,
            status=status,
            assignee=assignee,
            work_item_type=work_item_type,
            jql_query=jql_query,
        )

        if jql_from_criteria := criteria.get('jql'):
            validation_result = await self.validate_jql_query(jql_from_criteria)
            if not validation_result.success:
                self.logger.warning(f'JQL validation failed: {validation_result.error}')
                return APIControllerResponse(success=False, error=validation_result.error)

        try:
            response: dict = await self.api.search_work_items(
                project_key=project_key,
                created_from=created_from,
                created_until=created_until,
                updated_from=criteria.get('updated_from'),
                status=status,
                assignee=assignee,
                work_item_type=work_item_type,
                search_in_active_sprint=search_in_active_sprint,
                jql_query=criteria.get('jql'),
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
                error=f'There was an unknown error while searching for work items: {str(e)}',
            )
        work_items: list[JiraWorkItem] = []
        work_item: JiraWorkItem
        for work_item in response.get('issues', []):
            try:
                work_item = WorkItemFactory.new_work_item(work_item)
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
        project_key: str | None = None,
        created_from: date | None = None,
        created_until: date | None = None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        jql_query: str | None = None,
    ) -> APIControllerResponse:
        """Estimates the number of work items yield by a search.

        Args:
            project_key: the case-sensitive key of the project whose work items we want to search.
            created_from: search work items created from this date forward (inclusive).
            created_until: search work items created until this date (inclusive).
            status: search work items with this status.
            assignee: search work items assigned to this user's account ID.
            work_item_type: search work items of this type.
            jql_query: search work items using this (additional) JQL query.

        Returns:
            An instance of `APIControllerResponse` with the count of work items or, en error if the estimation can not
            be calculated.
        """

        criteria: dict = self._build_criteria_for_searching_work_items(
            project_key=project_key,
            created_from=created_from,
            created_until=created_until,
            status=status,
            assignee=assignee,
            work_item_type=work_item_type,
            jql_query=jql_query,
        )

        if jql_from_criteria := criteria.get('jql'):
            validation_result = await self.validate_jql_query(jql_from_criteria)
            if not validation_result.success:
                self.logger.warning(f'JQL validation failed: {validation_result.error}')
                return APIControllerResponse(success=False, error=validation_result.error)

        try:
            response: dict = await self.api.work_items_search_approximate_count(
                project_key=project_key,
                created_from=created_from,
                created_until=created_until,
                updated_from=criteria.get('updated_from'),
                status=status,
                assignee=assignee,
                work_item_type=work_item_type,
                jql_query=criteria.get('jql'),
            )
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

        try:
            response: list[dict] = await self.api.get_work_item_remote_links(
                work_item_key_or_id, global_id
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve the web links of a work item',
                extra={
                    'work_item_id_or_key': work_item_key_or_id,
                    'global_id': global_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        return APIControllerResponse(
            result=[
                WorkItemRemoteLink(
                    id=str(item.get('id')),
                    global_id=str(item.get('globalId', '')),
                    relationship=str(item.get('relationship', '')),
                    title=item.get('object', {}).get('title'),
                    summary=item.get('object', {}).get('summary'),
                    url=item.get('object', {}).get('url'),
                    status_resolved=item.get('object', {}).get('status', {}).get('resolved'),
                )
                for item in response
            ]
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
        try:
            await self.api.create_work_item_remote_link(work_item_key_or_id, url, title)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to create the web link',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'web_url': url,
                    'title': title,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse()

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
        try:
            await self.api.delete_work_item_remote_link(work_item_key_or_id, link_id)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to delete web link',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'link_id': link_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse()

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
        try:
            await self.api.update_work_item_remote_link(work_item_key_or_id, link_id, url, title)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to update web link',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'link_id': link_id,
                    'url': url,
                    'title': title,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse()

    async def global_settings(self) -> APIControllerResponse:
        """Retrieves the global settings of the Jira instance.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the details or,
            `APIControllerResponse(success=False)` if there is an error fetching the details.
        """
        try:
            response: dict = await self.api.global_settings()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve information of the Jira server',
                extra=exception_details.get('extra'),
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        time_tracking_configuration = None
        if values := response.get('timeTrackingConfiguration'):
            time_tracking_configuration = JiraTimeTrackingConfiguration(
                default_unit=values.get('defaultUnit'),
                time_format=values.get('timeFormat'),
                working_days_per_week=values.get('workingDaysPerWeek'),
                working_hours_per_day=values.get('workingHoursPerDay'),
            )

        return APIControllerResponse(
            result=JiraGlobalSettings(
                attachments_enabled=bool(response.get('attachmentsEnabled', False)),
                work_item_linking_enabled=bool(response.get('issueLinkingEnabled', False)),
                subtasks_enabled=bool(response.get('subTasksEnabled', False)),
                unassigned_work_items_allowed=bool(response.get('unassignedIssuesAllowed', False)),
                voting_enabled=bool(response.get('votingEnabled', False)),
                watching_enabled=bool(response.get('watchingEnabled', False)),
                time_tracking_enabled=bool(response.get('timeTrackingEnabled', False)),
                time_tracking_configuration=time_tracking_configuration,
            )
        )

    async def server_info(self) -> APIControllerResponse:
        """Retrieves details of the Jira server instance.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the details or,
            `APIControllerResponse(success=False)` if there is an error fetching the details.
        """
        try:
            response: dict = await self.api.server_info()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve information of the Jira server',
                extra=exception_details.get('extra'),
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse(
            result=JiraServerInfo(
                base_url=str(response.get('baseUrl', '')),
                display_url_servicedesk_help_center=response.get('displayUrlServicedeskHelpCenter'),
                display_url_confluence=response.get('displayUrlConfluence'),
                version=str(response.get('version', '')),
                deployment_type=response.get('deploymentType'),
                build_number=int(response.get('buildNumber', 0)),
                build_date=str(response.get('buildDate', '')),
                server_time=response.get('serverTime'),
                server_title=str(response.get('serverTitle', '')),
                default_locale=response.get('defaultLocale', {}).get('locale'),
                server_time_zone=response.get('serverTimeZone'),
            )
        )

    async def myself(self) -> APIControllerResponse:
        """Retrieves details of the Jira user connecting to the API.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the details or,
            `APIControllerResponse(success=False)` if there is an error fetching the details.
        """
        try:
            response: dict = await self.api.myself()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse(
            result=JiraMyselfInfo(
                account_id=str(response.get('accountId', '')),
                account_type=str(response.get('accountType', '')),
                active=bool(response.get('active', False)),
                display_name=str(response.get('displayName', '')),
                email=response.get('emailAddress'),
                groups=[
                    JiraUserGroup(id=g.get('id'), name=g.get('name'))
                    for g in response.get('groups', {}).get('items', [])
                ],
            )
        )

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

        if JiraWorkItemGenericFields.SUMMARY.value in updates:
            if (
                not (summary := updates.get(JiraWorkItemGenericFields.SUMMARY.value))
                or not summary.strip()
            ):
                raise ValidationError('The summary field can not be empty.')

        fields_to_update: dict[str, list] = {}

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
                fields_to_update[JiraWorkItemGenericFields.PARENT.value] = [
                    {'set': {'key': updates.get(JiraWorkItemGenericFields.PARENT.value)}}
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
                fields_to_update[meta_assignee.get('key')] = [
                    {'set': {'accountId': updates.get('assignee_account_id')}}
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
                    from gojeera.utils.adf_helpers import text_to_adf

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

        if fields_to_update:
            response: dict = await self.api.update_work_item(work_item.key, fields_to_update)
            updated_fields: list[str] = []
            if fields := response.get('fields', {}):
                updated_fields = list(fields.keys())
            return APIControllerResponse(
                result=UpdateWorkItemResponse(success=True, updated_fields=updated_fields)
            )
        return APIControllerResponse(result=UpdateWorkItemResponse(success=True))

    async def transitions(self, work_item_id_or_key: str) -> APIControllerResponse:
        """Retrieves the applicable (status) transitions of a work item.

        Args:
            work_item_id_or_key: the (case-sensitive) key of the work item.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the list of `IssueTransition` instances or,
            `APIControllerResponse(success=False)` if there is an error fetching the data.
        """
        try:
            response: dict = await self.api.transitions(work_item_id_or_key)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to retrieve status transitions for the work item',
                extra={
                    'work_item_id_or_key': work_item_id_or_key,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        transitions: list[WorkItemTransition] = []
        for transition in response.get('transitions', []):
            if to_state := transition.get('to', {}):
                status_category = to_state.get('statusCategory', {})
                color_name = status_category.get('colorName') if status_category else None

                transitions.append(
                    WorkItemTransition(
                        id=str(transition.get('id')),
                        name=transition.get('name'),
                        to_state=WorkItemTransitionState(
                            id=str(to_state.get('id')),
                            name=to_state.get('name'),
                            description=to_state.get('description'),
                            status_category_color=color_name,
                        ),
                    )
                )
        return APIControllerResponse(result=transitions)

    async def transition_work_item_status(
        self, work_item_id_or_key: str, status_id: str
    ) -> APIControllerResponse:
        """Transitions a work item to a new status.

        Args:
            work_item_id_or_key: the (case-sensitive) key of the work item.
            status_id: the ID of the new status.

        Returns:
            An instance of `APIControllerResponse(success=True)` if the work item was transitioned;
            `APIControllerResponse(success=False)` if there is an error.
        """
        response: APIControllerResponse = await self.transitions(work_item_id_or_key)
        if not response.success or not response.result:
            return APIControllerResponse(
                success=False,
                error=f'Unable to find valid status transitions for the selected item: {response.error}',
            )

        transition_id: str | None = None
        for transition in response.result:
            if transition.to_state.id == status_id:
                transition_id = transition.id
                break

        if transition_id is None:
            return APIControllerResponse(
                success=False, error='Unable to find a valid transition for the given status ID.'
            )

        try:
            await self.api.transition_work_item(work_item_id_or_key, transition_id)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to update the status of the work item',
                extra={
                    'work_item_id_or_key': work_item_id_or_key,
                    'status_id': status_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
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
        try:
            comment: dict = await self.api.get_comment(work_item_key_or_id, comment_id)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to fetch the comment',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'comment_id': comment_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        author = comment.get('author', {})
        update_author = comment.get('updateAuthor')
        return APIControllerResponse(
            result=WorkItemComment(
                id=str(comment.get('id', '')),
                author=JiraUser(
                    account_id=author.get('accountId'),
                    display_name=author.get('displayName'),
                    active=author.get('active'),
                    email=author.get('emailAddress'),
                ),
                created=isoparse(comment.get('created')),
                updated=isoparse(comment.get('updated')),
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
        try:
            response: dict = await self.api.get_comments(work_item_key_or_id, offset, limit)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to fetch comments',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        comments: list[WorkItemComment] = []
        for record in response.get('comments', []):
            author = record.get('author', {})
            update_author = record.get('updateAuthor')
            comments.append(
                WorkItemComment(
                    id=record.get('id'),
                    created=isoparse(record.get('created')) if record.get('created') else None,
                    updated=isoparse(record.get('updated')) if record.get('updated') else None,
                    author=JiraUser(
                        account_id=author.get('accountId'),
                        active=author.get('active'),
                        display_name=author.get('displayName'),
                        email=author.get('emailAddress'),
                    ),
                    update_author=JiraUser(
                        account_id=update_author.get('accountId'),
                        active=update_author.get('active'),
                        display_name=update_author.get('displayName'),
                        email=update_author.get('emailAddress'),
                    )
                    if update_author
                    else None,
                    body=record.get('body'),
                )
            )
        return APIControllerResponse(result=comments)

    async def add_comment(self, work_item_key_or_id: str, message: str) -> APIControllerResponse:
        """Adds a comment to a work item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            message: the text of the comment.

        Returns:
            An instance of `APIControllerResponse` with the result of the operation.
        """
        if not message:
            return APIControllerResponse(success=False, error='Missing required message.')
        try:
            response = await self.api.add_comment(work_item_key_or_id, message)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to create the comment',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        author = response.get('author', {})
        update_author = response.get('updateAuthor')
        comment = WorkItemComment(
            id=str(response.get('id', '')),
            created=isoparse(response.get('created')) if response.get('created') else None,
            updated=isoparse(response.get('updated')) if response.get('updated') else None,
            author=JiraUser(
                account_id=author.get('accountId'),
                active=author.get('active'),
                display_name=author.get('displayName'),
                email=author.get('emailAddress'),
            ),
            update_author=JiraUser(
                account_id=update_author.get('accountId'),
                active=update_author.get('active'),
                display_name=update_author.get('displayName'),
                email=update_author.get('emailAddress'),
            )
            if update_author
            else None,
            body=response.get('body'),
        )
        return APIControllerResponse(result=comment)

    async def update_comment(
        self, work_item_key_or_id: str, comment_id: str, message: str
    ) -> APIControllerResponse:
        """Updates a comment on a work item.

        Args:
            work_item_key_or_id: the case-sensitive key or id of a work item.
            comment_id: the id of the comment to update.
            message: the new text of the comment in markdown format.

        Returns:
            An instance of `APIControllerResponse` with the result of the operation.
        """
        if not message:
            return APIControllerResponse(success=False, error='Missing required message.')
        try:
            response = await self.api.update_comment(work_item_key_or_id, comment_id, message)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to update the comment',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'comment_id': comment_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        author = response.get('author', {})
        update_author = response.get('updateAuthor')
        comment = WorkItemComment(
            id=str(response.get('id', '')),
            created=isoparse(response.get('created')) if response.get('created') else None,
            updated=isoparse(response.get('updated')) if response.get('updated') else None,
            author=JiraUser(
                account_id=author.get('accountId'),
                active=author.get('active'),
                display_name=author.get('displayName'),
                email=author.get('emailAddress'),
            ),
            update_author=JiraUser(
                account_id=update_author.get('accountId'),
                active=update_author.get('active'),
                display_name=update_author.get('displayName'),
                email=update_author.get('emailAddress'),
            )
            if update_author
            else None,
            body=response.get('body'),
        )
        return APIControllerResponse(result=comment)

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
        try:
            await self.api.delete_comment(work_item_key_or_id, comment_id)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to delete the comment',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'comment_id': comment_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse()

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
        try:
            await self.api.create_work_item_link(
                left_work_item_key=left_work_item_key,
                right_work_item_key=right_work_item_key,
                link_type=link_type,
                link_type_id=link_type_id,
            )
            return APIControllerResponse()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to link items',
                extra={
                    'left_work_item_key': left_work_item_key,
                    'link_type': link_type,
                    'link_type_id': link_type_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

    async def delete_work_item_link(self, link_id: str) -> APIControllerResponse:
        """Deletes the link between 2 work items.

        Args:
            link_id: the ID of the link to delete.

        Returns:
            An instance of `APIControllerResponse(success=True)` if the work items were unlinked successfully;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            await self.api.delete_work_item_link(link_id)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to delete link between items',
                extra={
                    'link_id': link_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse()

    async def work_item_link_types(self) -> APIControllerResponse:
        """Retrieves the types of links that can be created between 2 work items.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the list of `LinkIssueType` instances;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            response: dict = await self.api.work_item_link_types()
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

            if hasattr(work_item, 'versions') and work_item.versions:
                fields_to_clone['versions'] = [
                    {'id': v.id}
                    for v in work_item.versions  # type: ignore[attr-defined]
                ]

            if hasattr(work_item, 'fix_versions') and work_item.fix_versions:
                fields_to_clone['fixVersions'] = [
                    {'id': v.id}
                    for v in work_item.fix_versions  # type: ignore[attr-defined]
                ]

            if work_item.assignee and work_item.assignee.account_id:
                fields_to_clone['assignee'] = {'accountId': work_item.assignee.account_id}

            if (
                work_item.parent_key
                and work_item.work_item_type
                and work_item.work_item_type.hierarchy_level != 0
            ):
                fields_to_clone['parent'] = {'key': work_item.parent_key}

            create_meta_response = await self.api.get_work_item_create_meta(
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

            if not isinstance(fields_to_clone, dict):
                raise TypeError(
                    f'fields_to_clone must be a dict, got {type(fields_to_clone).__name__}'
                )

            cloned_item = await self.api.clone_work_item(
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
    ) -> APIControllerResponse:
        """Retrieves the metadata relevant for creating work items of a project and of a certain type.

        Args:
            project_id_or_key: the (case-sensitive) key of the project.
            work_item_type_id: the ID of the type of work item.

        Returns:
            An instance of `APIControllerResponse(success=True)` with the metadata;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            response = await self.api.get_work_item_create_meta(
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

    async def new_work_item(self, data: dict, **dynamic_fields) -> APIControllerResponse:
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
        available_fields: set[str] = set()

        if project_key and work_item_type_id:
            metadata_response = await self.get_work_item_create_metadata(
                project_key, work_item_type_id
            )
            if metadata_response.success and metadata_response.result:
                metadata_fields = metadata_response.result.get('fields', [])
                available_fields = {
                    field.get('key') for field in metadata_fields if field.get('key')
                }

        if assignee_account_id := data.get('assignee_account_id'):
            fields['assignee'] = {'id': assignee_account_id}

        if reporter_account_id := data.get('reporter_account_id'):
            if not available_fields or 'reporter' in available_fields:
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

        if description := data.get('description'):
            from gojeera.utils.adf_helpers import text_to_adf

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
            result: dict = await self.api.new_work_item(fields)
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)

            error_message = exception_details.get('message', str(e))

            if 'cannot be set' in str(e).lower() or (
                exception_details.get('extra', {}).get('errors')
                and any(
                    'cannot be set' in str(err).lower()
                    for err in exception_details.get('extra', {}).get('errors', {}).values()
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
            response: list[dict] = self.api.add_attachment_to_work_item(
                work_item_key_or_id, filename, name, mime_type
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to attach files',
                extra={
                    'work_item_key_or_id': work_item_key_or_id,
                    'filename': filename,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        else:
            creator = None
            if author := response[0].get('author'):
                creator = JiraUser(
                    account_id=author.get('accountId'),
                    active=author.get('active'),
                    display_name=author.get('displayName'),
                    email=author.get('emailAddress'),
                )
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
            await self.api.delete_attachment(attachment_id)
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
            content: bytes = await self.api.get_attachment_content(attachment_id)
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
            response: dict = await self.api.get_work_item_work_log(
                work_item_key_or_id, offset, limit
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to to retrieve the worklog', extra=exception_details.get('extra')
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        logs: list[JiraWorklog] = []
        for work_log in response.get('worklogs', []):
            update_author = None
            if value := work_log.get('updateAuthor'):
                update_author = JiraUser(
                    account_id=value.get('accountId'),
                    display_name=value.get('displayName'),
                    active=value.get('active'),
                    email=value.get('emailAddress'),
                )
            author = None
            if value := work_log.get('author'):
                author = JiraUser(
                    account_id=value.get('accountId'),
                    display_name=value.get('displayName'),
                    active=value.get('active'),
                    email=value.get('emailAddress'),
                )

            logs.append(
                JiraWorklog(
                    id=work_log.get('id'),
                    work_item_id=work_log.get('issueId'),
                    started=isoparse(work_log.get('started')) if work_log.get('started') else None,
                    updated=isoparse(work_log.get('updated')) if work_log.get('updated') else None,
                    time_spent=work_log.get('timeSpent'),
                    time_spent_seconds=work_log.get('timeSpentSeconds'),
                    author=author,
                    update_author=update_author,
                    comment=work_log.get('comment'),
                )
            )

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

        remaining_time = None
        if time_remaining:
            if not current_remaining_estimate or time_remaining != current_remaining_estimate:
                remaining_time = time_remaining

        try:
            response: dict = await self.api.add_work_item_work_log(
                work_item_id_or_key=work_item_key_or_id,
                started=started,
                time_spent=time_spent,
                time_remaining=remaining_time,
                comment=comment,
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to add worklog',
                extra={
                    'time_spent': time_spent,
                    'time_remaining': time_remaining,
                    'current_remaining_estimate': current_remaining_estimate,
                    'started': str(started) if started else None,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        update_author = None
        if value := response.get('updateAuthor'):
            update_author = JiraUser(
                account_id=value.get('accountId'),
                display_name=value.get('displayName'),
                active=value.get('active'),
                email=value.get('emailAddress'),
            )
        author = None
        if value := response.get('author'):
            author = JiraUser(
                account_id=value.get('accountId'),
                display_name=value.get('displayName'),
                active=value.get('active'),
                email=value.get('emailAddress'),
            )

        return APIControllerResponse(
            result=JiraWorklog(
                id=str(response.get('id', '')),
                work_item_id=str(response.get('issueId', '')),
                started=isoparse(response.get('started')) if response.get('started') else None,
                updated=isoparse(response.get('updated')) if response.get('updated') else None,
                time_spent=response.get('timeSpent'),
                time_spent_seconds=response.get('timeSpentSeconds'),
                author=author,
                update_author=update_author,
                comment=response.get('comment'),
            )
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

        remaining_time = None
        if time_remaining:
            if not current_remaining_estimate or time_remaining != current_remaining_estimate:
                remaining_time = time_remaining

        try:
            response: dict = await self.api.update_work_log(
                work_item_id_or_key=work_item_key_or_id,
                worklog_id=worklog_id,
                started=started,
                time_spent=time_spent,
                time_remaining=remaining_time,
                comment=comment,
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to update worklog',
                extra={
                    'worklog_id': worklog_id,
                    'time_spent': time_spent,
                    'time_remaining': time_remaining,
                    'current_remaining_estimate': current_remaining_estimate,
                    'started': str(started) if started else None,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))

        update_author = None
        if value := response.get('updateAuthor'):
            update_author = JiraUser(
                account_id=value.get('accountId'),
                display_name=value.get('displayName'),
                active=value.get('active'),
                email=value.get('emailAddress'),
            )
        author = None
        if value := response.get('author'):
            author = JiraUser(
                account_id=value.get('accountId'),
                display_name=value.get('displayName'),
                active=value.get('active'),
                email=value.get('emailAddress'),
            )

        return APIControllerResponse(
            result=JiraWorklog(
                id=str(response.get('id', '')),
                work_item_id=str(response.get('issueId', '')),
                started=isoparse(response.get('started')) if response.get('started') else None,
                updated=isoparse(response.get('updated')) if response.get('updated') else None,
                time_spent=response.get('timeSpent'),
                time_spent_seconds=response.get('timeSpentSeconds'),
                author=author,
                update_author=update_author,
                comment=response.get('comment'),
            )
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
        try:
            await self.api.delete_work_log(
                work_item_id_or_key=work_item_id_or_key, worklog_id=worklog_id
            )
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                'Unable to delete worklog',
                extra={
                    'worklog_id': worklog_id,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        return APIControllerResponse()

    async def get_fields(self, field_name: str | None = None) -> APIControllerResponse:
        """Retrieves system and custom work item fields.

        Returns:
            `APIControllerResponse(success=True, result=fields)` if the operation was successful;
            `APIControllerResponse(success=False)` if there is an error.
        """
        try:
            response = await self.api.get_fields()
        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error('Unable to fetch fields', extra=exception_details.get('extra'))
            return APIControllerResponse(success=False, error=exception_details.get('message'))
        fields: list[JiraField] = []
        for field in response:
            if field_name and str(field.get('name', '')).lower() != field_name.lower():
                continue
            fields.append(
                JiraField(
                    id=field.get('id', ''),
                    key=field.get('key', ''),
                    name=str(field.get('name', '')),
                    schema=field.get('schema', {}),
                )
            )
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
            response: Any | None = await self.api.get_label_suggestions(query=query)
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

    async def get_sprints_for_project(self, project_key: str) -> APIControllerResponse:
        """Get active and future sprints for a project with caching.

        Args:
            project_key: The project key

        Returns:
            An instance of `APIControllerResponse` with a list of JiraSprint models and `success = True`.
            If an error occurs then `success = False` and the error message in the `error` key.
        """
        cached_sprints = self.cache.get('sprints', project_key)
        if cached_sprints is not None:
            return APIControllerResponse(result=cached_sprints)

        try:
            sprints_data = await self.api.get_sprints_for_project(
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

            self.cache.set('sprints', sprints, project_key)

            return APIControllerResponse(result=sprints)

        except Exception as e:
            exception_details: dict = self._extract_exception_details(e)
            self.logger.error(
                f'Failed to fetch sprints for project {project_key}',
                extra={
                    'project_key': project_key,
                    **exception_details.get('extra', {}),
                },
            )
            return APIControllerResponse(success=False, error=exception_details.get('message'))
