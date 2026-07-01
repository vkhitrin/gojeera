import logging
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from pydantic import SecretStr

from gojeera.internal.jira.api import JiraAPI
from gojeera.internal.store.config import ApplicationConfiguration, JiraAuthContext, JiraConfig


def build_api_with_mocked_client(responses: list[dict]) -> tuple[JiraAPI, AsyncMock]:
    api = JiraAPI.__new__(JiraAPI)
    api.logger = logging.getLogger('gojeera.test')
    api._client = AsyncMock()
    api._client.make_request = AsyncMock(side_effect=responses)
    return api, api._client.make_request


def basic_auth_context(
    *,
    site: str = 'https://example.atlassian.net',
    api_token: str = 'token',
    profile_name: str = 'bot',
) -> JiraAuthContext:
    return JiraAuthContext(
        profile_name=profile_name,
        auth_type='basic',
        api_base_url=site,
        instance_base_url=site,
        api_email='user@example.com',
        api_token=api_token,
        cloud_id='cloud-123',
        account_id='account-123',
    )


def oauth2_auth_context(
    *,
    site: str = 'https://example.atlassian.net',
    bearer_token: str = 'token',
    profile_name: str = 'oauth',
) -> JiraAuthContext:
    return JiraAuthContext(
        profile_name=profile_name,
        auth_type='oauth2',
        api_base_url='https://api.atlassian.com',
        instance_base_url=site,
        bearer_token=bearer_token,
        cloud_id='cloud-123',
        account_id='account-123',
        rest_api_path_prefix='/ex/jira/cloud-123/rest/api/3/',
        agile_api_path_prefix='/ex/jira/cloud-123/rest/agile/1.0/',
        identity_base_url='https://api.atlassian.com',
    )


def api_configuration(*, site: str = 'https://example.atlassian.net') -> ApplicationConfiguration:
    return ApplicationConfiguration.model_construct(
        jira=JiraConfig.model_construct(
            api_email_override='user@example.com',
            api_token=SecretStr('token'),
            api_base_url_override=site,
        ),
        ssl=None,
    )


def controller_configuration(
    *,
    site: str = 'https://example.atlassian.net',
    auth_context: JiraAuthContext | None = None,
) -> ApplicationConfiguration:
    resolved_auth_context = auth_context or basic_auth_context(
        site=site,
        api_token='basic-token',
        profile_name='basic-profile',
    )
    return cast(
        ApplicationConfiguration,
        SimpleNamespace(
            jira=SimpleNamespace(
                build_auth_context=lambda: resolved_auth_context,
                api_token_fallback_profile=None,
            ),
            ssl=None,
            ignore_users_without_email=True,
        ),
    )


def external_pull_request_data() -> dict:
    return {
        '__typename': 'ExternalPullRequest',
        'id': 'external-pr-1',
        'externalRepositoryId': '36571207',
        'title': 'External GitLab PR',
        'externalStatus': 'MERGED',
        'url': 'https://gitlab.example/platform-api/merge_requests/2',
        'pullRequestId': '2',
        'thirdPartyId': 'third-party-pr-2',
        'lastUpdate': '2026-06-19T09:00:00Z',
        'sourceBranch': {'name': 'feature/gitlab'},
        'destinationBranch': {'name': 'main'},
        'provider': {
            'providerId': 'gitlab-jira-connect-gitlab.com',
            'name': 'GitLab',
        },
    }


def graphql_project_by_key_response() -> dict:
    return {
        'data': {
            'jira_projectByIdOrKey': {
                'id': 'ari:cloud:jira:cloud-123:project/10446',
                'key': 'ENG',
                'projectId': '10446',
                'name': 'Engineering',
            }
        }
    }
