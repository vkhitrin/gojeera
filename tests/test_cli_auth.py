import sys
from types import SimpleNamespace

from click.testing import CliRunner

from gojeera.auth_profiles import BasicAuthProfile, OAuth2AuthProfile
from gojeera.auth_service import AuthProfileStatus, AuthValidationResult
from gojeera.cli import cli


def test_auth_login_stores_environment_secrets(monkeypatch):
    runner = CliRunner()

    stored = {}
    profile = {}
    selector_calls = []

    prompt_values = iter(
        [
            'work',
            'https://example.atlassian.acme.net',
            'testuser@example.com',
            'env-token',
        ]
    )

    monkeypatch.setattr('gojeera.cli.list_profiles', lambda: (None, {}))
    monkeypatch.setattr('gojeera.cli.Prompt.ask', lambda *args, **kwargs: next(prompt_values))
    monkeypatch.setattr('gojeera.cli.Confirm.ask', lambda *args, **kwargs: True)
    monkeypatch.setattr(
        'gojeera.cli._select_option',
        lambda title, options, **kwargs: (
            selector_calls.append((title, [value for value, _ in options])),
            'basic',
        )[1],
    )
    monkeypatch.setattr(
        'gojeera.cli.auth_service',
        SimpleNamespace(
            validate_profile=lambda profile, **kwargs: AuthValidationResult(True, 'Test User'),
            get_basic_api_token=lambda profile, **kwargs: None,
        ),
    )

    def mock_set_jira_api_token(base_url, api_email, api_token):
        stored['jira'] = (base_url, api_email, api_token)

    def mock_upsert_profile(profile_name, **kwargs):
        profile['name'] = profile_name
        profile['data'] = kwargs

    monkeypatch.setattr('gojeera.cli.upsert_profile', mock_upsert_profile)
    monkeypatch.setattr('gojeera.cli.set_jira_api_token', mock_set_jira_api_token)

    result = runner.invoke(cli, ['auth', 'login'])

    assert result.exit_code == 0
    assert 'Created profile work.' in result.output
    assert stored['jira'] == (
        'https://example.atlassian.acme.net',
        'testuser@example.com',
        'env-token',
    )
    assert profile['name'] == 'work'
    assert profile['data']['auth_type'] == 'basic'
    assert profile['data']['client_id'] is None
    assert selector_calls == [('Authentication type', ['basic', 'oauth2'])]


def test_auth_login_requires_basic_credentials(monkeypatch):
    runner = CliRunner()
    prompt_values = iter(
        [
            'work',
            'https://example.atlassian.acme.net',
            '',
            '',
        ]
    )
    monkeypatch.setattr('gojeera.cli.list_profiles', lambda: (None, {}))
    monkeypatch.setattr('gojeera.cli.Prompt.ask', lambda *args, **kwargs: next(prompt_values))
    monkeypatch.setattr('gojeera.cli.Confirm.ask', lambda *args, **kwargs: True)
    monkeypatch.setattr('gojeera.cli._select_option', lambda *args, **kwargs: 'basic')

    result = runner.invoke(cli, ['auth', 'login'])

    assert result.exit_code == 1
    assert 'Email and Jira API token are required.' in result.output


