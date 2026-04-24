from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from gojeera.auth_profiles import (
    ATLASSIAN_OAUTH2_AUTHORIZATION_URL,
    ATLASSIAN_OAUTH2_REDIRECT_URI,
    ATLASSIAN_OAUTH2_TOKEN_URL,
    AuthProfile,
    BasicAuthProfile,
    OAuth2AuthProfile,
    load_profiles_settings,
)
from gojeera.auth_service import AuthService
from gojeera.files import get_config_file
from gojeera.models import BaseModel

AUTH_SERVICE = AuthService()


class SSLConfiguration(BaseModel):
    """Configuration for SSL CA bundles and client-side certificates."""

    verify_ssl: bool = True
    """Indicates whether HTTP requests should use SSL validation."""
    ca_bundle: str | None = None
    """Path to the CA bundle file."""
    certificate_file: str | None = None
    """Path to the a client-side certificate file, e.g. cert.pem"""
    key_file: str | None = None
    """Path to the key file."""
    password: SecretStr | None = None
    """The password for the key file."""


class RemoteFiltersConfig(BaseModel):
    """Configuration for fetching remote JQL filters from Jira API."""

    enabled: bool = False
    """If enabled, gojeera fetches JQL filters from Jira for the autocomplete dropdown.
    Default: disabled."""
    include_shared: bool = False
    """When enabled, fetch both personal filters and filters shared with you (through groups/projects).
    Otherwise, fetch only filters owned by the current user.
    Default: personal filters only."""
    starred_only: bool = False
    """When enabled, fetch only filters starred by the user. Otherwise, fetch all filters.
    Default: fetch all filters."""
    cache_ttl: int = 3600
    """Time-to-live (in seconds) for cached remote filters. After this time, filters are re-fetched from the server.
    Default: 3600 seconds (1 hour)."""


class JumperConfig(BaseModel):
    """Configuration for the jumper overlay widget."""

    enabled: bool = True
    """If True (default), the jumper overlay is enabled and allows quick navigation between widgets."""
    keys: list[str] = ['q', 'w', 'e', 'a', 's', 'd', 'z', 'x', 'c']
    """List of keys to use for the jumper overlay.

    Default is ['q', 'w', 'e', 'a', 's', 'd', 'z', 'x', 'c'].
    """


@dataclass(frozen=True)
class JiraAuthContext:
    profile_name: str | None
    auth_type: Literal['basic', 'oauth2']
    api_base_url: str
    api_email: str | None = None
    api_token: str | None = None
    bearer_token: str | None = None
    cloud_id: str | None = None
    rest_api_path_prefix: str = '/rest/api/3/'
    agile_api_path_prefix: str = '/rest/agile/1.0/'
    identity_base_url: str | None = None


