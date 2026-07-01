import json

import httpx
import pytest
import respx

from gojeera.internal.jira.api import JiraAPI
from gojeera.internal.models.exceptions import ServiceInvalidRequestException
from gojeera.utils.jira.graphql import GRAPHQL_PROJECT_REPOSITORIES_OAUTH_ERROR
from tests.jira_api_test_utils import (
    api_configuration,
    basic_auth_context,
    oauth2_auth_context,
)


@pytest.mark.asyncio
@respx.mock
async def test_get_project_repositories_uses_graphql_project_associations(
    mock_jira_graphql_project_repositories,
    mock_jira_graphql_project_repositories_payload,
):
    route = mock_jira_graphql_project_repositories(
        site='https://plainid.atlassian.net',
        project_key='ENG',
        project_name='Engineering',
    )
    api = JiraAPI(
        auth=basic_auth_context(site='https://plainid.atlassian.net'),
        configuration=api_configuration(site='https://plainid.atlassian.net'),
    )

    try:
        repositories = await api.get_project_repositories('ENG')
    finally:
        await api.client.close_async_client()
        await api.async_http_client.close_async_client()
        await api.graphql_client.close_async_client()

    assert repositories == mock_jira_graphql_project_repositories_payload

    project_request = json.loads(route.calls[0].request.content)
    assert project_request['variables'] == {'cloudId': 'cloud-123', 'projectKey': 'ENG'}

    first_repo_request = route.calls[1].request
    assert first_repo_request.headers['X-Query-Context'] == ('ari:cloud:platform::site/cloud-123')
    first_repo_payload = json.loads(first_repo_request.content)
    assert first_repo_payload['variables'] == {
        'projectAri': 'ari:cloud:jira:cloud-123:project/10446',
        'first': 1000,
        'after': None,
    }

    second_repo_request = json.loads(route.calls[2].request.content)
    assert second_repo_request['variables']['after'] == 'cursor-1'


@pytest.mark.asyncio
@respx.mock
async def test_get_project_repositories_rejects_oauth2_profiles_before_graphql_request():
    route = respx.post('https://api.atlassian.com/graphql').mock(
        return_value=httpx.Response(200, json={'data': {}})
    )
    api = JiraAPI(
        auth=oauth2_auth_context(site='https://plainid.atlassian.net'),
        configuration=api_configuration(site='https://plainid.atlassian.net'),
    )

    try:
        with pytest.raises(ServiceInvalidRequestException) as exc_info:
            await api.get_project_repositories('ENG')
    finally:
        await api.client.close_async_client()
        await api.async_http_client.close_async_client()
        await api.graphql_client.close_async_client()

    assert str(exc_info.value) == GRAPHQL_PROJECT_REPOSITORIES_OAUTH_ERROR
    assert not route.called
