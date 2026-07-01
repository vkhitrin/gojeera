from typing import cast
import json

import httpx
import pytest
import respx

from gojeera.internal.jira.api import JiraAPI
from gojeera.internal.jira.controller import APIController
from gojeera.internal.models.jira import JiraProjectRepository
from tests.jira_api_test_utils import (
    api_configuration,
    basic_auth_context,
    controller_configuration,
    external_pull_request_data,
    graphql_project_by_key_response,
)


def _project_space_pull_request_edge(
    *,
    edge_id: str,
    pull_request_data: dict,
    work_item_id: str | None = None,
) -> dict:
    node = dict(pull_request_data)
    if work_item_id is not None:
        node['associatedWith'] = {
            'edges': [
                {
                    'node': {
                        'entity': {
                            '__typename': 'JiraIssue',
                            'issueId': work_item_id,
                        }
                    }
                }
            ]
        }
    return {
        'id': edge_id,
        'createdAt': '2026-06-18T00:00:00Z',
        'lastUpdated': pull_request_data.get('lastUpdated') or pull_request_data.get('lastUpdate'),
        'node': node,
    }


def _expected_devops_pull_request() -> dict:
    return {
        'id': 'pr-1',
        'title': 'Add platform API',
        'work_item_key': '10001',
        'work_item_id': '10001',
        'work_item_ari': 'ari:cloud:jira:cloud-123:issue/10001',
        'status': 'OPEN',
        'url': 'https://gitlab.example/platform-api/merge_requests/1',
        'author': 'Dev User',
        'repository_id': 'repo-123',
        'repository_name': 'platform-api',
        'repository_url': 'https://gitlab.example/platform-api',
        'provider_id': 'gitlab',
        'provider_name': 'GitLab',
        'source_branch': 'feature/api',
        'destination_branch': 'main',
        'last_updated': '2026-06-19T08:00:00Z',
    }


def _expected_external_pull_request(
    *,
    work_item_id: str = '10002',
    work_item_ari: str | None = '{value=ari:cloud:jira:cloud-123:issue/10002}',
    title: str = 'External GitLab PR',
    source_branch: str = 'feature/gitlab',
) -> dict:
    return {
        'id': 'external-pr-1',
        'title': title,
        'work_item_key': work_item_id,
        'work_item_id': work_item_id,
        'work_item_ari': work_item_ari,
        'status': 'MERGED',
        'url': 'https://gitlab.example/platform-api/merge_requests/2',
        'author': None,
        'repository_id': '36571207',
        'repository_name': None,
        'repository_url': None,
        'provider_id': 'gitlab-jira-connect-gitlab.com',
        'provider_name': 'GitLab',
        'source_branch': source_branch,
        'destination_branch': 'main',
        'last_updated': '2026-06-19T09:00:00Z',
    }


def _development_pull_request_data() -> dict:
    return {
        'id': 'pr-1',
        'title': 'PAA - Secure Communication between Services',
        'work_item_key': '108321',
        'work_item_id': '108321',
        'status': 'MERGED',
        'url': 'https://gitlab.example/platform-api/merge_requests/1',
        'repository_id': '36571207',
        'repository_name': 'agent',
        'provider_name': 'GitLab',
        'source_branch': 'ENG-22332-PAA',
        'destination_branch': 'main',
        'last_updated': '2026-06-19T08:00:00Z',
    }


def _graphql_pull_request_connection(edges: list[dict]) -> dict:
    return {
        'edges': edges,
        'pageInfo': {
            'hasNextPage': False,
            'endCursor': None,
        },
    }


def _graphql_project_space_pull_requests_response() -> dict:
    return {
        'data': {
            'graphStoreV2': {
                'jiraSpaceLinksExternalPullRequest': _graphql_pull_request_connection(
                    [
                        _project_space_pull_request_edge(
                            edge_id='edge-1',
                            pull_request_data=external_pull_request_data(),
                        ),
                    ]
                )
            }
        }
    }


