import httpx
from pydantic import SecretStr
import pytest
import respx

from gojeera.api.client import AsyncJiraClient, JiraClient
from gojeera.config import ApplicationConfiguration, JiraConfig


def _configuration() -> ApplicationConfiguration:
    return ApplicationConfiguration.model_construct(
        jira=JiraConfig.model_construct(
            api_email_override='user@example.com',
            api_token=SecretStr('token'),
            api_base_url_override='https://api.atlassian.com',
        ),
        ssl=None,
    )


@pytest.mark.asyncio
@respx.mock
async def test_async_jira_client_retries_after_oauth2_refresh():
    refresh_calls = 0

    def refresh_token() -> str:
        nonlocal refresh_calls
        refresh_calls += 1
        return 'fresh-token'

    route = respx.get('https://api.atlassian.com/test').mock(
        side_effect=[
            httpx.Response(401, json={'errorMessages': ['expired']}),
            httpx.Response(200, json={'ok': True}),
        ]
    )

    client = AsyncJiraClient(
        base_url='https://api.atlassian.com',
        api_email=None,
        api_token=None,
        configuration=_configuration(),
        bearer_token='expired-token',
        token_refresh_callback=refresh_token,
    )

    try:
        response = await client.make_request(method=httpx.AsyncClient.get, url='test')
    finally:
        await client.close_async_client()

    assert response == {'ok': True}
    assert refresh_calls == 1
    assert route.calls[0].request.headers['Authorization'] == 'Bearer expired-token'
    assert route.calls[1].request.headers['Authorization'] == 'Bearer fresh-token'


@respx.mock
def test_jira_client_retries_after_oauth2_refresh():
    refresh_calls = 0

    def refresh_token() -> str:
        nonlocal refresh_calls
        refresh_calls += 1
        return 'fresh-token'

    route = respx.get('https://api.atlassian.com/test').mock(
        side_effect=[
            httpx.Response(401, json={'errorMessages': ['expired']}),
            httpx.Response(200, json={'ok': True}),
        ]
    )

    client = JiraClient(
        base_url='https://api.atlassian.com',
        api_email=None,
        api_token=None,
        configuration=_configuration(),
        bearer_token='expired-token',
        token_refresh_callback=refresh_token,
    )

    try:
        response = client.make_request(method=client.client.get, url='test')
    finally:
        client.client.close()

    assert response == {'ok': True}
    assert refresh_calls == 1
    assert route.calls[0].request.headers['Authorization'] == 'Bearer expired-token'
    assert route.calls[1].request.headers['Authorization'] == 'Bearer fresh-token'
