import os
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError
import yaml

from gojeera.internal.store.files import get_config_directory
from gojeera.internal.store.files import load_yaml_mapping

ATLASSIAN_OAUTH2_AUTHORIZATION_URL = 'https://auth.atlassian.com/authorize'
ATLASSIAN_OAUTH2_TOKEN_URL = 'https://auth.atlassian.com/oauth/token'
ATLASSIAN_OAUTH2_REDIRECT_URI = 'http://127.0.0.1:49152/callback'


class AuthProfileBase(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str
    site: str

    def site_url(self) -> str:
        site = self.site.strip().rstrip('/')
        if urlsplit(site).scheme:
            return site
        return f'https://{site}'

    def basic_email(self) -> str | None:
        return None

    def oauth_cloud_id(self) -> str | None:
        return None

    def oauth_client_id(self) -> str | None:
        return None

    def oauth_scopes(self) -> list[str] | None:
        return None

    def existing_email(self) -> str:
        return ''

    def existing_client_id(self) -> str:
        return ''


class BasicAuthProfile(AuthProfileBase):
    email: str
    cloud_id: str | None = None
    account_id: str | None = None
    display_name: str | None = None
    auth_type: Literal['basic'] = 'basic'

    def basic_email(self) -> str | None:
        return self.email

    def oauth_cloud_id(self) -> str | None:
        return self.cloud_id

    def existing_email(self) -> str:
        return self.email


class OAuth2AuthProfile(AuthProfileBase):
    cloud_id: str
    account_id: str | None = None
    email: str | None = None
    client_id: str | None = None
    display_name: str | None = None
    oauth2_access_token_expiration_timestamp: int | None = None
    auth_type: Literal['oauth2'] = 'oauth2'

    def oauth_cloud_id(self) -> str | None:
        return self.cloud_id

    def oauth_client_id(self) -> str | None:
        return self.client_id

    def oauth_scopes(self) -> list[str] | None:
        from gojeera.internal.auth.oauth2 import OAUTH2_SCOPES

        return OAUTH2_SCOPES

    def existing_client_id(self) -> str:
        return self.client_id or ''


AuthProfile = Annotated[BasicAuthProfile | OAuth2AuthProfile, Field(discriminator='auth_type')]


def get_profiles_file() -> Path:
    if profiles_file := os.getenv('GOJEERA_AUTH_PROFILES_FILE'):
        return Path(profiles_file).expanduser().resolve()
    return get_config_directory() / 'auth_profiles.yaml'


def _load_config_data() -> dict[str, Any]:
    profiles_file = get_profiles_file()
    if not profiles_file.exists():
        return {}
    try:
        return load_yaml_mapping(profiles_file, default_empty={})
    except TypeError:
        return {}


def _save_config_data(data: dict[str, Any]) -> None:
    profiles_file = get_profiles_file()
    profiles_file.parent.mkdir(parents=True, exist_ok=True)
    profiles_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False))


def _format_profile_validation_error(name: str, exc: ValidationError) -> str:
    formatted_errors: list[str] = []
    for error in exc.errors():
        location = '.'.join(str(part) for part in error.get('loc', ()) if part is not None)
        if error.get('type') == 'extra_forbidden' and location:
            formatted_errors.append(f'unexpected field "{location}"')
        elif location:
            formatted_errors.append(f'{location}: {error.get("msg")}')
        else:
            formatted_errors.append(str(error.get('msg')))

    details = '; '.join(formatted_errors) if formatted_errors else str(exc)
    return f'Invalid auth profile "{name}": {details}'


def _load_profile(name: str, profile_data: dict[str, Any]) -> AuthProfile:
    auth_type = profile_data.get('auth_type', 'basic')
    payload = dict(profile_data)
    payload['name'] = name
    if auth_type == 'api_token':
        payload['auth_type'] = 'basic'
        auth_type = 'basic'
    if auth_type == 'oauth':
        payload['auth_type'] = 'oauth2'
        auth_type = 'oauth2'

    try:
        if auth_type == 'oauth2':
            return OAuth2AuthProfile.model_validate(payload)
        return BasicAuthProfile.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(_format_profile_validation_error(name, exc)) from exc