class JiraConfig(BaseSettings):
    """Configuration for Jira API connection."""

    active_profile_name: str | None = Field(default=None, alias='active_profile')
    """The active Jira authentication profile name."""
    profiles: dict[str, AuthProfile] = Field(default_factory=dict)
    """Named Jira authentication profiles."""
    auth_type_override: Literal['basic', 'oauth2'] | None = Field(default=None, alias='auth_type')
    """Optional override for the resolved authentication type."""
    api_email_override: str | None = Field(default=None, alias='api_email')
    """Optional override for the Jira API email."""
    api_token: SecretStr | None = None
    """The token to use for connecting to the Jira API."""
    oauth2_access_token: SecretStr | None = None
    """The OAuth 2.0 access token to use for connecting to the Jira API."""
    oauth2_refresh_token: SecretStr | None = None
    """The OAuth 2.0 refresh token used to regenerate access tokens."""
    api_base_url_override: str | None = Field(default=None, alias='api_base_url')
    """Optional override for the Jira API base URL."""
    cloud_id_override: str | None = Field(default=None, alias='cloud_id')
    """Optional override for the Atlassian cloud ID used for OAuth 2.0 API requests."""
    oauth2_client_id_override: str | None = Field(default=None, alias='oauth2_client_id')
    """Optional override for the Atlassian 3LO client ID."""
    oauth2_client_secret: SecretStr | None = None
    """OAuth 2.0 client secret for the Atlassian 3LO app."""
    oauth2_scopes_override: list[str] | None = Field(default=None, alias='oauth2_scopes')
    """Optional override for the OAuth 2.0 scopes."""

    def _reload_active_profile_secrets(self) -> None:
        active_profile = self.active_profile
        if active_profile is None:
            object.__setattr__(self, 'api_token', None)
            object.__setattr__(self, 'oauth2_access_token', None)
            object.__setattr__(self, 'oauth2_refresh_token', None)
            object.__setattr__(self, 'oauth2_client_secret', None)
            return

        secrets = AUTH_SERVICE.get_runtime_secrets(active_profile, prefer_environment=True)

        if self.auth_type == 'oauth2':
            object.__setattr__(self, 'api_token', None)
            object.__setattr__(
                self,
                'oauth2_access_token',
                SecretStr(secrets['oauth2_access_token'])
                if 'oauth2_access_token' in secrets
                else None,
            )
            object.__setattr__(
                self,
                'oauth2_refresh_token',
                SecretStr(secrets['oauth2_refresh_token'])
                if 'oauth2_refresh_token' in secrets
                else None,
            )
            object.__setattr__(
                self,
                'oauth2_client_secret',
                SecretStr(secrets['oauth2_client_secret'])
                if 'oauth2_client_secret' in secrets
                else None,
            )
        else:
            object.__setattr__(self, 'oauth2_access_token', None)
            object.__setattr__(self, 'oauth2_refresh_token', None)
            object.__setattr__(self, 'oauth2_client_secret', None)
            object.__setattr__(
                self,
                'api_token',
                SecretStr(secrets['api_token']) if 'api_token' in secrets else None,
            )

    def activate_profile(self, profile_name: str) -> None:
        if profile_name not in self.profiles:
            raise ValueError(f'jira.active_profile "{profile_name}" does not exist.')
        object.__setattr__(self, 'active_profile_name', profile_name)
        self._reload_active_profile_secrets()

    @model_validator(mode='after')
    def resolve_profile(self) -> 'JiraConfig':
        if self.profiles and self.active_profile_name is not None:
            if self.active_profile_name not in self.profiles:
                raise ValueError(
                    f'jira.active_profile "{self.active_profile_name}" does not exist.'
                )
        return self

    def get_active_profile_name(self) -> str | None:
        return self.active_profile_name

    @property
    def active_profile(self) -> BasicAuthProfile | OAuth2AuthProfile | None:
        profile_name = self.get_active_profile_name()
        if profile_name is None:
            return None
        return self.profiles.get(profile_name)

    @property
    def auth_type(self) -> Literal['basic', 'oauth2']:
        if self.auth_type_override is not None:
            return self.auth_type_override
        if self.active_profile is not None:
            return self.active_profile.auth_type
        return 'basic'

    @property
    def api_email(self) -> str | None:
        if self.api_email_override is not None:
            return self.api_email_override
        if isinstance(self.active_profile, BasicAuthProfile):
            return self.active_profile.email
        return None

    @property
    def api_base_url(self) -> str | None:
        if self.api_base_url_override is not None:
            return self.api_base_url_override
        if self.active_profile is not None:
            return self.active_profile.instance_url
        return None

    @property
    def cloud_id(self) -> str | None:
        if self.cloud_id_override is not None:
            return self.cloud_id_override
        if isinstance(self.active_profile, OAuth2AuthProfile):
            return self.active_profile.cloud_id
        return None

    @property
    def oauth2_client_id(self) -> str | None:
        if self.oauth2_client_id_override is not None:
            return self.oauth2_client_id_override
        if isinstance(self.active_profile, OAuth2AuthProfile):
            return self.active_profile.client_id
        return None

    @property
    def oauth2_scopes(self) -> list[str] | None:
        if self.oauth2_scopes_override is not None:
            return self.oauth2_scopes_override
        if isinstance(self.active_profile, OAuth2AuthProfile):
            return self.active_profile.scopes
        return None

    @property
    def oauth2_authorization_url(self) -> str:
        return ATLASSIAN_OAUTH2_AUTHORIZATION_URL

    @property
    def oauth2_token_url(self) -> str:
        return ATLASSIAN_OAUTH2_TOKEN_URL

    @property
    def oauth2_redirect_uri(self) -> str:
        return ATLASSIAN_OAUTH2_REDIRECT_URI

    def require_api_token(self) -> str:
        if self.api_token is None:
            raise ValueError(
                'jira.api_token is required via GOJEERA_JIRA__API_TOKEN or the operating system keyring.'
            )
        return self.api_token.get_secret_value()

    def require_oauth2_access_token(self) -> str:
        if self.oauth2_access_token is None:
            raise ValueError(
                'jira.oauth2_access_token is required via GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN or the operating system keyring.'
            )
        return self.oauth2_access_token.get_secret_value()

    def require_api_base_url(self) -> str:
        if self.api_base_url is None:
            raise ValueError('jira.api_base_url is required.')
        return self.api_base_url

    def require_cloud_id(self) -> str:
        if self.cloud_id is None:
            raise ValueError('jira.cloud_id is required for oauth2 authentication.')
        return self.cloud_id

    def require_api_email(self) -> str:
        if self.api_email is None:
            raise ValueError('jira.api_email is required for basic authentication.')
        return self.api_email

    def build_auth_context(self) -> JiraAuthContext:
        profile_name = self.get_active_profile_name()
        if self.auth_type == 'oauth2':
            cloud_id = self.require_cloud_id()
            return JiraAuthContext(
                profile_name=profile_name,
                auth_type='oauth2',
                api_base_url='https://api.atlassian.com',
                bearer_token=self.require_oauth2_access_token(),
                cloud_id=cloud_id,
                rest_api_path_prefix=f'/ex/jira/{cloud_id}/rest/api/3/',
                agile_api_path_prefix=f'/ex/jira/{cloud_id}/rest/agile/1.0/',
                identity_base_url='https://api.atlassian.com',
            )

        return JiraAuthContext(
            profile_name=profile_name,
            auth_type='basic',
            api_base_url=self.require_api_base_url(),
            api_email=self.require_api_email(),
            api_token=self.require_api_token(),
        )

    model_config = SettingsConfigDict(
        env_prefix='GOJEERA_JIRA__',
        populate_by_name=True,
        validate_assignment=True,
        extra='ignore',  # Ignore extra env vars that don't match our fields
    )


