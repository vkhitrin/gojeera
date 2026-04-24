from types import SimpleNamespace
from typing import cast

from gojeera.api_controller.controller import APIController
from gojeera.config import ApplicationConfiguration


def test_api_controller_uses_basic_auth_profile(monkeypatch):
    captured = {}

    def mock_jira_api(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr('gojeera.api_controller.controller.JiraAPI', mock_jira_api)

    configuration = cast(
        ApplicationConfiguration,
        SimpleNamespace(
            jira=SimpleNamespace(
                build_auth_context=lambda: SimpleNamespace(
                    auth_type='basic',
                    profile_name='basic-profile',
                    api_base_url='https://example.atlassian.net',
                    api_email='user@example.com',
                    api_token='basic-token',
                    bearer_token=None,
                    identity_base_url=None,
                    rest_api_path_prefix='/rest/api/3/',
                    agile_api_path_prefix='/rest/agile/1.0/',
                )
            ),
            ssl=None,
            ignore_users_without_email=True,
        ),
    )

    APIController(configuration=configuration)

    assert captured['auth'].api_base_url == 'https://example.atlassian.net'
    assert captured['auth'].api_email == 'user@example.com'
    assert captured['auth'].api_token == 'basic-token'
    assert captured['auth'].bearer_token is None


def test_api_controller_uses_oauth2_profile(monkeypatch):
    captured = {}

    def mock_jira_api(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr('gojeera.api_controller.controller.JiraAPI', mock_jira_api)

    configuration = cast(
        ApplicationConfiguration,
        SimpleNamespace(
            jira=SimpleNamespace(
                build_auth_context=lambda: SimpleNamespace(
                    auth_type='oauth2',
                    profile_name='oauth-profile',
                    api_base_url='https://api.atlassian.com',
                    api_email=None,
                    api_token=None,
                    bearer_token='oauth-token',
                    identity_base_url='https://api.atlassian.com',
                    rest_api_path_prefix='/ex/jira/cloud-123/rest/api/3/',
                    agile_api_path_prefix='/ex/jira/cloud-123/rest/agile/1.0/',
                )
            ),
            ssl=None,
            ignore_users_without_email=True,
        ),
    )

    APIController(configuration=configuration)

    assert captured['auth'].api_base_url == 'https://api.atlassian.com'
    assert captured['auth'].api_email is None
    assert captured['auth'].api_token is None
    assert captured['auth'].bearer_token == 'oauth-token'
    assert captured['auth'].rest_api_path_prefix == '/ex/jira/cloud-123/rest/api/3/'
    assert captured['auth'].agile_api_path_prefix == '/ex/jira/cloud-123/rest/agile/1.0/'
