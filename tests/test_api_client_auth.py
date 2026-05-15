import httpx
from pydantic import SecretStr
import pytest
import respx

from gojeera.internal.jira.client import AsyncJiraClient, JiraClient
from gojeera.internal.store.config import ApplicationConfiguration, JiraConfig


def _configuration() -> ApplicationConfiguration:
    return ApplicationConfiguration.model_construct(
        jira=JiraConfig.model_construct(
            api_email_override='user@example.com',
            api_token=SecretStr('token'),
            api_base_url_override='https://api.atlassian.com',
        ),
        ssl=None,
    )


def _refresh_token_counter():
    refresh_calls: list[bool] = []

    def refresh_token(force: bool) -> str | None:
        refresh_calls.append(force)
        if force:
            return 'fresh-token'
        return None

    def calls() -> list[bool]:
        return refresh_calls

    return refresh_token, calls


def _retry_route():
    return respx.get('https://api.atlassian.com/test').mock(
        side_effect=[
            httpx.Response(401, json={'errorMessages': ['expired']}),
            httpx.Response(200, json={'ok': True}),
        ]
    )


def _oauth2_client_kwargs(token_refresh_callback):
    return {
        'base_url': 'https://api.atlassian.com',
        'api_email': None,
        'api_token': None,
        'configuration': _configuration(),
        'bearer_token': 'expired-token',
        'token_refresh_callback': token_refresh_callback,
    }


def _assert_retry_result(route, call_count: int, response) -> None:
    assert response == {'ok': True}
    assert call_count == [False, True]
    assert route.calls[0].request.headers['Authorization'] == 'Bearer expired-token'
    assert route.calls[1].request.headers['Authorization'] == 'Bearer fresh-token'


@pytest.mark.asyncio
@respx.mock
async def test_async_jira_client_retries_after_oauth2_refresh():
    refresh_token, refresh_calls = _refresh_token_counter()
    route = _retry_route()

    client = AsyncJiraClient(**_oauth2_client_kwargs(refresh_token))

    try:
        response = await client.make_request(method=httpx.AsyncClient.get, url='test')
    finally:
        await client.close_async_client()

    _assert_retry_result(route, refresh_calls(), response)


@respx.mock
def test_jira_client_retries_after_oauth2_refresh():
    refresh_token, refresh_calls = _refresh_token_counter()
    route = _retry_route()

    client = JiraClient(**_oauth2_client_kwargs(refresh_token))

    try:
        response = client.make_request(method=client.client.get, url='test')
    finally:
        client.client.close()

    _assert_retry_result(route, refresh_calls(), response)


@respx.mock
def test_jira_client_refreshes_expired_oauth2_token_before_request():
    refresh_calls: list[bool] = []
    route = respx.get('https://api.atlassian.com/test').mock(
        return_value=httpx.Response(200, json={'ok': True})
    )

    def refresh_token(force: bool) -> str | None:
        refresh_calls.append(force)
        return 'fresh-token'

    client = JiraClient(**_oauth2_client_kwargs(refresh_token))

    try:
        response = client.make_request(method=client.client.get, url='test')
    finally:
        client.client.close()

    assert response == {'ok': True}
    assert refresh_calls == [False]
    assert route.calls[0].request.headers['Authorization'] == 'Bearer fresh-token'
