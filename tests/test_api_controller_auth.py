from types import SimpleNamespace
from typing import cast

import pytest

from gojeera.internal.auth.oauth2 import OAuth2TokenResponse
from gojeera.internal.auth.profiles import OAuth2AuthProfile
from gojeera.internal.jira.controller import APIController
from gojeera.internal.store.config import ApplicationConfiguration


def _configuration_for_auth_context(auth_context: SimpleNamespace) -> ApplicationConfiguration:
    return cast(
        ApplicationConfiguration,
        SimpleNamespace(
            jira=SimpleNamespace(build_auth_context=lambda: auth_context),
            ssl=None,
            ignore_users_without_email=True,
        ),
    )


@pytest.mark.parametrize(
    ('auth_context', 'expected'),
    [
        (
            SimpleNamespace(
                auth_type='basic',
                profile_name='basic-profile',
                api_base_url='https://example.atlassian.net',
                api_email='user@example.com',
                api_token='basic-token',
                bearer_token=None,
                identity_base_url=None,
                rest_api_path_prefix='/rest/api/3/',
                agile_api_path_prefix='/rest/agile/1.0/',
            ),
            {
                'api_base_url': 'https://example.atlassian.net',
                'api_email': 'user@example.com',
                'api_token': 'basic-token',
                'bearer_token': None,
            },
        ),
        (
            SimpleNamespace(
                auth_type='oauth2',
                profile_name='oauth-profile',
                api_base_url='https://api.atlassian.com',
                api_email=None,
                api_token=None,
                bearer_token='oauth-token',
                identity_base_url='https://api.atlassian.com',
                rest_api_path_prefix='/ex/jira/cloud-123/rest/api/3/',
                agile_api_path_prefix='/ex/jira/cloud-123/rest/agile/1.0/',
            ),
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

    auth_context = SimpleNamespace(
        auth_type='oauth2',
        profile_name='oauth-profile',
        api_base_url='https://api.atlassian.com',
        api_email=None,
        api_token=None,
        bearer_token='expired-token',
        identity_base_url='https://api.atlassian.com',
        rest_api_path_prefix='/ex/jira/cloud-123/rest/api/3/',
        agile_api_path_prefix='/ex/jira/cloud-123/rest/agile/1.0/',
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