def _dump_profile(profile: AuthProfile) -> dict[str, Any]:
    if isinstance(profile, OAuth2AuthProfile):
        payload = profile.model_dump(
            exclude_none=True,
            exclude={
                'name',
                'scopes',
                'client_id',
                'oauth2_access_token_expiration_timestamp',
            },
        )
        payload['auth_type'] = 'oauth'
        return payload
    payload = profile.model_dump(exclude_none=True, exclude={'name', 'scopes'})
    payload['auth_type'] = 'api_token'
    return payload


def _dump_profile_entry(profile: AuthProfile) -> dict[str, Any]:
    payload = _dump_profile(profile)
    return {'name': profile.name, **payload}


def _cloud_account_profile_name(profile: dict[str, Any]) -> str | None:
    cloud_id = profile.get('cloud_id')
    account_id = profile.get('account_id')
    if isinstance(cloud_id, str) and isinstance(account_id, str):
        return f'{cloud_id}:{account_id}'
    return None


def _iter_profile_entries(raw_profiles: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw_profiles, list):
        entries: list[tuple[str, dict[str, Any]]] = []
        for item in raw_profiles:
            if not isinstance(item, dict):
                continue
            name = item.get('name') or _cloud_account_profile_name(item)
            if isinstance(name, str):
                entries.append((name, item))
        return entries

    return []


def get_current_profile_name(config: dict[str, Any]) -> str | None:
    current_profile = config.get('current_profile')
    return current_profile if isinstance(current_profile, str) else None


def normalize_profiles(raw_profiles: Any) -> dict[str, AuthProfile]:
    normalized_profiles: dict[str, AuthProfile] = {}
    for name, profile in _iter_profile_entries(raw_profiles):
        normalized_profiles[name] = _load_profile(name, profile)
    return normalized_profiles


def resolve_current_profile(config: dict[str, Any]) -> AuthProfile | None:
    current_profile_name = get_current_profile_name(config)
    if not isinstance(current_profile_name, str):
        return None

    return normalize_profiles(config.get('profiles', {})).get(current_profile_name)


def list_profiles() -> tuple[str | None, dict[str, AuthProfile]]:
    config = _load_config_data()
    current_profile = get_current_profile_name(config)
    profiles = normalize_profiles(config.get('profiles', {}))
    return current_profile, profiles


def upsert_profile(
    profile_name: str,
    *,
    auth_type: str,
    site: str,
    email: str | None,
    account_id: str | None,
    display_name: str | None,
    cloud_id: str | None,
    client_id: str | None,
    oauth2_access_token_expiration_timestamp: int | None,
    activate: bool,
) -> None:
    config = _load_config_data()
    active_profile, profiles = list_profiles()

    if auth_type == 'oauth2':
        if not cloud_id:
            raise ValueError('OAuth2 profiles require cloud_id.')
        profile: AuthProfile = OAuth2AuthProfile(
            name=profile_name,
            site=site,
            cloud_id=cloud_id,
            account_id=account_id,
            email=email,
            client_id=client_id,
            display_name=display_name,
            oauth2_access_token_expiration_timestamp=oauth2_access_token_expiration_timestamp,
        )
    else:
        if not email:
            raise ValueError('Basic profiles require email.')
        profile = BasicAuthProfile(
            name=profile_name,
            site=site,
            email=email,
            cloud_id=cloud_id,
            account_id=account_id,
            display_name=display_name,
        )

    profiles[profile_name] = profile

    config['profiles'] = [
        _dump_profile_entry(current_profile) for current_profile in profiles.values()
    ]

    if activate or not active_profile:
        config['current_profile'] = profile_name

    _save_config_data(config)


def remove_profile(profile_name: str) -> AuthProfile | None:
    config = _load_config_data()
    active_profile, profiles = list_profiles()

    removed_profile = profiles.pop(profile_name, None)
    if removed_profile is None:
        return None

    if active_profile == profile_name:
        config['current_profile'] = next(iter(profiles), None)

    config['profiles'] = [
        _dump_profile_entry(current_profile) for current_profile in profiles.values()
    ]
    _save_config_data(config)
    return removed_profile


def load_profiles_settings() -> dict[str, Any]:
    current_profile, profiles = list_profiles()
    jira_settings: dict[str, Any] = {}

    if current_profile:
        jira_settings['current_profile'] = current_profile
    if profiles:
        jira_settings['profiles'] = [_dump_profile_entry(profile) for profile in profiles.values()]

    return {'jira': jira_settings} if jira_settings else {}