def test_auth_logout_removes_profile_and_stored_secrets(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(
        'gojeera.cli.list_profiles',
        lambda: (
            'work',
            {
                'work': BasicAuthProfile(
                    name='work',
                    instance_url='https://example.atlassian.acme.net',
                    email='testuser@example.com',
                )
            },
        ),
    )

    removed = {'profile': None}

    def mock_delete_jira_api_token(base_url, api_email):
        removed['jira'] = (base_url, api_email)
        return True

    def mock_remove_profile(profile_name):
        removed['profile'] = profile_name
        return {'auth_type': 'basic'}

    monkeypatch.setattr('gojeera.cli.delete_jira_api_token', mock_delete_jira_api_token)
    monkeypatch.setattr('gojeera.cli.remove_profile', mock_remove_profile)

    result = runner.invoke(cli, ['auth', 'logout', 'work'])

    assert result.exit_code == 0
    assert result.output == ''
    assert removed['jira'] == ('https://example.atlassian.acme.net', 'testuser@example.com')
    assert removed['profile'] == 'work'


def test_auth_logout_uses_interactive_profile_selection(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(
        'gojeera.cli.list_profiles',
        lambda: (
            'work',
            {
                'work': BasicAuthProfile(
                    name='work',
                    instance_url='https://example.atlassian.acme.net',
                    email='testuser@example.com',
                )
            },
        ),
    )
    monkeypatch.setattr('gojeera.cli._select_option', lambda *args, **kwargs: 'work')
    monkeypatch.setattr('gojeera.cli.delete_jira_api_token', lambda *args, **kwargs: True)
    monkeypatch.setattr('gojeera.cli.remove_profile', lambda profile_name: {'auth_type': 'basic'})

    result = runner.invoke(cli, ['auth', 'logout'])

    assert result.exit_code == 0
    assert result.output == ''


def test_auth_status_reports_no_profiles_when_empty(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr('gojeera.cli.list_profiles', lambda: (None, {}))

    result = runner.invoke(cli, ['auth', 'status'])

    assert result.exit_code == 0
    assert 'No profiles configured.' in result.output


def test_cli_profile_option_selects_auth_profile(monkeypatch):
    runner = CliRunner()
    captured = {}

    class DummySettings:
        def __init__(self):
            self.jira = SimpleNamespace(
                active_profile_name='default',
                profiles={'work': object()},
                activate_profile=lambda profile_name: setattr(
                    self.jira, 'active_profile_name', profile_name
                ),
                get_active_profile_name=lambda: self.jira.active_profile_name,
            )
            self.search_on_startup = False

    class DummyApp:
        def __init__(self, settings, **kwargs):
            captured['settings'] = settings

        def run(self):
            return None

    monkeypatch.setattr('gojeera.config.ApplicationConfiguration', DummySettings)
    monkeypatch.setitem(sys.modules, 'gojeera.app', SimpleNamespace(JiraApp=DummyApp))

    result = runner.invoke(cli, ['--profile', 'work'])

    assert result.exit_code == 0
    assert captured['settings'].jira.get_active_profile_name() == 'work'


def test_cli_profile_option_reports_unknown_profile(monkeypatch):
    runner = CliRunner()

    class DummyJiraSettings:
        def __init__(self):
            self._active_profile = 'default'
            self.profiles = {'default': object()}

    class DummySettings:
        def __init__(self):
            self.jira = DummyJiraSettings()
            self.search_on_startup = False

    monkeypatch.setattr('gojeera.config.ApplicationConfiguration', DummySettings)

    result = runner.invoke(cli, ['--profile', 'missing'])

    assert result.exit_code == 1
    assert 'Authentication profile not found: missing' in result.output


def test_auth_status_reports_profiles_and_keyring_state(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(
        'gojeera.cli.list_profiles',
        lambda: (
            'work',
            {
                'work': BasicAuthProfile(
                    name='work',
                    instance_url='https://example.atlassian.acme.net',
                    email='testuser@example.com',
                )
            },
        ),
    )
    monkeypatch.setattr(
        'gojeera.cli.auth_service',
        SimpleNamespace(
            get_profile_status=lambda profile_name, profile, *, active_profile_name: (
                AuthProfileStatus(
                    profile_name=profile_name,
                    profile=profile,
                    is_active=profile_name == active_profile_name,
                    token_source='keyring',
                    token='keyring-token',
                    validation=AuthValidationResult(True, 'Test User'),
                )
            ),
        ),
    )

    result = runner.invoke(cli, ['auth', 'status'])

    assert result.exit_code == 0
    assert 'https://example.atlassian.acme.net' in result.output
    assert 'Logged in as Test User (keyring)' in result.output
    assert '- Profile: work' in result.output
    assert '- Active profile: true' in result.output
    assert '- Authentication type: Basic' in result.output
    assert '- Token: ********' in result.output
    assert '- Token source:' not in result.output


def test_auth_status_refreshes_expired_oauth2_access_token(monkeypatch):
    runner = CliRunner()
    status_calls = {}

    monkeypatch.setattr(
        'gojeera.cli.list_profiles',
        lambda: (
            'work',
            {
                'work': OAuth2AuthProfile(
                    name='work',
                    instance_url='https://example.atlassian.net',
                    cloud_id='cloud-123',
                    client_id='client-123',
                )
            },
        ),
    )

    monkeypatch.setattr(
        'gojeera.cli.auth_service',
        SimpleNamespace(
            get_profile_status=lambda profile_name, profile, *, active_profile_name: (
                status_calls.update(
                    {
                        'profile_name': profile_name,
                        'active_profile_name': active_profile_name,
                        'instance_url': profile.instance_url,
                        'cloud_id': profile.cloud_id,
                        'client_id': profile.client_id,
                    }
                ),
                AuthProfileStatus(
                    profile_name=profile_name,
                    profile=profile,
                    is_active=True,
                    token_source='keyring',
                    token='fresh-token',
                    validation=AuthValidationResult(True, 'OAuth User'),
                ),
            )[1],
        ),
    )

    result = runner.invoke(cli, ['auth', 'status'])

    assert result.exit_code == 0
    assert 'Logged in as OAuth User (keyring)' in result.output
    assert status_calls == {
        'profile_name': 'work',
        'active_profile_name': 'work',
        'instance_url': 'https://example.atlassian.net',
        'cloud_id': 'cloud-123',
        'client_id': 'client-123',
    }


def test_auth_login_runs_oauth2_browser_flow(monkeypatch):
    runner = CliRunner()

    stored = {}
    profile = {}
    selector_calls = []
    flow_calls = {}
    prompt_values = iter(
        [
            'work',
            'client-123',
            'secret-123',
        ]
    )

    monkeypatch.setattr('gojeera.cli.list_profiles', lambda: (None, {}))
    monkeypatch.setattr('gojeera.cli.Prompt.ask', lambda *args, **kwargs: next(prompt_values))
    monkeypatch.setattr('gojeera.cli.Confirm.ask', lambda *args, **kwargs: True)
    select_values = iter(['oauth2'])
    monkeypatch.setattr(
        'gojeera.cli._select_option',
        lambda title, options, **kwargs: (
            selector_calls.append((title, [value for value, _ in options])),
            next(select_values),
        )[1],
    )
    monkeypatch.setattr(
        'gojeera.cli._run_oauth2_login_flow',
        lambda **kwargs: (
            flow_calls.update(kwargs),
            type(
                'TokenResponse',
                (),
                {
                    'access_token': 'oauth-access-token',
                    'refresh_token': 'oauth-refresh-token',
                },
            )(),
        )[1],
    )
    monkeypatch.setattr(
        'gojeera.cli.get_atlassian_accessible_resources',
        lambda access_token: [
            type(
                'Resource',
                (),
                {'id': 'cloud-123', 'name': 'Example', 'url': 'https://example.atlassian.net'},
            )()
        ],
    )
    monkeypatch.setattr(
        'gojeera.cli.auth_service',
        SimpleNamespace(
            validate_profile=lambda profile, **kwargs: AuthValidationResult(True, 'OAuth User'),
            get_oauth2_client_secret=lambda profile, **kwargs: None,
        ),
    )

    def mock_upsert_profile(profile_name, **kwargs):
        profile['name'] = profile_name
        profile['data'] = kwargs

    def mock_set_jira_oauth2_access_token(base_url, cloud_id, access_token):
        stored['oauth2'] = (base_url, cloud_id, access_token)

    def mock_set_jira_oauth2_refresh_token(base_url, cloud_id, refresh_token):
        stored['refresh'] = (base_url, cloud_id, refresh_token)

    def mock_set_jira_oauth2_client_secret(base_url, cloud_id, client_secret):
        stored['client_secret'] = (base_url, cloud_id, client_secret)

    monkeypatch.setattr('gojeera.cli.upsert_profile', mock_upsert_profile)
    monkeypatch.setattr(
        'gojeera.cli.set_jira_oauth2_access_token', mock_set_jira_oauth2_access_token
    )
    monkeypatch.setattr(
        'gojeera.cli.set_jira_oauth2_refresh_token', mock_set_jira_oauth2_refresh_token
    )
    monkeypatch.setattr(
        'gojeera.cli.set_jira_oauth2_client_secret', mock_set_jira_oauth2_client_secret
    )

    result = runner.invoke(cli, ['auth', 'login'])

    assert result.exit_code == 0
    assert stored['oauth2'] == (
        'https://example.atlassian.net',
        'cloud-123',
        'oauth-access-token',
    )
    assert stored['refresh'] == (
        'https://example.atlassian.net',
        'cloud-123',
        'oauth-refresh-token',
    )
    assert stored['client_secret'] == (
        'https://example.atlassian.net',
        'cloud-123',
        'secret-123',
    )
    assert profile['data']['auth_type'] == 'oauth2'
    assert profile['data']['cloud_id'] == 'cloud-123'
    assert profile['data']['client_id'] == 'client-123'
    assert profile['data']['scopes'] == [
        'read:jira-user',
        'read:jira-work',
        'write:jira-work',
        'manage:jira-data-provider',
        'read:servicedesk-request',
        'read:servicemanagement-insight-objects',
        'offline_access',
        'read:me',
        'read:account',
    ]
    assert selector_calls == [('Authentication type', ['basic', 'oauth2'])]
    assert flow_calls == {
        'client_id': 'client-123',
        'client_secret': 'secret-123',
        'scopes': [
            'read:jira-user',
            'read:jira-work',
            'write:jira-work',
            'manage:jira-data-provider',
            'read:servicedesk-request',
            'read:servicemanagement-insight-objects',
            'offline_access',
            'read:me',
            'read:account',
        ],
        'redirect_uri': 'http://127.0.0.1:49152/callback',
        'authorization_url': 'https://auth.atlassian.com/authorize',
    }
