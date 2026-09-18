import asyncio
from io import BytesIO
import logging
import sys
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import httpx

from gojeera.internal.jira.api import JiraAPI
import gojeera.internal.jira.controller as controller_module
from gojeera.internal.jira.controller import (
    DEFERRED_WORK_ITEM_FIELDS,
    INITIAL_WORK_ITEM_FIELDS,
    TRANSIENT_PROJECT_CACHE_MAX_ENTRIES,
    APIController,
    APIControllerResponse,
)
from gojeera.internal.jira.factories import WorkItemFactory, build_comments
from gojeera.internal.models.jira import JiraField, JiraProject, WorkItemType, WorkItemWatchers
from gojeera.internal.models.work_items import WorkItemComment
from tests.jira_api_test_utils import build_api_with_mocked_client

COMMENT_AUTHOR_RESPONSE = {
    'accountId': 'user-1',
    'active': True,
    'displayName': 'User One',
}
ENGINEERING_SCRUM_BOARD = {
    'id': 7,
    'name': 'Engineering Scrum',
    'type': 'scrum',
    'location': {'projectKey': 'ENG'},
}


def _concurrent_request_gate(expected_requests: int = 2):
    started: set[str] = set()
    all_started = asyncio.Event()
    release_requests = asyncio.Event()

    async def wait_for_peer(name: str, result: Any) -> Any:
        started.add(name)
        if len(started) == expected_requests:
            all_started.set()
        await release_requests.wait()
        return result

    return started, all_started, release_requests, wait_for_peer


def test_attachment_mime_detection_imports_magic_on_first_use(monkeypatch) -> None:
    from_buffer = Mock(return_value='text/plain')
    monkeypatch.setitem(sys.modules, 'magic', SimpleNamespace(from_buffer=from_buffer))
    file_to_upload = BytesIO(b'plain text attachment')

    result = JiraAPI._detect_file_mime_type(file_to_upload)

    assert result == 'text/plain'
    from_buffer.assert_called_once_with(b'plain text attachment', mime=True)


def test_transient_project_cache_is_ttl_aware_and_lru_bounded():
    cache = {}
    future_expiry = controller_module.monotonic() + 60

    for index in range(TRANSIENT_PROJECT_CACHE_MAX_ENTRIES + 1):
        APIController._set_transient_cache_entry(
            cache,
            f'project-{index}',
            (future_expiry, index),
        )

    assert len(cache) == TRANSIENT_PROJECT_CACHE_MAX_ENTRIES
    assert 'project-0' not in cache

    assert APIController._get_transient_cache_entry(cache, 'project-1') is not None
    APIController._set_transient_cache_entry(
        cache,
        'new-project',
        (future_expiry, 'new'),
    )

    assert 'project-1' in cache
    assert 'project-2' not in cache

    APIController._set_transient_cache_entry(cache, 'expired', (0, 'expired'))
    assert APIController._get_transient_cache_entry(cache, 'expired') is None


MISSING_ADD_COMMENTS_PERMISSION_RESPONSE = {
    'permissions': {
        'BROWSE_PROJECTS': {'havePermission': True},
        'ADD_COMMENTS': {'havePermission': False},
    }
}


def _work_item_response(summary: str, fields: dict | None = None) -> dict:
    return {
        'id': '10001',
        'key': 'ENG-1',
        'fields': {
            'summary': summary,
            'status': {'id': '1', 'name': 'Open'},
            'issuetype': {'id': '10001', 'name': 'Task'},
            **(fields or {}),
        },
    }


def _build_controller_for_full_work_item_load(
    *,
    flagged: bool,
    summary: str,
    fields: dict | None = None,
) -> APIController:
    controller = APIController.__new__(APIController)
    controller.client = AsyncMock()
    controller.logger = logging.getLogger('gojeera')
    controller.get_fields = AsyncMock()
    controller.get_work_item_flagged_state = AsyncMock(
        return_value=APIControllerResponse(result=flagged)
    )
    controller.client.get_work_item = AsyncMock(return_value=_work_item_response(summary, fields))
    return controller


def _build_controller_for_flag_update() -> APIController:
    controller = APIController.__new__(APIController)
    controller.client = AsyncMock()
    controller.logger = logging.getLogger('gojeera')
    controller.get_fields = AsyncMock(
        return_value=APIControllerResponse(
            result=[
                JiraField(
                    id='customfield_10021',
                    key='customfield_10021',
                    name='Flagged',
                    schema={},
                )
            ]
        )
    )
    controller.client.update_work_item = AsyncMock(return_value=_work_item_response('Flag me'))
    return controller


