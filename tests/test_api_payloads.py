from unittest.mock import AsyncMock

import httpx

from gojeera.internal.jira.controller import APIController
from gojeera.internal.jira.api import JiraAPI
from gojeera.internal.jira.factories import WorkItemFactory, build_comments
from gojeera.internal.models.work_items import WorkItemComment
from tests.jira_api_test_utils import build_api_with_mocked_client

COMMENT_AUTHOR_RESPONSE = {
    'accountId': 'user-1',
    'active': True,
    'displayName': 'User One',
}


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
        {
            'permissions': {
                'BROWSE_PROJECTS': {'havePermission': True},
                'ADD_COMMENTS': {'havePermission': False},
            }
        }
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
