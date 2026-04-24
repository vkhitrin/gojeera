from pydantic import SecretStr, ValidationError
import pytest

from gojeera.config import ApplicationConfiguration


def test_keyring_token_is_used_when_env_token_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(tmp_path / 'auth_profiles.yaml'))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.setenv('GOJEERA_JIRA__API_EMAIL', 'testuser@example.com')
    monkeypatch.setenv('GOJEERA_JIRA__API_BASE_URL', 'https://example.atlassian.acme.net')
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)

    monkeypatch.setattr(
        'gojeera.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {'api_token': 'keyring-token'},
    )

    config = ApplicationConfiguration()

    assert config.jira.api_token == SecretStr('keyring-token')


def test_env_token_overrides_keyring(monkeypatch, tmp_path):
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(tmp_path / 'auth_profiles.yaml'))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.setenv('GOJEERA_JIRA__API_EMAIL', 'testuser@example.com')
    monkeypatch.setenv('GOJEERA_JIRA__API_BASE_URL', 'https://example.atlassian.acme.net')
    monkeypatch.setenv('GOJEERA_JIRA__API_TOKEN', 'env-token')

    monkeypatch.setattr(
        'gojeera.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {'api_token': 'keyring-token'},
    )

    config = ApplicationConfiguration()

    assert config.jira.api_token == SecretStr('env-token')


def test_missing_token_raises_configuration_error(monkeypatch, tmp_path):
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(tmp_path / 'auth_profiles.yaml'))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.setenv('GOJEERA_JIRA__API_EMAIL', 'testuser@example.com')
    monkeypatch.setenv('GOJEERA_JIRA__API_BASE_URL', 'https://example.atlassian.acme.net')
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)
    monkeypatch.setattr(
        'gojeera.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {},
    )

    with pytest.raises(Exception, match='jira.api_token is required'):
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
        'gojeera.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {},
    )

    with pytest.raises(ValidationError):
        ApplicationConfiguration()


def test_oauth2_refresh_token_is_loaded_from_keyring(monkeypatch, tmp_path):
    config_file = tmp_path / 'gojeera.yaml'
    config_file.write_text(
        '\n'.join(
            [
                'jira:',
                '  active_profile: "work"',
                '  profiles:',
                '    work:',
                '      auth_type: "oauth2"',
                '      instance_url: "https://example.atlassian.net"',
                '      cloud_id: "cloud-123"',
            ]
        )
    )
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(config_file))
    monkeypatch.setenv('GOJEERA_JIRA__AUTH_TYPE', 'oauth2')
    monkeypatch.setenv('GOJEERA_JIRA__API_BASE_URL', 'https://example.atlassian.net')
    monkeypatch.setenv('GOJEERA_JIRA__CLOUD_ID', 'cloud-123')
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN', raising=False)
    monkeypatch.setattr(
        'gojeera.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {
            'oauth2_access_token': 'access-token',
            'oauth2_refresh_token': 'refresh-token',
        },
    )

    config = ApplicationConfiguration()

    assert config.jira.oauth2_access_token == SecretStr('access-token')
    assert config.jira.oauth2_refresh_token == SecretStr('refresh-token')
    assert config.jira.oauth2_redirect_uri == 'http://127.0.0.1:49152/callback'


def test_activate_profile_reloads_basic_secret_and_resolves_profile_fields(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    profiles_file.write_text(
        '\n'.join(
            [
                'active_profile: oauth',
                'profiles:',
                '  oauth:',
                '    auth_type: "oauth2"',
                '    instance_url: "https://example.atlassian.net"',
                '    cloud_id: "cloud-123"',
                '  basic:',
                '    auth_type: "basic"',
                '    instance_url: "https://example.atlassian.acme.net"',
                '    email: "basic@example.com"',
            ]
        )
    )
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET', raising=False)
    monkeypatch.setattr(
        'gojeera.config.AUTH_SERVICE.get_runtime_secrets',
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
    profiles_file.write_text(
        '\n'.join(
            [
                'active_profile: null',
                'profiles:',
                '  default:',
                '    auth_type: "oauth2"',
                '    instance_url: "https://example.atlassian.net"',
                '    cloud_id: "cloud-123"',
            ]
        )
    )
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(tmp_path / 'gojeera.yaml'))
    monkeypatch.delenv('GOJEERA_JIRA__API_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN', raising=False)
    monkeypatch.delenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET', raising=False)
    monkeypatch.setattr(
        'gojeera.config.AUTH_SERVICE.get_runtime_secrets',
        lambda profile, **kwargs: {'oauth2_access_token': 'oauth-access-token'},
    )

    with pytest.raises(Exception, match='jira.active_profile is required'):
        ApplicationConfiguration()