class ApplicationConfiguration(BaseSettings):
    """The configuration for the gojeera application and CLI tool."""

    jira: JiraConfig = Field(default_factory=JiraConfig)
    """Jira API connection configuration."""

    @field_validator('jira', mode='before')
    @classmethod
    def validate_jira_config(cls, v):
        """Ensure jira config has properly validated nested fields."""
        if isinstance(v, dict):
            if 'api_token' in v and isinstance(v['api_token'], str):
                v = v.copy()
                v['api_token'] = SecretStr(v['api_token'])
            if 'oauth2_access_token' in v and isinstance(v['oauth2_access_token'], str):
                v = v.copy()
                v['oauth2_access_token'] = SecretStr(v['oauth2_access_token'])
            if 'oauth2_refresh_token' in v and isinstance(v['oauth2_refresh_token'], str):
                v = v.copy()
                v['oauth2_refresh_token'] = SecretStr(v['oauth2_refresh_token'])
            if 'oauth2_client_secret' in v and isinstance(v['oauth2_client_secret'], str):
                v = v.copy()
                v['oauth2_client_secret'] = SecretStr(v['oauth2_client_secret'])
        return v

    @model_validator(mode='after')
    def validate_authentication_configuration(self) -> 'ApplicationConfiguration':
        if self.jira.profiles and self.jira.get_active_profile_name() is None:
            raise ValueError('jira.active_profile is required when authentication profiles exist.')

        if self.jira.auth_type == 'oauth2':
            if self.jira.api_base_url is None:
                raise ValueError('jira.api_base_url is required for oauth2 authentication.')
            if self.jira.cloud_id is None:
                raise ValueError('jira.cloud_id is required for oauth2 authentication.')
            if self.jira.oauth2_access_token is None:
                raise ValueError(
                    'jira.oauth2_access_token is required via GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN or the operating system keyring.'
                )
        else:
            if self.jira.api_base_url is None:
                raise ValueError('jira.api_base_url is required for basic authentication.')
            if self.jira.api_email is None:
                raise ValueError('jira.api_email is required for basic authentication.')
            if self.jira.api_token is None:
                raise ValueError(
                    'jira.api_token is required via GOJEERA_JIRA__API_TOKEN or the operating system keyring.'
                )
        return self

    show_work_item_web_links: bool = True
    """If True (default) then the application will retrieve the remote links related to a work item."""
    ignore_users_without_email: bool = True
    """Controls whether Jira users without an email address configured should be included in the list of users and users
    assignable to projects and work items."""
    enable_sprint_selection: bool = True
    """If True (default), enables the sprint selection dropdown when creating or updating work items. When False,
    the sprint field uses a plain text input."""
    jql_filters: list[dict[str, str]] | None = None
    """A list of pre-defined JQL filters to use in the JQL Expression Editor. Each item should be a dictionary
    with 'label' and 'expression' keys. Example:

    [
        {
            'label': 'Find work created by John and sort it by created date asc',
            'expression': 'creator = "john" order by created asc'
        },
        {
            'label': 'Find work due on 2100-12-31 and for the production environment',
            'expression': 'dueDate = "2100-12-31" AND environment = "production"'
        }
    ]
    """
    jql_filter_label_for_work_items_search: str | None = None
    """If set to one of the filter labels defined in jql_filters then the app will use this expression
    to retrieve work items when no criteria and JQL query is provided by the user."""
    fetch_remote_filters: RemoteFiltersConfig = RemoteFiltersConfig()
    """Configuration for fetching remote JQL filters from Jira API."""
    jumper: JumperConfig = JumperConfig()
    """Configuration for the jumper overlay widget."""
    search_results_per_page: int = Field(default=20, ge=1, le=200)
    """Number of search results to retrieve and display per page. Must be between 1 and 200. Default: 20."""
    search_results_truncate_work_item_summary: int | None = None
    """When this is defined the summary of a work item will be truncated to the specified length when it is displayed in
    the search results."""
    log_file: str | None = None
    """The filename of the log file to use. If you set an empty string logging to a file is disabled."""
    log_level: str = 'WARNING'
    """The log level to use. Use Python's `logging` names: `CRITICAL`, `FATAL`, `ERROR`, `WARN`, `WARNING`, `INFO`,
    `DEBUG` and `NOTSET`."""
    confirm_before_quit: bool = True
    """If this is set to `True` then the application will show a pop-up screen so the user can confirm whether or not
    to quit the app. The default is `False` and the app simply exits."""
    theme: str | None = None
    """The name of the theme to use for the UI. Accept Textual themes."""
    enable_advanced_full_text_search: bool = True
    """When enabled, gojeera uses Jira full-text search across text-based fields, including comments.
    This may be slower. When disabled, searching is limited to summary and description fields."""
    ssl: SSLConfiguration | None = SSLConfiguration()
    """SSL configuration for client-side certificates and CA bundle."""
    search_on_startup: bool = False
    """If True, triggers a search automatically when the UI starts. Can be set via CLI argument --search-on-startup."""
    enable_updating_additional_fields: bool = False
    """If True the app will allow the user to view and update additional fields."""
    update_additional_fields_ignore_ids: list[str] | None = None
    """When `enable_updating_additional_fields = True`, some custom fields and system fields with these ids or keys
    will be ignored and not show in the Details tab and will not be updated."""
    enable_creating_additional_fields: bool = False
    """If True the app will allow the user to populate additional optional fields when creating work items.
    When False (default), only 'duedate' and 'priority' optional fields are shown."""
    create_additional_fields_ignore_ids: list[str] | None = None
    """When `enable_creating_additional_fields = True`, optional fields with these IDs will be excluded from rendering.
    Example: ['customfield_10050', 'customfield_10051']
    When `enable_creating_additional_fields = False`, this is also used to exclude specific fields from the default set."""
    show_footer: bool = True
    """When this is `True` (default), footer key bindings are shown. When `False`, footer widgets are hidden."""

    model_config = SettingsConfigDict(
        extra='allow',
        validate_assignment=True,
        env_prefix='GOJEERA_',
        env_nested_delimiter='__',
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        if jira_tui_config_file := os.getenv('GOJEERA_CONFIG_FILE'):
            conf_file = Path(jira_tui_config_file).resolve()
        else:
            conf_file = get_config_file()

        if conf_file.exists():
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                GojeeraYamlConfigSettingsSource(settings_cls, yaml_file=conf_file),
                AuthProfilesSettingsSource(settings_cls),
                KeyringSettingsSource(settings_cls),
            )
        else:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                AuthProfilesSettingsSource(settings_cls),
                KeyringSettingsSource(settings_cls),
            )


