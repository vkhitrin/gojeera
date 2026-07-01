from types import SimpleNamespace
from typing import Awaitable, Callable, cast

import pytest

from gojeera.internal.auth.oauth2 import OAuth2TokenResponse
from gojeera.internal.auth.profiles import OAuth2AuthProfile
from gojeera.internal.jira.controller import (
    API_TOKEN_FALLBACK_REQUIRED_ERROR,
    APIController,
    APIControllerResponse,
)
from gojeera.internal.models.jira import JiraProjectRepository
from gojeera.internal.store.config import ApplicationConfiguration
from tests.jira_api_test_utils import (
    basic_auth_context,
    controller_configuration,
    oauth2_auth_context,
)


def _configuration_for_auth_context(auth_context: SimpleNamespace) -> ApplicationConfiguration:
    return cast(
        ApplicationConfiguration,
        SimpleNamespace(
            jira=SimpleNamespace(build_auth_context=lambda: auth_context),
            ssl=None,
            ignore_users_without_email=True,
        ),
    )


def _unexpected_oauth_client_use(*args, **kwargs):
    raise AssertionError('OAuth client should not be used without API-token fallback')


async def _get_project_repositories_response(controller: APIController):
    return await controller.get_project_repositories('ENG')


async def _get_repository_pull_requests_response(controller: APIController):
    return await controller.get_repository_pull_requests(
        'ENG',
        JiraProjectRepository(id='repo-1', name='platform-api'),
    )


async def _get_work_item_pull_requests_response(controller: APIController):
    return await controller.get_work_item_development_pull_requests(
        'ENG-22332',
        work_item_id='108321',
    )


