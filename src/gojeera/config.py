from contextvars import ContextVar
import os
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from gojeera.files import get_config_file
from gojeera.models import BaseModel


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
    """If True, gojeera will fetch JQL filters from the Jira server and include them in the JQL autocomplete dropdown.
    Default is False."""
    include_shared: bool = False
    """If True, fetch both personal filters and filters shared with you (through groups/projects).
    If False, only fetch filters owned by the current user.
    Default is False (personal filters only)."""
    starred_only: bool = False
    """If True, only fetch filters that are starred (marked as favorite) by the user. If False, fetch all filters.
    Default is False (fetch all)."""
    cache_ttl: int = 3600
    """Time-to-live (in seconds) for cached remote filters. After this time, filters will be re-fetched from the server.
    Default is 3600 seconds (1 hour)."""


class JumperConfig(BaseModel):
    """Configuration for the jumper overlay widget."""

    enabled: bool = True
    """If True (default), the jumper overlay is enabled and allows quick navigation between widgets."""
    keys: list[str] = ['1', '2', '3', 'q', 'w', 'e', 'a', 's', 'd']
    """List of keys to use for the jumper overlay. Default is ['1', '2', '3', 'q', 'w', 'e', 'a', 's', 'd']."""


class JiraConfig(BaseSettings):
    """Configuration for Jira API connection."""

    api_username: str
    """The username to use for connecting to the Jira API."""
    api_token: SecretStr
    """The token to use for connecting to the Jira API."""
    api_base_url: str
    """The base URL of the Jira API."""

    model_config = SettingsConfigDict(
        env_prefix='GOJEERA_JIRA__',
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
        return v

    show_work_item_web_links: bool = True
    """If True (default) then the application will retrieve the remote links related to a work item."""
    ignore_users_without_email: bool = True
    """Controls whether Jira users without an email address configured should be included in the list of users and users
    assignable to projects and work items."""
    enable_sprint_selection: bool = True
    """If True (default), enables the sprint selection dropdown when creating or updating work items. When False,
    the sprint field uses a plain text input."""
    fetch_attachments_on_delete: bool = True
    """When this is True (default) the application will fetch the attachments of a work item after an attachment is
    deleted from the list of attachments. This makes the data more accurate but slower due to the extra request. When
    this is False the list of attachments is updated in place."""
    fetch_comments_on_delete: bool = True
    """When this is True (default) the application will fetch the comments of a work item after a comment is
    deleted from the list of comments. This makes the data more accurate but slower due to the extra request. When
    this is False the list of comments is updated in place."""
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
    fetch_remote_filters: RemoteFiltersConfig = Field(default_factory=RemoteFiltersConfig)  # type: ignore[assignment]
    """Configuration for fetching remote JQL filters from Jira API."""
    jumper: JumperConfig = Field(default_factory=JumperConfig)  # type: ignore[assignment]
    """Configuration for the jumper overlay widget."""
    search_results_per_page: int = Field(default=20, ge=1, le=200)
    """Number of search results to retrieve and display per page. Must be between 1 and 200. Default is 20."""
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
    """When this is True gojeera will use Jira ability to do full-text search not only in summary and description
    fields but in any text-based field, including comments. This may be slower. If this is False gojeera will only
    search items by summary and description fields."""
    ssl: SSLConfiguration | None = Field(default_factory=SSLConfiguration)  # type: ignore[assignment]
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
    enable_images_support: bool = True
    """When this is set to `True` gojeera will attempt to display images attached to a work item in the Attachments
    tab."""
    obfuscate_personal_info: bool = False
    """When this is set to `True` the app header will obfuscate the username and instance URL for privacy. Default is
    False."""

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
                YamlConfigSettingsSource(settings_cls, yaml_file=conf_file),
            )
        else:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
            )


CONFIGURATION: ContextVar[ApplicationConfiguration] = ContextVar('configuration')