CONFIGURATION: ContextVar[ApplicationConfiguration] = ContextVar('configuration')


class KeyringSettingsSource(InitSettingsSource):
    """Load secrets from the operating system keyring after env vars and YAML config."""

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls, {})

    def __call__(self) -> dict[str, object]:
        state = self.current_state
        settings: dict[str, object] = {}

        jira_config = state.get('jira')
        if isinstance(jira_config, dict):
            profiles = jira_config.get('profiles')
            active_profile_name = jira_config.get('active_profile')
            if not isinstance(active_profile_name, str):
                active_profile_name = jira_config.get('active_profile_name')
            active_profile: AuthProfile | None = None
            if isinstance(profiles, dict) and isinstance(active_profile_name, str):
                candidate = profiles.get(active_profile_name)
                if isinstance(candidate, dict):
                    auth_type = candidate.get('auth_type', 'basic')
                    if auth_type == 'oauth2':
                        active_profile = OAuth2AuthProfile.model_validate(candidate)
                    else:
                        active_profile = BasicAuthProfile.model_validate(candidate)

            auth_type = jira_config.get('auth_type')
            if not isinstance(auth_type, str):
                auth_type = jira_config.get('auth_type_override')
            if not isinstance(auth_type, str) and active_profile is not None:
                auth_type = active_profile.auth_type
            if not isinstance(auth_type, str):
                auth_type = 'basic'

            api_base_url = jira_config.get('api_base_url')
            if not isinstance(api_base_url, str):
                api_base_url = jira_config.get('api_base_url_override')
            if not isinstance(api_base_url, str) and active_profile is not None:
                api_base_url = active_profile.instance_url

            resolved_profile: AuthProfile | None = active_profile
            if auth_type == 'basic' and isinstance(active_profile, OAuth2AuthProfile):
                resolved_profile = None
            elif auth_type == 'oauth2' and isinstance(active_profile, BasicAuthProfile):
                resolved_profile = None

            if resolved_profile is None and isinstance(api_base_url, str):
                if auth_type == 'oauth2':
                    cloud_id = jira_config.get('cloud_id')
                    if not isinstance(cloud_id, str):
                        cloud_id = jira_config.get('cloud_id_override')
                    if isinstance(cloud_id, str):
                        resolved_profile = OAuth2AuthProfile(
                            name='__override__',
                            instance_url=api_base_url,
                            cloud_id=cloud_id,
                            client_id=jira_config.get('oauth2_client_id_override'),
                        )
                else:
                    api_email = jira_config.get('api_email')
                    if not isinstance(api_email, str):
                        api_email = jira_config.get('api_email_override')
                    if isinstance(api_email, str):
                        resolved_profile = BasicAuthProfile(
                            name='__override__',
                            instance_url=api_base_url,
                            email=api_email,
                        )

            if resolved_profile is not None:
                secret_settings = AUTH_SERVICE.get_runtime_secrets(
                    resolved_profile, prefer_environment=False
                )
                if secret_settings:
                    settings['jira'] = secret_settings

        return settings


class AuthProfilesSettingsSource(InitSettingsSource):
    """Load Jira auth profiles from the dedicated auth profile registry file."""

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls, {})

    def __call__(self) -> dict[str, object]:
        return load_profiles_settings()


class GojeeraYamlConfigSettingsSource(YamlConfigSettingsSource):
    """YAML config source with file-based Jira authentication removed."""

    def __call__(self) -> dict[str, object]:
        settings = super().__call__()
        jira_config = settings.get('jira')
        if isinstance(jira_config, dict):
            sanitized_jira_config = {
                key: value
                for key, value in jira_config.items()
                if key
                not in {
                    'active_profile',
                    'api_email',
                    'api_token',
                    'api_base_url',
                    'oauth2_access_token',
                    'oauth2_refresh_token',
                    'profiles',
                }
            }
            if sanitized_jira_config:
                settings['jira'] = sanitized_jira_config
            else:
                settings.pop('jira', None)
        return settings
