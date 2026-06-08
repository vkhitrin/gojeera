import logging
from typing import cast
from unittest.mock import AsyncMock

import httpx

from gojeera.internal.jira.controller import APIController, APIControllerResponse
from gojeera.internal.jira.api import JiraAPI
from gojeera.internal.jira.factories import WorkItemFactory, build_comments
from gojeera.internal.models.jira import JiraField, WorkItemWatchers
from gojeera.internal.models.work_items import WorkItemComment
from tests.jira_api_test_utils import build_api_with_mocked_client

COMMENT_AUTHOR_RESPONSE = {
    'accountId': 'user-1',
    'active': True,
    'displayName': 'User One',
}

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


async def test_controller_full_work_item_load_uses_jql_workaround_for_flagged_state():
    controller = _build_controller_for_full_work_item_load(flagged=True, summary='Flag me')

    response = await controller.get_work_item('ENG-1')

    assert response.success
    assert response.result is not None
    assert response.result.work_items[0].flagged is True
    _assert_full_work_item_loaded_with_default_fields(controller)
    cast(AsyncMock, controller.get_work_item_flagged_state).assert_awaited_once_with('ENG-1')


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
    controller.client.search_work_items = AsyncMock(
        return_value={'issues': [{'key': 'PLAT-25346'}]}
    )

    response = await controller.get_work_item_flagged_state('PLAT-25346')

    assert response.success
    assert response.result is True
    controller.client.search_work_items.assert_awaited_once_with(
        jql_query='key = "PLAT-25346" AND "Flagged[Checkboxes]" = Impediment',
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