def _assert_full_work_item_loaded_with_default_fields(controller: APIController) -> None:
    get_fields = cast(AsyncMock, controller.get_fields)
    get_work_item = cast(AsyncMock, controller.client.get_work_item)
    get_fields.assert_not_awaited()
    get_work_item.assert_awaited_once_with(
        work_item_id_or_key='ENG-1',
        fields='*all,watches',
        properties=None,
    )


def test_initial_work_item_fields_exclude_lazily_loaded_details() -> None:
    assert DEFERRED_WORK_ITEM_FIELDS == {'comment', 'subtasks'}
    assert INITIAL_WORK_ITEM_FIELDS == ['*all', '-comment', '-subtasks', 'watches']


async def test_initial_work_item_load_preserves_unlisted_field_values() -> None:
    controller = _build_controller_for_full_work_item_load(
        flagged=False,
        summary='All fields',
        fields={
            'environment': 'production',
            'customfield_non_editable': {'value': 'retained'},
        },
    )

    response = await controller.get_work_item('ENG-1', fields=INITIAL_WORK_ITEM_FIELDS)

    assert response.success
    assert response.result is not None
    work_item = response.result.work_items[0]
    assert work_item.additional_fields == {'environment': 'production'}
    assert work_item.custom_fields == {'customfield_non_editable': {'value': 'retained'}}
    cast(AsyncMock, controller.client.get_work_item).assert_awaited_once_with(
        work_item_id_or_key='ENG-1',
        fields='*all,-comment,-subtasks,watches',
        properties=None,
    )


def test_build_payload_to_add_comment_uses_normal_text_conversion():
    payload = JiraAPI._build_payload_to_add_comment('hello')

    assert payload == {
        'body': {
            'type': 'doc',
            'version': 1,
            'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'hello'}]}],
        }
    }


def test_build_payload_to_add_comment_does_not_include_jsd_public():
    payload = JiraAPI._build_payload_to_add_comment('hello')

    assert 'jsdPublic' not in payload


async def test_add_comment_with_jsd_public_uses_service_desk_request_comment_endpoint():
    api, make_request = build_api_with_mocked_client([{}])
    api._service_desk_client = api._client

    await api.add_comment('SUP-1', 'internal note', jsd_public=False)

    request_args = make_request.await_args
    assert request_args is not None
    assert request_args.kwargs['url'] == 'request/SUP-1/comment'
    assert request_args.kwargs['data'] == '{"body": "internal note", "public": false}'


async def test_get_my_permissions_uses_issue_context_and_permissions():
    api, make_request = build_api_with_mocked_client([{'permissions': {}}])

    await api.get_my_permissions(
        work_item_id_or_key='ENG-1',
        permissions=['BROWSE_PROJECTS', 'ADD_COMMENTS'],
    )

    request_args = make_request.await_args
    assert request_args is not None
    assert request_args.kwargs['method'] == httpx.AsyncClient.get
    assert request_args.kwargs['url'] == 'mypermissions'
    assert request_args.kwargs['params'] == {
        'issueKey': 'ENG-1',
        'permissions': 'BROWSE_PROJECTS,ADD_COMMENTS',
    }


async def test_get_work_item_watchers_uses_watchers_endpoint():
    api, make_request = build_api_with_mocked_client([{'watchers': []}])

    await api.get_work_item_watchers('ENG-1')

    request_args = make_request.await_args
    assert request_args is not None
    assert request_args.kwargs['method'] == httpx.AsyncClient.get
    assert request_args.kwargs['url'] == 'issue/ENG-1/watchers'


async def test_add_work_item_watcher_defaults_to_current_user():
    api, make_request = build_api_with_mocked_client([{}])

    await api.add_work_item_watcher('ENG-1')

    request_args = make_request.await_args
    assert request_args is not None
    assert request_args.kwargs['method'] == httpx.AsyncClient.post
    assert request_args.kwargs['url'] == 'issue/ENG-1/watchers'
    assert request_args.kwargs['data'] == '""'


