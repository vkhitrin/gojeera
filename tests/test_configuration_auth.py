from pydantic import SecretStr, ValidationError
import pytest

from tests.config_test_helpers import write_config_and_set_basic_auth, write_custom_theme_config

from gojeera.internal.store.config import ApplicationConfiguration

OAUTH2_PROFILE_ID = 'cloud-123:account-123'


def _set_profile_registry_env(monkeypatch, profiles_file, tmp_path) -> None:
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_CLIENT_ID', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET', raising=False)


def _set_runtime_secrets_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr('gojeera.internal.store.config.AUTH_SERVICE.get_runtime_secrets', provider)


def _write_auth_profiles_file(profiles_file, *lines: str) -> None:
    profiles_file.write_text('\n'.join(lines))


def _write_acli_oauth_profile(
    profiles_file,
    *,
    current_profile: str | None = OAUTH2_PROFILE_ID,
    extra_profile_lines: tuple[str, ...] = (),
    extra_profiles: tuple[str, ...] = (),
) -> None:
    _write_auth_profiles_file(
        profiles_file,
        f'current_profile: "{current_profile}"'
        if current_profile is not None
        else 'current_profile: null',
        'profiles:',
        '  - auth_type: "oauth"',
        '    site: "https://example.atlassian.net"',
        '    cloud_id: "cloud-123"',
        '    account_id: "account-123"',
        *extra_profile_lines,
        *extra_profiles,
    )


def _set_basic_auth_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(tmp_path / 'auth_profiles.yaml'))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.setenv('GOJEERA_JIRA__API_EMAIL', 'testuser@example.com')
    monkeypatch.setenv('GOJEERA_JIRA__API_BASE_URL', 'https://example.atlassian.acme.net')


def test_keyring_token_is_used_when_env_token_is_missing(monkeypatch, tmp_path):
    _set_basic_auth_env(monkeypatch, tmp_path)
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)

    monkeypatch.setattr(
        'gojeera.internal.store.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {'api_token': 'keyring-token'},
    )

    config = ApplicationConfiguration()

    assert config.jira.api_token == SecretStr('keyring-token')


def test_env_token_overrides_keyring(monkeypatch, tmp_path):
    _set_basic_auth_env(monkeypatch, tmp_path)
    monkeypatch.setenv('GOJEERA_JIRA__API_TOKEN', 'env-token')

    monkeypatch.setattr(
        'gojeera.internal.store.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {'api_token': 'keyring-token'},
    )

    config = ApplicationConfiguration()

    assert config.jira.api_token == SecretStr('env-token')


def test_missing_token_raises_configuration_error(monkeypatch, tmp_path):
    _set_basic_auth_env(monkeypatch, tmp_path)
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)
    monkeypatch.setattr(
        'gojeera.internal.store.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {},
    )

    with pytest.raises(Exception, match='jira.api_token is required'):
        ApplicationConfiguration()


def test_missing_auth_configuration_raises_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(tmp_path / 'auth_profiles.yaml'))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.delenv('GOJEERA_JIRA__AUTH_TYPE', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__API_EMAIL', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__API_BASE_URL', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__CLOUD_ID', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_CLIENT_ID', raising=False)
    monkeypatch.setattr(
        'gojeera.internal.store.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {},
    )

    with pytest.raises(Exception, match='No Jira authentication is configured'):
        ApplicationConfiguration()


