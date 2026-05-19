from datetime import datetime, timedelta, timezone
import sys
import time
from types import SimpleNamespace

from click.testing import CliRunner
from pydantic import BaseModel, ConfigDict

from gojeera.cli import cli
from gojeera.internal.auth.oauth2 import OAUTH2_SCOPES
from gojeera.internal.auth.profiles import BasicAuthProfile, OAuth2AuthProfile
from gojeera.internal.auth.service import AuthProfileStatus, AuthValidationResult


def _runner() -> CliRunner:
    return CliRunner()


def _basic_profile(
    *,
    name: str = 'work',
    site: str = 'https://example.atlassian.acme.net',
    email: str = 'testuser@example.com',
) -> BasicAuthProfile:
    return BasicAuthProfile(name=name, site=site, email=email)


def _oauth2_profile(
    *,
    name: str = 'work',
    site: str = 'https://example.atlassian.net',
    cloud_id: str = 'cloud-123',
    account_id: str = '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
    client_id: str = 'client-123',
    display_name: str | None = None,
) -> OAuth2AuthProfile:
    return OAuth2AuthProfile(
        name=name,
        site=site,
        cloud_id=cloud_id,
        account_id=account_id,
        client_id=client_id,
        display_name=display_name,
    )


def _capture_upserted_profile(storage: dict):
    def mock_upsert_profile(profile_name, **kwargs):
        storage['name'] = profile_name
        storage['data'] = kwargs

    return mock_upsert_profile


def _single_basic_profile_listing():
    return (
        'work',
        {'work': _basic_profile()},
    )


def test_auth_login_stores_environment_secrets(monkeypatch):
    runner = _runner()

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

    def mock_set_jira_api_token(api_email, api_token):
        stored['jira'] = (api_email, api_token)

    monkeypatch.setattr('gojeera.cli.upsert_profile', _capture_upserted_profile(profile))
    monkeypatch.setattr('gojeera.cli.set_jira_api_token', mock_set_jira_api_token)

    result = runner.invoke(cli, ['auth', 'login'])

    assert result.exit_code == 0
    assert 'Created profile work.' in result.output
    assert stored['jira'] == ('testuser@example.com', 'env-token')
    assert profile['name'] == 'work'
    assert profile['data']['auth_type'] == 'basic'
    assert profile['data']['client_id'] is None
    assert selector_calls == [('Authentication type', ['basic', 'oauth2'])]


def test_auth_login_requires_basic_credentials(monkeypatch):
    runner = _runner()
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
    runner = _runner()
    monkeypatch.setattr('gojeera.cli.list_profiles', _single_basic_profile_listing)

    removed = {'profile': None}

    def mock_delete_jira_api_token(api_email):
        removed['jira'] = api_email
        return True

    def mock_remove_profile(profile_name):
        removed['profile'] = profile_name
        return {'auth_type': 'basic'}

    monkeypatch.setattr('gojeera.cli.delete_jira_api_token', mock_delete_jira_api_token)
    monkeypatch.setattr('gojeera.cli.remove_profile', mock_remove_profile)

    result = runner.invoke(cli, ['auth', 'logout', 'work'])

    assert result.exit_code == 0
    assert result.output == ''
    assert removed['jira'] == 'testuser@example.com'
    assert removed['profile'] == 'work'


def test_auth_logout_uses_interactive_profile_selection(monkeypatch):
    runner = _runner()
    monkeypatch.setattr('gojeera.cli.list_profiles', _single_basic_profile_listing)
    monkeypatch.setattr('gojeera.cli._select_option', lambda *args, **kwargs: 'work')
    monkeypatch.setattr('gojeera.cli.delete_jira_api_token', lambda *args, **kwargs: True)
    monkeypatch.setattr('gojeera.cli.remove_profile', lambda profile_name: {'auth_type': 'basic'})

    result = runner.invoke(cli, ['auth', 'logout'])

    assert result.exit_code == 0
    assert result.output == ''


def test_auth_status_reports_no_profiles_when_empty(monkeypatch):
    runner = _runner()
    monkeypatch.setattr('gojeera.cli.list_profiles', lambda: (None, {}))

    result = runner.invoke(cli, ['auth', 'status'])

    assert result.exit_code == 0
    assert 'No profiles configured.' in result.output