async def _get_development_pull_requests_with_mocks(
    monkeypatch,
    controller: APIController,
    *,
    get_work_item,
    get_work_item_pull_requests,
    work_item_id: str | None = None,
):
    monkeypatch.setattr(controller.client, 'get_work_item', get_work_item)
    monkeypatch.setattr(
        controller.client, 'get_work_item_pull_requests', get_work_item_pull_requests
    )
    try:
        return await controller.get_work_item_development_pull_requests(
            'ENG-22332',
            work_item_id=work_item_id,
            project_key='ENG',
        )
    finally:
        await controller.close()


async def _get_development_pull_requests_with_payload(
    monkeypatch,
    controller: APIController,
    *,
    get_work_item,
    payload: dict,
    work_item_id: str | None = None,
):
    return await _get_development_pull_requests_with_mocks(
        monkeypatch,
        controller,
        get_work_item=get_work_item,
        get_work_item_pull_requests=_build_get_work_item_pull_requests(payload),
        work_item_id=work_item_id,
    )


def _assert_single_development_pull_request(response) -> None:
    assert response.success
    pull_requests = cast(list, response.result)
    assert len(pull_requests) == 1
    assert pull_requests[0].work_item_key == 'ENG-22332'
    assert pull_requests[0].work_item_id == '108321'


def _build_get_work_item_pull_requests(payload: dict):
    async def get_work_item_pull_requests(work_item_id):
        assert work_item_id == '108321'
        return [payload]

    return get_work_item_pull_requests


@pytest.mark.asyncio
@respx.mock
async def test_get_project_space_pull_requests_uses_graphql_v2_project_prs():
    route = respx.post('https://example.atlassian.net/gateway/api/graphql').mock(
        side_effect=[
            httpx.Response(200, json=graphql_project_by_key_response()),
            httpx.Response(200, json=_graphql_project_space_pull_requests_response()),
        ]
    )
    api = JiraAPI(auth=basic_auth_context(), configuration=api_configuration())

    try:
        pull_requests = await api.get_project_space_pull_requests('ENG')
    finally:
        await api.client.close_async_client()
        await api.async_http_client.close_async_client()
        await api.graphql_client.close_async_client()

    expected_pull_request = _expected_external_pull_request(
        work_item_id='10002', work_item_ari=None
    )
    expected_pull_request['work_item_key'] = ''
    expected_pull_request['work_item_id'] = ''
    assert pull_requests == [expected_pull_request]

    request = route.calls[1].request
    assert request.headers['X-Query-Context'] == 'ari:cloud:platform::site/cloud-123'
    payload = json.loads(request.content)
    assert payload['variables'] == {
        'projectAri': 'ari:cloud:jira:cloud-123:project/10446',
        'first': 100,
        'after': None,
    }
    assert 'jiraSpaceLinksExternalPullRequest' in payload['query']
    assert 'associatedWith' not in payload['query']
    assert 'issueId' not in payload['query']
    assert 'key' not in payload['query']


@pytest.mark.asyncio
@respx.mock
async def test_get_work_item_pull_requests_uses_graphql_issue_associated_prs():
    route = respx.post('https://example.atlassian.net/gateway/api/graphql').mock(
        return_value=httpx.Response(
            200,
            json={
                'data': {
                    'graphStoreV2_jiraWorkItemLinksExternalPullRequest': (
                        _graphql_pull_request_connection(
                            [
                                {
                                    'id': 'edge-1',
                                    'createdAt': '2026-06-18T00:00:00Z',
                                    'lastUpdated': '2026-06-19T09:00:00Z',
                                    'node': external_pull_request_data(),
                                },
                            ]
                        )
                    )
                }
            },
        )
    )
    api = JiraAPI(auth=basic_auth_context(), configuration=api_configuration())

    try:
        pull_requests = await api.get_work_item_pull_requests('108321')
    finally:
        await api.client.close_async_client()
        await api.async_http_client.close_async_client()
        await api.graphql_client.close_async_client()

    expected_pull_request = _expected_external_pull_request(
        work_item_id='108321',
        work_item_ari='ari:cloud:jira:cloud-123:issue/108321',
    )
    expected_pull_request['work_item_key'] = ''
    assert pull_requests == [expected_pull_request]

    request = route.calls[0].request
    assert request.headers['X-Query-Context'] == 'ari:cloud:platform::site/cloud-123'
    payload = json.loads(request.content)
    assert payload['variables'] == {
        'issueAri': 'ari:cloud:jira:cloud-123:issue/108321',
        'first': 100,
        'after': None,
    }
    assert 'GraphStoreV2IssueAssociatedPr' in payload['query']