@pytest.mark.parametrize(
    ('auth_context', 'expected'),
    [
        (
            basic_auth_context(
                api_token='basic-token',
                profile_name='basic-profile',
            ),
            {
                'api_base_url': 'https://example.atlassian.net',
                'api_email': 'user@example.com',
                'api_token': 'basic-token',
                'bearer_token': None,
            },
        ),
        (
            oauth2_auth_context(profile_name='oauth-profile', bearer_token='oauth-token'),
            {
                'api_base_url': 'https://api.atlassian.com',
                'api_email': None,
                'api_token': None,
                'bearer_token': 'oauth-token',
                'rest_api_path_prefix': '/ex/jira/cloud-123/rest/api/3/',
                'agile_api_path_prefix': '/ex/jira/cloud-123/rest/agile/1.0/',
            },
        ),
    ],
)
def test_api_controller_uses_auth_profile(monkeypatch, auth_context, expected):
    captured = {}

    def mock_jira_api(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr('gojeera.internal.jira.controller.JiraAPI', mock_jira_api)

    APIController(configuration=_configuration_for_auth_context(auth_context))

    for field_name, expected_value in expected.items():
        assert getattr(captured['auth'], field_name) == expected_value


def test_api_controller_refreshes_expired_oauth2_token_and_updates_clients(monkeypatch):
    refreshed_tokens: list[str] = []

    auth_context = oauth2_auth_context(
        profile_name='oauth-profile',
        bearer_token='expired-token',
    )
    active_profile = OAuth2AuthProfile(
        name='oauth-profile',
        site='https://example.atlassian.net',
        cloud_id='cloud-123',
        account_id='account-123',
        client_id='client-123',
        oauth2_access_token_expiration_timestamp=1,
    )

    jira_settings = SimpleNamespace(
        build_auth_context=lambda: auth_context,
        active_profile=active_profile,
        update_active_oauth2_session=lambda **kwargs: refreshed_tokens.append(
            kwargs['access_token']
        ),
    )
    configuration = cast(
        ApplicationConfiguration,
        SimpleNamespace(
            jira=jira_settings,
            ssl=None,
            ignore_users_without_email=True,
        ),
    )

    monkeypatch.setattr(
        'gojeera.internal.jira.controller.JiraAPI',
        lambda **kwargs: SimpleNamespace(
            set_bearer_token=lambda token: refreshed_tokens.append(token)
        ),
    )
    monkeypatch.setattr(
        'gojeera.internal.jira.controller.AsyncJiraClient',
        lambda **kwargs: SimpleNamespace(
            set_bearer_token=lambda token: refreshed_tokens.append(token)
        ),
    )
    monkeypatch.setattr(
        'gojeera.internal.jira.controller.AuthService',
        lambda: SimpleNamespace(
            should_refresh_oauth2_access_token=lambda profile: True,
            refresh_oauth2_access_token=lambda profile: OAuth2TokenResponse(
                access_token='fresh-token',
                refresh_token='fresh-refresh-token',
                access_token_expiration_timestamp=3600,
            ),
            get_oauth2_access_token=lambda profile: 'fresh-token',
        ),
    )

    controller = APIController(configuration=configuration)

    assert controller._refresh_oauth2_access_token(False) == 'fresh-token'
    assert refreshed_tokens == ['fresh-token', 'fresh-token', 'fresh-token']


@pytest.mark.asyncio
async def test_api_controller_uses_api_token_fallback_for_project_repositories(monkeypatch):
    auth_context = oauth2_auth_context(
        profile_name='oauth-profile',
        bearer_token='oauth-token',
    )
    fallback_auth = SimpleNamespace(auth_type='basic', profile_name='bot')
    closed = []

    class FakeAsyncClient:
        async def close_async_client(self):
            closed.append('closed')

    class FakeJiraAPI:
        def __init__(self, *, auth, **kwargs):
            self.auth = auth
            self.client = FakeAsyncClient()
            self.async_http_client = FakeAsyncClient()
            self.graphql_client = FakeAsyncClient()

        async def get_project_repositories(self, project_key):
            assert self.auth is fallback_auth
            assert project_key == 'ENG'
            return [
                {
                    'id': 'repo-1',
                    'name': 'platform-api',
                    'url': 'https://gitlab.example/platform-api',
                }
            ]

        async def get_project_features(self, project_key):
            assert self.auth is auth_context
            assert project_key == 'ENG'
            return {'features': [{'feature': 'jsw.classic.code', 'state': 'ENABLED'}]}

    configuration = cast(
        ApplicationConfiguration,
        SimpleNamespace(
            jira=SimpleNamespace(
                build_auth_context=lambda: auth_context,
                api_token_fallback_profile='bot',
                build_api_token_auth_context=lambda profile_name: fallback_auth,
            ),
            ssl=None,
            ignore_users_without_email=True,
        ),
    )

    monkeypatch.setattr('gojeera.internal.jira.controller.JiraAPI', FakeJiraAPI)

    controller = APIController(configuration=configuration)
    response = await controller.get_project_repositories('ENG')
    repositories = cast(list, response.result)

    assert response.success
    assert repositories[0].id == 'repo-1'
    assert repositories[0].name == 'platform-api'
    assert closed == ['closed', 'closed', 'closed']


@pytest.mark.parametrize(
    ('client_method_name', 'controller_call'),
    [
        ('get_project_repositories', _get_project_repositories_response),
        ('get_project_space_pull_requests', _get_repository_pull_requests_response),
        ('get_work_item_pull_requests', _get_work_item_pull_requests_response),
    ],
)
@pytest.mark.asyncio
async def test_api_controller_reports_missing_fallback_for_oauth_blocked_features(
    monkeypatch,
    client_method_name: str,
    controller_call: Callable[[APIController], Awaitable[APIControllerResponse]],
):
    auth_context = oauth2_auth_context(
        profile_name='oauth-profile',
        bearer_token='oauth-token',
    )
    controller = APIController(configuration=controller_configuration(auth_context=auth_context))
    monkeypatch.setattr(controller.client, client_method_name, _unexpected_oauth_client_use)

    try:
        response = await controller_call(controller)
    finally:
        await controller.close()

    assert not response.success
    assert response.error == API_TOKEN_FALLBACK_REQUIRED_ERROR