def test_cli_profile_option_selects_auth_profile(monkeypatch):
    runner = _runner()
    captured = {}

    class DummySettings:
        def __init__(self):
            self.jira = SimpleNamespace(
                active_profile_name='default',
                profiles={'work': object()},
                active_profile=object(),
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

    monkeypatch.setattr('gojeera.internal.store.config.ApplicationConfiguration', DummySettings)
    monkeypatch.setitem(sys.modules, 'gojeera.app', SimpleNamespace(JiraApp=DummyApp))

    result = runner.invoke(cli, ['--profile', 'work'])

    assert result.exit_code == 0
    assert captured['settings'].jira.get_active_profile_name() == 'work'


def test_cli_profile_option_reports_unknown_profile(monkeypatch):
    runner = _runner()

    class DummyJiraSettings:
        def __init__(self):
            self._active_profile = 'default'
            self.profiles = {'default': object()}

    class DummySettings:
        def __init__(self):
            self.jira = DummyJiraSettings()
            self.search_on_startup = False

    monkeypatch.setattr('gojeera.internal.store.config.ApplicationConfiguration', DummySettings)

    result = runner.invoke(cli, ['--profile', 'missing'])

    assert result.exit_code == 1
    assert 'Authentication profile not found: missing' in result.output


def test_cli_reports_missing_auth_configuration(monkeypatch):
    runner = _runner()

    class MissingAuthSettings:
        def __init__(self):
            raise ValueError(
                'No Jira authentication is configured. '
                'Use `gojeera auth login` to configure your credentials.'
            )

    monkeypatch.setattr(
        'gojeera.internal.store.config.ApplicationConfiguration', MissingAuthSettings
    )

    result = runner.invoke(cli, [], color=True)

    assert result.exit_code == 1
    assert '\x1b[31m' in result.output
    assert (
        'No Jira credentials are configured. '
        'Use `gojeera auth login` to configure your credentials.' in result.output
    )
    assert (
        'Configuration validation error. Make sure your config file is correct.'
        not in result.output
    )
    assert 'Configuration error:' not in result.output
    assert 'jira.api_base_url is required for basic authentication.' not in result.output


def test_cli_reports_configuration_validation_errors_in_red(monkeypatch):
    runner = _runner()

    class InvalidConfigSettings:
        def __init__(self):
            raise ValueError('jira.api_base_url is required for basic authentication.')

    monkeypatch.setattr(
        'gojeera.internal.store.config.ApplicationConfiguration', InvalidConfigSettings
    )

    result = runner.invoke(cli, [], color=True)

    assert result.exit_code == 1
    assert '\x1b[31m' in result.output
    assert 'Configuration validation error. Make sure your config file is correct.' in result.output
    assert (
        'Configuration error: jira.api_base_url is required for basic authentication.'
        in result.output
    )


def test_cli_reports_invalid_auth_profile_with_actionable_message(monkeypatch):
    runner = _runner()

    class InvalidProfileSettings:
        def __init__(self):
            raise ValueError('Invalid auth profile "default": unexpected field "asite"')

    monkeypatch.setattr(
        'gojeera.internal.store.config.ApplicationConfiguration', InvalidProfileSettings
    )

    result = runner.invoke(cli, [], color=True)

    assert result.exit_code == 1
    assert 'Invalid auth profile "default": unexpected field "asite".' in result.output
    assert (
        'Configuration validation error. Make sure your config file is correct.'
        not in result.output
    )


def test_cli_reports_invalid_configuration_field_concisely(monkeypatch):
    runner = _runner()

    class InvalidConfigSettings:
        def __init__(self):
            class FilterModel(BaseModel):
                model_config = ConfigDict(extra='forbid')

                label: str
                expression: str

            class StrictConfigModel(BaseModel):
                model_config = ConfigDict(extra='forbid')

                jql_filters: list[FilterModel]

            StrictConfigModel.model_validate(
                {'jql_filters': [{'label': 'Mine', 'expression': 'x', 'a': 'oops'}]}
            )

    monkeypatch.setattr(
        'gojeera.internal.store.config.ApplicationConfiguration', InvalidConfigSettings
    )

    result = runner.invoke(cli, [], color=True)

    assert result.exit_code == 1
    assert 'Invalid configuration field "jql_filters[0].a".' in result.output
    assert (
        'Configuration validation error. Make sure your config file is correct.'
        not in result.output
    )


def test_cli_reports_invalid_theme_file_and_exits(monkeypatch):
    runner = _runner()

    class DummySettings:
        def __init__(self):
            self.jira = SimpleNamespace(
                active_profile_name='default',
                profiles={},
                active_profile=None,
            )
            self.search_on_startup = False

    class DummyApp:
        def __init__(self, settings, **kwargs):
            pass

        def run(self):
            raise ValueError(
                'Invalid theme file "broken.yaml": Theme configuration contains unexpected field \'naaame\''
            )

    monkeypatch.setattr('gojeera.internal.store.config.ApplicationConfiguration', DummySettings)
    monkeypatch.setitem(sys.modules, 'gojeera.app', SimpleNamespace(JiraApp=DummyApp))

    result = runner.invoke(cli, [], color=True)

    assert result.exit_code == 1
    assert (
        'Invalid theme file "broken.yaml": Theme configuration contains unexpected field \'naaame\'.'
        in result.output
    )


def test_auth_status_reports_profiles_and_keyring_state(monkeypatch):
    runner = _runner()
    monkeypatch.setattr('gojeera.cli.list_profiles', _single_basic_profile_listing)
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
    assert '- Authentication type: API token' in result.output
    assert '- Token: ********' in result.output
    assert '- Token source:' not in result.output


def test_auth_status_checks_multiple_profiles_concurrently_in_output_order(monkeypatch):
    runner = _runner()
    first_profile = _basic_profile(name='first', site='https://first.atlassian.net')
    second_profile = _basic_profile(name='second', site='https://second.atlassian.net')

    monkeypatch.setattr(
        'gojeera.cli.list_profiles',
        lambda: ('first', {'first': first_profile, 'second': second_profile}),
    )

    def get_profile_status(profile_name, profile, *, active_profile_name):
        if profile_name == 'first':
            time.sleep(0.05)
        return AuthProfileStatus(
            profile_name=profile_name,
            profile=profile,
            is_active=profile_name == active_profile_name,
            token_source='keyring',
            token=f'{profile_name}-token',
            validation=AuthValidationResult(True, f'{profile_name.title()} User'),
        )

    monkeypatch.setattr(
        'gojeera.cli.auth_service',
        SimpleNamespace(get_profile_status=get_profile_status),
    )

    result = runner.invoke(cli, ['auth', 'status'])

    assert result.exit_code == 0
    assert result.output.index('https://first.atlassian.net') < result.output.index(
        'https://second.atlassian.net'
    )
    assert 'Logged in as First User (keyring)' in result.output
    assert 'Logged in as Second User (keyring)' in result.output


def test_auth_status_refreshes_expired_oauth2_access_token(monkeypatch):
    runner = _runner()
    status_calls = {}

    monkeypatch.setattr(
        'gojeera.cli.list_profiles',
        lambda: (
            'work',
            {'work': _oauth2_profile()},
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
                        'site': profile.site,
                        'cloud_id': profile.cloud_id,
                        'account_id': profile.account_id,
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
        'site': 'https://example.atlassian.net',
        'cloud_id': 'cloud-123',
        'account_id': '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        'client_id': 'client-123',
    }


def test_auth_login_runs_oauth2_browser_flow(monkeypatch):
    runner = _runner()

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
                    'expires_in': 3600,
                    'access_token_expiration_timestamp': 1234567890,
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
            validate_profile=lambda profile, **kwargs: AuthValidationResult(
                True,
                'OAuth User',
                account_id='712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
            ),
            get_oauth2_client_secret=lambda profile, **kwargs: None,
            get_oauth2_client_id=lambda profile, **kwargs: None,
        ),
    )

    def mock_upsert_profile(profile_name, **kwargs):
        profile['name'] = profile_name
        profile['data'] = kwargs

    def mock_set_jira_oauth2_refresh_token(account_id, refresh_token):
        stored['refresh'] = (account_id, refresh_token)

    def mock_set_jira_oauth2_client_secret(account_id, client_secret):
        stored['client_secret'] = (account_id, client_secret)

    def mock_set_jira_oauth2_client_id(account_id, client_id):
        stored['client_id'] = (account_id, client_id)

    monkeypatch.setattr('gojeera.cli.upsert_profile', mock_upsert_profile)
    monkeypatch.setattr(
        'gojeera.cli.set_jira_oauth2_refresh_token', mock_set_jira_oauth2_refresh_token
    )
    monkeypatch.setattr(
        'gojeera.cli.set_jira_oauth2_client_secret', mock_set_jira_oauth2_client_secret
    )
    monkeypatch.setattr('gojeera.cli.set_jira_oauth2_client_id', mock_set_jira_oauth2_client_id)

    result = runner.invoke(cli, ['auth', 'login'])

    assert result.exit_code == 0
    assert 'Selected Atlassian site: Example https://example.atlassian.net' in result.output
    assert stored['refresh'] == (
        '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        'oauth-refresh-token',
    )
    assert stored['client_secret'] == (
        '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        'secret-123',
    )
    assert stored['client_id'] == (
        '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        'client-123',
    )
    assert profile['data']['auth_type'] == 'oauth2'
    assert profile['name'] == 'work'
    assert profile['data']['cloud_id'] == 'cloud-123'
    assert profile['data']['account_id'] == '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857'
    assert profile['data']['client_id'] == 'client-123'
    assert profile['data']['oauth2_access_token_expiration_timestamp'] is not None
    assert 'scopes' not in profile['data']
    assert selector_calls == [('Authentication type', ['basic', 'oauth2'])]
    assert flow_calls == {
        'client_id': 'client-123',
        'client_secret': 'secret-123',
        'scopes': OAUTH2_SCOPES,
        'redirect_uri': 'http://127.0.0.1:49152/callback',
        'authorization_url': 'https://auth.atlassian.com/authorize',
    }