async def test_remove_work_item_watcher_uses_account_id_query_param():
    api, make_request = build_api_with_mocked_client([{}])

    await api.remove_work_item_watcher('ENG-1', 'user-1')

    request_args = make_request.await_args
    assert request_args is not None
    assert request_args.kwargs['method'] == httpx.AsyncClient.delete
    assert request_args.kwargs['url'] == 'issue/ENG-1/watchers'
    assert request_args.kwargs['params'] == {'accountId': 'user-1'}


async def test_update_work_item_can_override_screen_security():
    api, make_request = build_api_with_mocked_client([{}])

    await api.update_work_item(
        'ENG-1',
        payload={'customfield_10021': [{'set': [{'value': 'Impediment'}]}]},
        override_screen_security=True,
    )

    request_args = make_request.await_args
    assert request_args is not None
    assert request_args.kwargs['method'] == httpx.AsyncClient.put
    assert request_args.kwargs['url'] == 'issue/ENG-1'
    assert request_args.kwargs['params'] == {
        'returnIssue': True,
        'overrideScreenSecurity': True,
    }


async def test_controller_get_work_item_watchers_builds_model():
    controller = APIController.__new__(APIController)
    controller.skip_users_without_email = False
    controller.client = AsyncMock()
    controller.client.get_work_item_watchers = AsyncMock(
        return_value={
            'isWatching': True,
            'watchCount': 1,
            'watchers': [
                {
                    'accountId': 'user-1',
                    'active': True,
                    'displayName': 'User One',
                }
            ],
        }
    )

    response = await controller.get_work_item_watchers('ENG-1')

    assert response.success
    assert isinstance(response.result, WorkItemWatchers)
    assert response.result.is_watching is True
    assert response.result.watch_count == 1
    assert response.result.watchers[0].display_name == 'User One'


async def test_controller_remove_work_item_watcher_delegates_to_client():
    controller = APIController.__new__(APIController)
    controller.client = AsyncMock()
    controller.client.remove_work_item_watcher = AsyncMock(return_value=None)

    response = await controller.remove_work_item_watcher('ENG-1', 'user-1')

    assert response.success
    controller.client.remove_work_item_watcher.assert_awaited_once_with('ENG-1', 'user-1')


async def test_controller_fetches_field_metadata_concurrently():
    both_started = asyncio.Event()
    release_requests = asyncio.Event()
    started_requests = 0

    async def wait_for_other_request(result):
        nonlocal started_requests
        started_requests += 1
        if started_requests == 2:
            both_started.set()
        await release_requests.wait()
        return result

    controller = APIController.__new__(APIController)
    controller.client = cast(
        Any,
        SimpleNamespace(
            get_fields=lambda: wait_for_other_request(
                [{'id': 'summary', 'key': 'summary', 'name': 'Summary', 'schema': {}}]
            ),
            get_all_fields_paginated=lambda **kwargs: wait_for_other_request(
                [{'id': 'summary', 'description': 'The work item summary'}]
            ),
        ),
    )
    controller.cache = cast(
        Any,
        SimpleNamespace(
            get_fields=lambda *, allow_stale=False: None,
            set_fields=lambda fields: None,
        ),
    )
    controller.logger = logging.getLogger('gojeera.test')

    response_task = asyncio.create_task(controller.get_fields())
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release_requests.set()
    response = await response_task

    assert response.success
    fields = cast(list[JiraField], response.result)
    assert fields[0].description == 'The work item summary'


async def test_controller_coalesces_matching_inflight_requests():
    started = asyncio.Event()
    release_request = asyncio.Event()
    operation_calls = 0

    async def operation() -> APIControllerResponse:
        nonlocal operation_calls
        operation_calls += 1
        started.set()
        await release_request.wait()
        return APIControllerResponse(result=['shared'])

    controller = APIController.__new__(APIController)
    first = asyncio.create_task(controller._coalesce_request(('fields',), operation))
    await asyncio.wait_for(started.wait(), timeout=1)
    second = asyncio.create_task(controller._coalesce_request(('fields',), operation))
    await asyncio.sleep(0)
    release_request.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert operation_calls == 1
    assert first_result is second_result
    assert controller._inflight_requests == {}


