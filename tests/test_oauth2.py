from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from gojeera.oauth2 import (
    ATLASSIAN_ACCESSIBLE_RESOURCES_URL,
    build_atlassian_authorization_url,
    exchange_atlassian_authorization_code,
    get_atlassian_accessible_resources,
    refresh_atlassian_oauth2_token,
    run_atlassian_oauth2_authorization_flow,
)


def test_build_atlassian_authorization_url_uses_default_redirect_uri():
    url = build_atlassian_authorization_url(
        client_id='client-123',
        scopes=[
            'read:jira-user',
            'read:jira-work',
            'write:jira-work',
            'read:servicedesk-request',
            'offline_access',
            'read:me',
            'read:account',
        ],
        state='state-123',
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == 'https'
    assert parsed.netloc == 'auth.atlassian.com'
    assert parsed.path == '/authorize'
    assert query['audience'] == ['api.atlassian.com']
    assert query['client_id'] == ['client-123']
    assert query['redirect_uri'] == ['http://127.0.0.1:49152/callback']
    assert query['response_type'] == ['code']
    assert query['prompt'] == ['consent']
    assert query['scope'] == [
        'read:jira-user read:jira-work write:jira-work read:servicedesk-request '
        'offline_access read:me read:account'
    ]
    assert query['state'] == ['state-123']


@respx.mock
def test_exchange_atlassian_authorization_code():
    route = respx.post('https://auth.atlassian.com/oauth/token').mock(
        return_value=httpx.Response(
            200,
            json={
                'access_token': 'access-token',
                'refresh_token': 'refresh-token',
                'expires_in': 3600,
                'scope': 'read:jira-user read:jira-work',
                'token_type': 'Bearer',
            },
        )
    )

    response = exchange_atlassian_authorization_code(
        client_id='client-123',
        client_secret='secret-123',
        code='code-123',
    )

    assert route.called
    assert response.access_token == 'access-token'
    assert response.refresh_token == 'refresh-token'
    assert response.expires_in == 3600


@respx.mock
def test_refresh_atlassian_oauth2_token():
    route = respx.post('https://auth.atlassian.com/oauth/token').mock(
        return_value=httpx.Response(
            200,
            json={
                'access_token': 'fresh-access-token',
                'refresh_token': 'fresh-refresh-token',
                'expires_in': 7200,
                'token_type': 'Bearer',
            },
        )
    )

    response = refresh_atlassian_oauth2_token(
        client_id='client-123',
        client_secret='secret-123',
        refresh_token='stale-refresh-token',
    )

    assert route.called
    assert response.access_token == 'fresh-access-token'
    assert response.refresh_token == 'fresh-refresh-token'
    assert response.expires_in == 7200


@respx.mock
def test_get_atlassian_accessible_resources():
    route = respx.get(ATLASSIAN_ACCESSIBLE_RESOURCES_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    'id': 'cloud-123',
                    'name': 'Example Site',
                    'url': 'https://example.atlassian.net',
                    'scopes': ['read:jira-user'],
                    'avatarUrl': 'https://example.atlassian.net/avatar.png',
                }
            ],
        )
    )

    resources = get_atlassian_accessible_resources(access_token='access-token')

    assert route.called
    assert len(resources) == 1
    assert resources[0].id == 'cloud-123'
    assert resources[0].url == 'https://example.atlassian.net'
    assert resources[0].avatar_url == 'https://example.atlassian.net/avatar.png'


@respx.mock
def test_get_atlassian_accessible_resources_requires_list_payload():
    respx.get(ATLASSIAN_ACCESSIBLE_RESOURCES_URL).mock(
        return_value=httpx.Response(200, json={'invalid': True})
    )

    with pytest.raises(ValueError, match='must be a list'):
        get_atlassian_accessible_resources(access_token='access-token')


def test_run_atlassian_oauth2_authorization_flow(monkeypatch):
    monkeypatch.setattr(
        'gojeera.oauth2.wait_for_atlassian_oauth2_callback',
        lambda **kwargs: type('CallbackResult', (), {'code': 'code-123', 'state': 'state-123'})(),
    )
    monkeypatch.setattr(
        'gojeera.oauth2.exchange_atlassian_authorization_code',
        lambda **kwargs: type(
            'TokenResponse',
            (),
            {'access_token': 'access-token', 'refresh_token': 'refresh-token'},
        )(),
    )

    response = run_atlassian_oauth2_authorization_flow(
        client_id='client-123',
        client_secret='secret-123',
        scopes=[
            'read:jira-user',
            'read:jira-work',
            'write:jira-work',
            'read:servicedesk-request',
            'offline_access',
            'read:me',
            'read:account',
        ],
    )

    assert response.access_token == 'access-token'
    assert response.refresh_token == 'refresh-token'