@pytest.mark.asyncio
async def test_get_repository_pull_requests_filters_graphql_prs_by_repository(monkeypatch):
    controller = APIController(configuration=controller_configuration())
    repository = JiraProjectRepository(
        id='ari:cloud:repo/1',
        name='platform-api',
        external_id='repo-123',
        provider_id='gitlab',
        url='https://gitlab.example/platform-api',
    )

    async def get_project_space_pull_requests(project_key):
        assert project_key == 'ENG'
        return [
            _expected_devops_pull_request()
            | {
                'source_branch': 'feature/ENG-10001-api',
                'work_item_ari': None,
                'work_item_key': 'ENG-10001',
                'work_item_id': '',
                'status': 'OPEN',
            },
            {
                'id': 'pr-2',
                'title': 'Other repo',
                'work_item_key': '10002',
                'work_item_id': '10002',
                'repository_id': 'repo-999',
            },
            _expected_external_pull_request(
                work_item_ari='ari:cloud:jira:cloud-123:issue/10002',
            ),
        ]

    async def get_work_item(work_item_id_or_key, fields=None, properties=None):
        raise AssertionError('repository pull request load should not resolve GraphQL issue ids')

    monkeypatch.setattr(
        controller.client,
        'get_project_space_pull_requests',
        get_project_space_pull_requests,
    )
    monkeypatch.setattr(controller.client, 'get_work_item', get_work_item)

    try:
        response = await controller.get_repository_pull_requests('ENG', repository)
    finally:
        await controller.close()

    assert response.success
    pull_requests = cast(list, response.result)
    assert len(pull_requests) == 1
    assert pull_requests[0].id == 'pr-1'
    assert pull_requests[0].title == 'Add platform API'
    assert pull_requests[0].work_item_key == 'ENG-10001'
    assert pull_requests[0].work_item_id == ''
    assert pull_requests[0].source_branch == 'feature/ENG-10001-api'


@pytest.mark.asyncio
async def test_get_work_item_development_pull_requests_filters_graphql_prs_by_work_item(
    monkeypatch,
):
    controller = APIController(configuration=controller_configuration())

    async def get_work_item(work_item_id_or_key, fields=None, properties=None):
        assert work_item_id_or_key == 'ENG-22332'
        assert fields == 'key'
        assert properties is None
        return {
            'id': '108321',
            'key': 'ENG-22332',
        }

    response = await _get_development_pull_requests_with_payload(
        monkeypatch,
        controller,
        get_work_item=get_work_item,
        payload=_development_pull_request_data(),
    )

    _assert_single_development_pull_request(response)
    pull_requests = cast(list, response.result)
    assert pull_requests[0].id == 'pr-1'
    assert pull_requests[0].repository_name == 'agent'
    assert pull_requests[0].provider_name == 'GitLab'


@pytest.mark.asyncio
async def test_get_work_item_development_pull_requests_uses_supplied_work_item_id(
    monkeypatch,
):
    controller = APIController(configuration=controller_configuration())

    async def get_work_item(*args, **kwargs):
        raise AssertionError('work item should not be fetched when id and project are supplied')

    response = await _get_development_pull_requests_with_payload(
        monkeypatch,
        controller,
        get_work_item=get_work_item,
        payload=_development_pull_request_data()
        | {
            'repository_id': None,
            'repository_name': None,
            'provider_name': None,
            'source_branch': None,
            'destination_branch': None,
            'last_updated': None,
        },
        work_item_id='108321',
    )

    _assert_single_development_pull_request(response)
