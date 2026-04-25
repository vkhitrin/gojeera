from types import SimpleNamespace
from typing import cast

import pytest

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