def test_yaml_jira_authentication_is_ignored(monkeypatch, tmp_path):
    config_file = tmp_path / 'gojeera.yaml'
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(tmp_path / 'auth_profiles.yaml'))
    config_file.write_text(
        '\n'.join(
            [
                'jira:',
                '  api_email: "yaml@example.com"',
                '  api_token: "yaml-token"',
                '  api_base_url: "https://yaml.example.atlassian.net"',
            ]
        )
    )
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(config_file))
    monkeypatch.delenv('GOJEERA_JIRA__API_EMAIL', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__API_BASE_URL', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)
    monkeypatch.setattr(
        'gojeera.internal.store.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {},
    )

    with pytest.raises(ValidationError):
        ApplicationConfiguration()


def test_unknown_top_level_config_field_raises_validation_error(monkeypatch, tmp_path):
    write_config_and_set_basic_auth(monkeypatch, tmp_path, 'thme: "oops"')

    with pytest.raises(ValidationError) as exc_info:
        ApplicationConfiguration()
    assert exc_info.value.errors()[0]['type'] == 'extra_forbidden'
    assert exc_info.value.errors()[0]['loc'] == ('thme',)


def test_unknown_nested_config_field_raises_validation_error(monkeypatch, tmp_path):
    write_config_and_set_basic_auth(monkeypatch, tmp_path, 'fetch_remote_filters:', '  a: true')

    with pytest.raises(ValidationError) as exc_info:
        ApplicationConfiguration()
    assert exc_info.value.errors()[0]['type'] == 'extra_forbidden'
    assert exc_info.value.errors()[0]['loc'] == ('fetch_remote_filters', 'a')


def test_known_nested_config_sections_remain_valid(monkeypatch, tmp_path):
    write_config_and_set_basic_auth(
        monkeypatch,
        tmp_path,
        'fetch_remote_filters:',
        '  enabled: true',
        '  include_shared: true',
        '  starred_only: false',
        '  cache_ttl: 120',
        'jumper:',
        '  enabled: true',
        '  keys: ["q", "w"]',
        'ssl:',
        '  verify_ssl: true',
    )

    config = ApplicationConfiguration()

    assert config.fetch_remote_filters.enabled is True
    assert config.fetch_remote_filters.include_shared is True
    assert config.fetch_remote_filters.cache_ttl == 120
    assert config.jumper.keys == ['q', 'w']
    assert config.ssl is not None
    assert config.ssl.verify_ssl is True


def test_unknown_jql_filter_field_raises_validation_error(monkeypatch, tmp_path):
    write_config_and_set_basic_auth(
        monkeypatch,
        tmp_path,
        'jql_filters:',
        '  - label: "My filter"',
        '    expression: "assignee = currentUser()"',
        '    a: "oops"',
    )

    with pytest.raises(ValidationError) as exc_info:
        ApplicationConfiguration()
    assert exc_info.value.errors()[0]['type'] == 'extra_forbidden'
    assert exc_info.value.errors()[0]['loc'] == ('jql_filters', 0, 'a')


def test_unknown_custom_theme_field_raises_configuration_error(monkeypatch, tmp_path):
    write_custom_theme_config(
        monkeypatch,
        tmp_path,
        '  - name: "custom"',
        '    primary: "#ffffff"',
        '    a: "oops"',
    )

    with pytest.raises(ValueError, match='Invalid configuration field "custom_themes\\[0\\].a"'):
        ApplicationConfiguration()


def test_oauth2_refresh_token_is_loaded_from_keyring(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    _write_acli_oauth_profile(profiles_file)
    _set_profile_registry_env(monkeypatch, profiles_file, tmp_path)
    monkeypatch.setenv('GOJEERA_JIRA__AUTH_TYPE', 'oauth2')
    monkeypatch.setenv('GOJEERA_JIRA__API_BASE_URL', 'https://example.atlassian.net')
    monkeypatch.setenv('GOJEERA_JIRA__CLOUD_ID', 'cloud-123')
    monkeypatch.setattr(
        'gojeera.internal.store.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {
            'oauth2_refresh_token': 'refresh-token',
            'oauth2_client_id': 'client-123',
            'oauth2_client_secret': 'client-secret',
        },
    )

    config = ApplicationConfiguration()

    assert config.jira.get_active_profile_name() == OAUTH2_PROFILE_ID
    assert config.jira.oauth2_access_token is None
    assert config.jira.oauth2_refresh_token == SecretStr('refresh-token')
    assert config.jira.oauth2_client_id == 'client-123'
    assert config.jira.oauth2_client_secret == SecretStr('client-secret')
    assert config.jira.oauth2_redirect_uri == 'http://127.0.0.1:49152/callback'


def test_activate_profile_reloads_basic_secret_and_resolves_profile_fields(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    _write_acli_oauth_profile(
        profiles_file,
        extra_profiles=(
            '  - name: "basic"',
            '    auth_type: "basic"',
            '    site: "https://example.atlassian.acme.net"',
            '    email: "basic@example.com"',
        ),
    )
    _set_profile_registry_env(monkeypatch, profiles_file, tmp_path)
    _set_runtime_secrets_provider(
        monkeypatch,
        lambda profile, **kwargs: (
            {
                'oauth2_access_token': 'oauth-access-token',
                'oauth2_refresh_token': 'oauth-refresh-token',
                'oauth2_client_secret': 'oauth-client-secret',
            }
            if profile.auth_type == 'oauth2'
            else {'api_token': 'basic-api-token'}
        ),
    )

    config = ApplicationConfiguration()

    assert config.jira.auth_type == 'oauth2'
    assert config.jira.require_oauth2_access_token() == 'oauth-access-token'

    config.jira.activate_profile('basic')

    assert config.jira.get_active_profile_name() == 'basic'
    assert config.jira.auth_type == 'basic'
    assert config.jira.api_base_url == 'https://example.atlassian.acme.net'
    assert config.jira.api_email == 'basic@example.com'
    assert config.jira.require_api_token() == 'basic-api-token'
    assert config.jira.oauth2_access_token is None


def test_profiles_require_active_profile_when_registry_exists(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    _write_acli_oauth_profile(profiles_file, current_profile=None)
    _set_profile_registry_env(monkeypatch, profiles_file, tmp_path)
    _set_runtime_secrets_provider(
        monkeypatch,
        lambda profile, **kwargs: {'oauth2_access_token': 'oauth-access-token'},
    )

    with pytest.raises(Exception, match='jira.current_profile is required'):
        ApplicationConfiguration()


def test_invalid_oauth2_profile_field_raises_configuration_error(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    _write_acli_oauth_profile(
        profiles_file,
        extra_profile_lines=('    asite: "unexpected"',),
    )
    _set_profile_registry_env(monkeypatch, profiles_file, tmp_path)
    _set_runtime_secrets_provider(
        monkeypatch,
        lambda profile, **kwargs: {'oauth2_access_token': 'oauth-access-token'},
    )

    with pytest.raises(
        ValueError, match=f'Invalid auth profile "{OAUTH2_PROFILE_ID}": unexpected field "asite"'
    ):
        ApplicationConfiguration()