def test_refresh_oauth2_access_token_on_startup_updates_settings(monkeypatch):
    profile = _oauth2_profile().model_copy(
        update={
            'oauth2_access_token_expiration_timestamp': int(
                (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
            )
        }
    )
    updates = {}
    settings = SimpleNamespace(
        jira=SimpleNamespace(
            active_profile=profile,
            oauth2_access_token=None,
            update_active_oauth2_session=lambda **kwargs: updates.update(kwargs),
        )
    )

    monkeypatch.setattr(
        'gojeera.cli.auth_service',
        SimpleNamespace(
            should_refresh_oauth2_access_token_on_startup=lambda current_profile: True,
            refresh_oauth2_access_token=lambda current_profile: SimpleNamespace(
                access_token='fresh-access-token',
                refresh_token='fresh-refresh-token',
                expires_in=7200,
                access_token_expiration_timestamp=1234567890,
            ),
        ),
    )

    from gojeera.cli import _refresh_oauth2_access_token_on_startup

    _refresh_oauth2_access_token_on_startup(settings)

    assert updates['access_token'] == 'fresh-access-token'
    assert updates['refresh_token'] == 'fresh-refresh-token'
    assert updates['oauth2_access_token_expiration_timestamp'] is not None


def test_auth_edit_oauth2_profile_skips_browser_flow_when_credentials_unchanged(monkeypatch):
    runner = _runner()

    profile = {}
    flow_calls = {}
    prompt_values = iter(['client-123', ''])

    monkeypatch.setattr(
        'gojeera.cli.list_profiles',
        lambda: (
            'work',
            {'work': _oauth2_profile(display_name='OAuth User')},
        ),
    )
    monkeypatch.setattr('gojeera.cli.Prompt.ask', lambda *args, **kwargs: next(prompt_values))
    monkeypatch.setattr('gojeera.cli.Confirm.ask', lambda *args, **kwargs: True)
    monkeypatch.setattr(
        'gojeera.cli._resolve_existing_profile_selection',
        lambda: (
            'work',
            _oauth2_profile(display_name='OAuth User'),
            True,
        ),
    )
    monkeypatch.setattr('gojeera.cli._select_option', lambda *args, **kwargs: 'oauth2')
    monkeypatch.setattr(
        'gojeera.cli._run_oauth2_login_flow',
        lambda **kwargs: flow_calls.update(kwargs),
    )

    monkeypatch.setattr('gojeera.cli.upsert_profile', _capture_upserted_profile(profile))

    result = runner.invoke(cli, ['auth', 'login'])

    assert result.exit_code == 0
    assert flow_calls == {}
    assert profile['name'] == 'work'
    assert profile['data']['site'] == 'https://example.atlassian.net'
    assert profile['data']['account_id'] == '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857'
    assert profile['data']['display_name'] == 'OAuth User'


def test_auth_edit_basic_profile_skips_validation_when_credentials_unchanged(monkeypatch):
    runner = _runner()

    profile = {}
    validate_calls = {}
    prompt_values = iter(['https://example.atlassian.acme.net', 'testuser@example.com', ''])

    monkeypatch.setattr(
        'gojeera.cli._resolve_existing_profile_selection',
        lambda: (
            'work',
            _basic_profile(),
            True,
        ),
    )
    monkeypatch.setattr('gojeera.cli.Prompt.ask', lambda *args, **kwargs: next(prompt_values))
    monkeypatch.setattr('gojeera.cli.Confirm.ask', lambda *args, **kwargs: True)
    monkeypatch.setattr('gojeera.cli._select_option', lambda *args, **kwargs: 'basic')
    monkeypatch.setattr(
        'gojeera.cli.auth_service',
        SimpleNamespace(
            validate_profile=lambda *args, **kwargs: validate_calls.update(called=True),
            get_basic_api_token=lambda *args, **kwargs: 'existing-token',
        ),
    )

    monkeypatch.setattr('gojeera.cli.upsert_profile', _capture_upserted_profile(profile))

    result = runner.invoke(cli, ['auth', 'login'])

    assert result.exit_code == 0
    assert validate_calls == {}
    assert profile['name'] == 'work'
    assert profile['data']['site'] == 'https://example.atlassian.acme.net'
    assert profile['data']['email'] == 'testuser@example.com'