async def test_get_work_item_coalesces_matching_inflight_requests():
    started = asyncio.Event()
    release_request = asyncio.Event()
    request_count = 0

    async def get_work_item(*, work_item_id_or_key: str, fields: str, properties=None):
        nonlocal request_count
        request_count += 1
        assert work_item_id_or_key == 'ENG-1'
        assert fields == 'summary,status,issuetype'
        assert properties is None
        started.set()
        await release_request.wait()
        return _work_item_response('Shared work item')

    controller = APIController.__new__(APIController)
    controller.client = cast(Any, SimpleNamespace(get_work_item=get_work_item))
    controller.logger = logging.getLogger('gojeera.test')

    first = asyncio.create_task(
        controller.get_work_item('ENG-1', fields=['summary', 'status', 'issuetype'])
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    second = asyncio.create_task(
        controller.get_work_item('ENG-1', fields=['summary', 'status', 'issuetype'])
    )
    await asyncio.sleep(0)
    release_request.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert request_count == 1
    assert first_result is second_result
    assert controller.get_cached_work_item_tooltip('ENG-1') == (
        'Task',
        'Shared work item',
        'Open',
    )


def test_work_item_tooltip_cache_is_bounded_and_expires(monkeypatch):
    current_time = 1000.0
    monkeypatch.setattr(controller_module, 'monotonic', lambda: current_time)
    controller = APIController.__new__(APIController)

    for index in range(controller_module.WORK_ITEM_TOOLTIP_CACHE_MAX_ENTRIES + 1):
        controller.cache_work_item_tooltip(
            f'ENG-{index}',
            'Task',
            f'Summary {index}',
            'Open',
        )

    assert controller.get_cached_work_item_tooltip('ENG-0') is None
    assert len(controller._work_item_tooltip_cache) == (
        controller_module.WORK_ITEM_TOOLTIP_CACHE_MAX_ENTRIES
    )

    current_time += controller_module.WORK_ITEM_TOOLTIP_CACHE_TTL_SECONDS + 1
    assert controller.get_cached_work_item_tooltip('ENG-1') is None


async def test_projects_with_releases_publish_progressively_and_reuse_cache():
    first_page_published = asyncio.Event()
    release_second_project = asyncio.Event()
    projects = [
        JiraProject(id='1', key='ENG', name='Engineering'),
        JiraProject(id='2', key='OPS', name='Operations'),
    ]
    release_requests: list[str] = []

    async def get_project_releases(project_key: str, **_kwargs):
        release_requests.append(project_key)
        if project_key == 'OPS':
            await release_second_project.wait()
        return APIControllerResponse(result=[object()])

    published_pages: list[list[str]] = []

    def publish_page(published_projects: list[JiraProject]) -> None:
        published_pages.append([project.key for project in published_projects])
        first_page_published.set()

    controller = APIController.__new__(APIController)
    controller.search_projects = AsyncMock(return_value=APIControllerResponse(result=projects))
    controller.get_project_releases = cast(Any, get_project_releases)

    response_task = asyncio.create_task(
        controller.search_projects_with_releases(on_page=publish_page)
    )
    await asyncio.wait_for(first_page_published.wait(), timeout=1)

    assert published_pages == [['ENG']]
    assert not response_task.done()

    release_second_project.set()
    response = await response_task

    assert response.success
    response_projects = cast(list[JiraProject], response.result)
    assert [project.key for project in response_projects] == ['ENG', 'OPS']
    assert published_pages == [['ENG'], ['ENG', 'OPS']]

    cached_pages: list[list[str]] = []
    cached_response = await controller.search_projects_with_releases(
        on_page=lambda cached_projects: cached_pages.append(
            [project.key for project in cached_projects]
        )
    )

    cached_projects = cast(list[JiraProject], cached_response.result)
    assert [project.key for project in cached_projects] == ['ENG', 'OPS']
    assert cached_pages == [['ENG', 'OPS']]
    assert release_requests.count('ENG') == 1
    assert release_requests.count('OPS') == 1


async def test_project_releases_publish_each_accumulated_page():
    responses = [
        {
            'values': [{'id': '1', 'name': 'First release'}],
            'isLast': False,
        },
        {
            'values': [{'id': '2', 'name': 'Second release'}],
            'isLast': True,
        },
    ]

    async def get_project_versions(*_args, **_kwargs):
        return responses.pop(0)

    published_pages = []
    controller = APIController.__new__(APIController)
    controller.client = cast(Any, SimpleNamespace(get_project_versions=get_project_versions))
    controller.logger = logging.getLogger('gojeera.test')

    response = await controller.get_project_releases(
        'ENG',
        on_page=lambda releases: published_pages.append([release.id for release in releases]),
    )

    assert response.success
    assert published_pages == [['1'], ['1', '2']]
    assert [release.id for release in cast(list, response.result)] == ['1', '2']

    cached_pages = []
    cached_response = await controller.get_project_releases(
        'ENG',
        on_page=lambda releases: cached_pages.append([release.id for release in releases]),
    )

    assert cached_response.success
    assert cached_pages == [['1', '2']]


async def test_concurrent_project_release_requests_share_pages_and_network_call():
    request_started = asyncio.Event()
    finish_request = asyncio.Event()
    request_count = 0

    async def get_project_versions(*_args, **_kwargs):
        nonlocal request_count
        request_count += 1
        request_started.set()
        await finish_request.wait()
        return {
            'values': [{'id': '1', 'name': 'First release'}],
            'isLast': True,
        }

    controller = APIController.__new__(APIController)
    controller.client = cast(Any, SimpleNamespace(get_project_versions=get_project_versions))
    controller.logger = logging.getLogger('gojeera.test')
    first_pages = []
    second_pages = []

    first_request = asyncio.create_task(
        controller.get_project_releases(
            'ENG',
            on_page=lambda releases: first_pages.append([release.id for release in releases]),
        )
    )
    await request_started.wait()
    second_request = asyncio.create_task(
        controller.get_project_releases(
            'ENG',
            on_page=lambda releases: second_pages.append([release.id for release in releases]),
        )
    )
    await asyncio.sleep(0)
    finish_request.set()

    first_response, second_response = await asyncio.gather(first_request, second_request)

    assert first_response.success
    assert second_response.success
    assert request_count == 1
    assert first_pages == [['1']]
    assert second_pages == [['1']]


async def test_stale_release_discovery_is_returned_while_refreshing_in_background():
    project = JiraProject(id='1', key='ENG', name='Engineering')

    class ReleaseDiscoveryCache:
        def get_projects_with_releases(self, *, allow_stale: bool = False):
            return [project] if allow_stale else None

    controller = APIController.__new__(APIController)
    controller.cache = cast(Any, ReleaseDiscoveryCache())
    controller._schedule_background_refresh = Mock()
    published_pages = []

    response = await controller.search_projects_with_releases(
        on_page=lambda projects: published_pages.append(projects)
    )

    assert response.success
    assert response.result == [project]
    assert published_pages == [[project]]
    controller._schedule_background_refresh.assert_called_once()


async def test_controller_serves_stale_cache_while_refreshing_in_background():
    refresh_started = asyncio.Event()
    release_refresh = asyncio.Event()

    def cache_getter(allow_stale: bool):
        return ['stale'] if allow_stale else None

    async def refresh() -> APIControllerResponse:
        refresh_started.set()
        await release_refresh.wait()
        return APIControllerResponse(result=['fresh'])

    controller = APIController.__new__(APIController)
    controller.logger = logging.getLogger('gojeera.test')

    response = await controller._cached_or_refresh(('fields',), cache_getter, refresh)

    assert response.success
    assert response.result == ['stale']
    await asyncio.wait_for(refresh_started.wait(), timeout=1)
    background_tasks = tuple(controller._background_refresh_tasks)
    release_refresh.set()
    await asyncio.gather(*background_tasks)

    assert controller._inflight_requests == {}


async def test_pull_request_work_item_keys_are_resolved_concurrently():
    started: set[str] = set()
    all_started = asyncio.Event()
    release_requests = asyncio.Event()

    async def get_work_item(*, work_item_id_or_key: str, fields: str) -> dict:
        assert fields == 'key'
        started.add(work_item_id_or_key)
        if len(started) == 3:
            all_started.set()
        await release_requests.wait()
        return {'key': f'ENG-{work_item_id_or_key}'}

    controller = APIController.__new__(APIController)
    pull_requests = [
        {'work_item_id': '1'},
        {'work_item_id': '2'},
        {'work_item_id': '3'},
    ]
    client = cast(Any, SimpleNamespace(get_work_item=get_work_item))

    request = asyncio.create_task(
        controller._populate_pull_request_work_item_keys(client, pull_requests)
    )
    await asyncio.wait_for(all_started.wait(), timeout=1)
    release_requests.set()
    await request

    assert started == {'1', '2', '3'}
    assert [item['work_item_key'] for item in pull_requests] == ['ENG-1', 'ENG-2', 'ENG-3']


async def test_controller_fetches_global_types_and_projects_concurrently():
    started, both_started, release_requests, wait_for_peer = _concurrent_request_gate()

    controller = APIController.__new__(APIController)
    controller.cache = cast(
        Any,
        SimpleNamespace(
            get_work_item_types=lambda *, allow_stale=False: None,
            set_work_item_types=Mock(),
        ),
    )
    controller.client = cast(
        Any,
        SimpleNamespace(
            get_work_items_types_for_user=lambda: wait_for_peer(
                'types',
                [
                    {
                        'id': '10001',
                        'name': 'Task',
                        'scope': {'type': 'PROJECT', 'project': {'id': '10'}},
                    }
                ],
            )
        ),
    )
    controller.search_projects = cast(
        Any,
        lambda: wait_for_peer(
            'projects',
            APIControllerResponse(result=[JiraProject(id='10', name='Engineering', key='ENG')]),
        ),
    )

    response_task = asyncio.create_task(controller.get_work_item_types())
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release_requests.set()
    response = await response_task

    assert started == {'types', 'projects'}
    assert response.success
    work_item_types = cast(list[WorkItemType], response.result)
    assert work_item_types[0].scope_project is not None
    assert work_item_types[0].scope_project.key == 'ENG'


async def test_controller_coalesces_create_metadata_requests():
    started = asyncio.Event()
    release_request = asyncio.Event()
    calls = 0

    async def get_work_item_create_meta(project_key: str, work_item_type_id: str) -> dict:
        nonlocal calls
        assert (project_key, work_item_type_id) == ('ENG', '10001')
        calls += 1
        started.set()
        await release_request.wait()
        return {'fields': []}

    controller = APIController.__new__(APIController)
    controller.client = cast(
        Any,
        SimpleNamespace(get_work_item_create_meta=get_work_item_create_meta),
    )

    first = asyncio.create_task(controller.get_work_item_create_metadata('ENG', '10001'))
    await asyncio.wait_for(started.wait(), timeout=1)
    second = asyncio.create_task(controller.get_work_item_create_metadata('ENG', '10001'))
    await asyncio.sleep(0)
    release_request.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert calls == 1
    assert first_result is second_result


async def test_controller_fetches_oauth_identity_and_jira_profile_concurrently():
    started, both_started, release_requests, wait_for_peer = _concurrent_request_gate()

    controller = APIController.__new__(APIController)
    controller.config = cast(Any, SimpleNamespace(jira=SimpleNamespace(auth_type='oauth2')))
    controller.identity_api = cast(
        Any,
        SimpleNamespace(
            make_request=lambda **kwargs: wait_for_peer(
                'identity',
                {
                    'account_id': 'user-1',
                    'account_type': 'atlassian',
                    'account_status': 'active',
                    'name': 'User One',
                    'email': 'user@example.com',
                },
            )
        ),
    )
    controller.client = cast(
        Any,
        SimpleNamespace(
            myself=lambda: wait_for_peer(
                'jira',
                {
                    'accountId': 'user-1',
                    'accountType': 'atlassian',
                    'active': True,
                    'displayName': 'User One',
                    'groups': {'items': []},
                },
            )
        ),
    )

    response_task = asyncio.create_task(controller.myself())
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release_requests.set()
    response = await response_task

    assert started == {'identity', 'jira'}
    assert response.success
    assert response.result is not None
    assert response.result.email == 'user@example.com'


async def test_sprint_board_fallback_temporarily_caches_empty_discovery():
    api = JiraAPI.__new__(JiraAPI)
    api.logger = logging.getLogger('gojeera.test')
    api._empty_fallback_board_discovery_until = {}
    api.get_boards_for_project = AsyncMock(return_value=[])
    api._fetch_paginated_agile_values = AsyncMock(return_value=[])

    assert await api.get_sprints_for_project('ENG') == []
    assert await api.get_sprints_for_project('eng') == []

    api._fetch_paginated_agile_values.assert_awaited_once_with(
        url='board',
        params={'type': 'scrum'},
        context_name='all scrum boards',
    )


async def test_sprint_board_fallback_persists_discovered_boards():
    api = JiraAPI.__new__(JiraAPI)
    api.logger = logging.getLogger('gojeera.test')
    api._empty_fallback_board_discovery_until = {}
    api.cache = cast(Any, SimpleNamespace(set_boards_for_project=Mock()))
    api.get_boards_for_project = AsyncMock(return_value=[])
    api._fetch_paginated_agile_values = AsyncMock(return_value=[ENGINEERING_SCRUM_BOARD])
    api.get_sprints_for_board = AsyncMock(return_value=[])

    assert await api.get_sprints_for_project('ENG') == []

    api.cache.set_boards_for_project.assert_called_once_with(
        'ENG',
        [ENGINEERING_SCRUM_BOARD],
    )


async def test_controller_full_work_item_load_defers_flagged_state_request():
    controller = _build_controller_for_full_work_item_load(flagged=True, summary='Flag me')

    response = await controller.get_work_item('ENG-1')

    assert response.success
    assert response.result is not None
    assert response.result.work_items[0].flagged is None
    _assert_full_work_item_loaded_with_default_fields(controller)
    cast(AsyncMock, controller.get_work_item_flagged_state).assert_not_awaited()


async def test_controller_full_work_item_load_requests_watches():
    controller = _build_controller_for_full_work_item_load(
        flagged=False,
        summary='Watch me',
        fields={'watches': {'isWatching': False, 'watchCount': 2}},
    )

    response = await controller.get_work_item('ENG-1')

    assert response.success
    assert response.result is not None
    assert response.result.work_items[0].watch_count == 2
    _assert_full_work_item_loaded_with_default_fields(controller)


async def test_controller_explicit_work_item_fields_are_not_enriched():
    controller = APIController.__new__(APIController)
    controller.client = AsyncMock()
    controller.logger = logging.getLogger('gojeera')
    controller.get_fields = AsyncMock()
    controller.client.get_work_item = AsyncMock(return_value=_work_item_response('Flag me'))

    response = await controller.get_work_item('ENG-1', fields=['summary'])

    assert response.success
    controller.get_fields.assert_not_awaited()
    assert not hasattr(controller, 'get_work_item_flagged_state') or not isinstance(
        controller.get_work_item_flagged_state, AsyncMock
    )
    controller.client.get_work_item.assert_awaited_once_with(
        work_item_id_or_key='ENG-1',
        fields='summary',
        properties=None,
    )


def _build_flaggable_work_item(flagged: bool = False):
    flagged_field_id = 'customfield_10021'
    return WorkItemFactory.create_work_item(
        {
            'id': '10001',
            'key': 'ENG-1',
            'fields': {
                'summary': 'Flag me',
                'status': {'id': '1', 'name': 'Open'},
                flagged_field_id: [{'value': 'Impediment'}] if flagged else [],
            },
            'editmeta': {
                'fields': {
                    flagged_field_id: {
                        'name': 'Flagged',
                        'operations': ['set'],
                        'allowedValues': [{'id': '10000', 'value': 'Impediment'}],
                    }
                }
            },
        }
    )


async def test_controller_set_work_item_flagged_uses_flagged_custom_field():
    controller = _build_controller_for_flag_update()
    work_item = _build_flaggable_work_item()

    response = await controller.set_work_item_flagged(work_item, True)

    assert response.success
    cast(AsyncMock, controller.client.update_work_item).assert_awaited_once_with(
        'ENG-1',
        fields={'customfield_10021': [{'value': 'Impediment'}]},
    )


async def test_controller_clear_work_item_flagged_sets_empty_list():
    controller = _build_controller_for_flag_update()
    work_item = _build_flaggable_work_item(flagged=True)

    response = await controller.set_work_item_flagged(work_item, False)

    assert response.success
    cast(AsyncMock, controller.client.update_work_item).assert_awaited_once_with(
        'ENG-1',
        fields={'customfield_10021': []},
    )


async def test_controller_get_work_item_flagged_state_uses_jql_count():
    controller = APIController.__new__(APIController)
    controller.client = AsyncMock()
    controller.client.search_work_items = AsyncMock(return_value={'issues': [{'key': 'ENG-25346'}]})

    response = await controller.get_work_item_flagged_state('ENG-25346')

    assert response.success
    assert response.result is True
    controller.client.search_work_items.assert_awaited_once_with(
        jql_query='key = "ENG-25346" AND "Flagged[Checkboxes]" = Impediment',
        fields=['key'],
        limit=1,
    )


def _build_controller_with_comment_permission_response(permission_response: dict) -> APIController:
    controller = APIController.__new__(APIController)
    controller.client = AsyncMock()
    get_my_permissions = AsyncMock(return_value=permission_response)
    add_comment = AsyncMock(
        return_value={
            'id': '10',
            'author': COMMENT_AUTHOR_RESPONSE,
        }
    )
    controller.client.get_my_permissions = get_my_permissions
    controller.client.add_comment = add_comment
    return controller


async def test_controller_add_comment_creates_comment_without_permission_preflight():
    controller = _build_controller_with_comment_permission_response(
        {
            'permissions': {
                'BROWSE_PROJECTS': {'havePermission': True},
                'ADD_COMMENTS': {'havePermission': True},
            }
        }
    )

    response = await controller.add_comment('ENG-1', 'hello')

    assert response.success
    assert isinstance(response.result, WorkItemComment)
    get_my_permissions = controller.client.get_my_permissions
    add_comment = controller.client.add_comment
    assert isinstance(get_my_permissions, AsyncMock)
    assert isinstance(add_comment, AsyncMock)
    get_my_permissions.assert_not_awaited()
    add_comment.assert_awaited_once_with(
        'ENG-1',
        'hello',
        jsd_public=None,
    )


async def test_controller_validate_add_comment_permissions_reports_missing_add_comments():
    controller = _build_controller_with_comment_permission_response(
        MISSING_ADD_COMMENTS_PERMISSION_RESPONSE
    )

    response = await controller.validate_add_comment_permissions('ENG-1')

    assert response is not None
    assert not response.success
    assert response.error == 'Missing required permission(s) to add comments: ADD_COMMENTS'
    get_my_permissions = controller.client.get_my_permissions
    add_comment = controller.client.add_comment
    assert isinstance(get_my_permissions, AsyncMock)
    assert isinstance(add_comment, AsyncMock)
    get_my_permissions.assert_awaited_once_with(
        work_item_id_or_key='ENG-1',
        permissions=['BROWSE_PROJECTS', 'ADD_COMMENTS'],
    )
    add_comment.assert_not_awaited()


async def test_controller_validate_work_item_permissions_reports_missing_permissions():
    controller = _build_controller_with_comment_permission_response(
        MISSING_ADD_COMMENTS_PERMISSION_RESPONSE
    )

    response = await controller.validate_work_item_permissions(
        'ENG-1',
        ['BROWSE_PROJECTS', 'ADD_COMMENTS'],
        action_name='add comments',
    )

    assert response is not None
    assert not response.success
    assert response.error == 'Missing required permission(s) to add comments: ADD_COMMENTS'


async def test_controller_validate_view_watchers_permissions_reports_missing_permission():
    controller = _build_controller_with_comment_permission_response(
        {
            'permissions': {
                'BROWSE_PROJECTS': {'havePermission': True},
                'VIEW_VOTERS_AND_WATCHERS': {'havePermission': False},
            }
        }
    )

    response = await controller.validate_view_watchers_permissions('ENG-1')

    assert response is not None
    assert not response.success
    assert (
        response.error
        == 'Missing required permission(s) to view watchers: VIEW_VOTERS_AND_WATCHERS'
    )
    get_my_permissions = controller.client.get_my_permissions
    assert isinstance(get_my_permissions, AsyncMock)
    get_my_permissions.assert_awaited_once_with(
        work_item_id_or_key='ENG-1',
        permissions=['BROWSE_PROJECTS', 'VIEW_VOTERS_AND_WATCHERS'],
    )


def test_build_work_item_keeps_project_type_key():
    work_item = WorkItemFactory.create_work_item(
        {
            'id': '10001',
            'key': 'SUP-1',
            'fields': {
                'summary': 'Help request',
                'project': {
                    'id': '60002',
                    'key': 'SUP',
                    'name': 'Support Project',
                    'projectTypeKey': 'service_desk',
                },
                'status': {'id': '1', 'name': 'Open'},
            },
        }
    )

    assert work_item.project is not None
    assert work_item.project.project_type_key == 'service_desk'
    assert work_item.project.is_service_desk


def test_build_work_item_reads_watch_summary():
    work_item = WorkItemFactory.create_work_item(
        {
            'id': '10001',
            'key': 'SUP-1',
            'fields': {
                'summary': 'Watched request',
                'status': {'id': '1', 'name': 'Open'},
                'watches': {
                    'isWatching': True,
                    'watchCount': 3,
                },
            },
        }
    )

    assert work_item.watch_count == 3
    assert work_item.is_watching is True


def test_build_comments_reads_jsd_public():
    comments = build_comments(
        [
            {
                'id': '10',
                'author': COMMENT_AUTHOR_RESPONSE,
                'jsdPublic': False,
            }
        ]
    )

    assert comments[0].jsd_public is False
