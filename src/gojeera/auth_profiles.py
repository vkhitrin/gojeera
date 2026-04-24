import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
import yaml

from gojeera.files import get_config_directory

ATLASSIAN_OAUTH2_AUTHORIZATION_URL = 'https://auth.atlassian.com/authorize'
ATLASSIAN_OAUTH2_TOKEN_URL = 'https://auth.atlassian.com/oauth/token'
ATLASSIAN_OAUTH2_REDIRECT_URI = 'http://127.0.0.1:49152/callback'


class BasicAuthProfile(BaseModel):
    model_config = ConfigDict(extra='ignore', frozen=True)

    name: str
    instance_url: str
    email: str
    auth_type: Literal['basic'] = 'basic'


class OAuth2AuthProfile(BaseModel):
    model_config = ConfigDict(extra='ignore', frozen=True)

    name: str
    instance_url: str
    cloud_id: str
    client_id: str | None = None
    account_display_name: str | None = None
    scopes: list[str] | None = None
    auth_type: Literal['oauth2'] = 'oauth2'


AuthProfile = Annotated[BasicAuthProfile | OAuth2AuthProfile, Field(discriminator='auth_type')]


def get_profiles_file() -> Path:
    if profiles_file := os.getenv('GOJEERA_AUTH_PROFILES_FILE'):
        return Path(profiles_file).expanduser().resolve()
    return get_config_directory() / 'auth_profiles.yaml'


def _load_config_data() -> dict[str, Any]:
    profiles_file = get_profiles_file()
    if not profiles_file.exists():
        return {}
    data = yaml.safe_load(profiles_file.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _save_config_data(data: dict[str, Any]) -> None:
    profiles_file = get_profiles_file()
    profiles_file.parent.mkdir(parents=True, exist_ok=True)
    profiles_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False))


def _load_profile(name: str, profile_data: dict[str, Any]) -> AuthProfile | None:
    auth_type = profile_data.get('auth_type', 'basic')
    payload = dict(profile_data)
    payload['name'] = name

    try:
        if auth_type == 'oauth2':
            return OAuth2AuthProfile.model_validate(payload)
        return BasicAuthProfile.model_validate(payload)
    except Exception:
        return None


def _dump_profile(profile: AuthProfile) -> dict[str, Any]:
    return profile.model_dump(exclude_none=True, exclude={'name'})


def list_profiles() -> tuple[str | None, dict[str, AuthProfile]]:
    config = _load_config_data()
    if not isinstance(config, dict):
        return None, {}

    active_profile = config.get('active_profile')
    profiles = config.get('profiles', {})
    if not isinstance(profiles, dict):
        profiles = {}

    normalized_profiles: dict[str, AuthProfile] = {}
    for name, profile in profiles.items():
        if not isinstance(name, str) or not isinstance(profile, dict):
            continue
        parsed_profile = _load_profile(name, profile)
        if parsed_profile is not None:
            normalized_profiles[name] = parsed_profile
    return active_profile if isinstance(active_profile, str) else None, normalized_profiles


def upsert_profile(
    profile_name: str,
    *,
    auth_type: str,
    instance_url: str,
    email: str | None,
    account_display_name: str | None,
    cloud_id: str | None,
    client_id: str | None,
    scopes: list[str] | None,
    activate: bool,
) -> None:
    config = _load_config_data()
    profiles = config.setdefault('profiles', {})
    if not isinstance(profiles, dict):
        profiles = {}
        config['profiles'] = profiles

    if auth_type == 'oauth2':
        if not cloud_id:
            raise ValueError('OAuth2 profiles require cloud_id.')
        profile: AuthProfile = OAuth2AuthProfile(
            name=profile_name,
            instance_url=instance_url,
            cloud_id=cloud_id,
            client_id=client_id,
            account_display_name=account_display_name,
            scopes=scopes,
        )
    else:
        if not email:
            raise ValueError('Basic profiles require email.')
        profile = BasicAuthProfile(name=profile_name, instance_url=instance_url, email=email)

    profiles[profile_name] = _dump_profile(profile)

    if activate or not config.get('active_profile'):
        config['active_profile'] = profile_name

    _save_config_data(config)


def remove_profile(profile_name: str) -> AuthProfile | None:
    config = _load_config_data()
    profiles = config.get('profiles', {})
    if not isinstance(profiles, dict):
        return None

    removed_profile_data = profiles.pop(profile_name, None)
    if removed_profile_data is None or not isinstance(removed_profile_data, dict):
        return None

    active_profile = config.get('active_profile')
    if active_profile == profile_name:
        config['active_profile'] = next(iter(profiles), None)

    _save_config_data(config)
    return _load_profile(profile_name, removed_profile_data)


def load_profiles_settings() -> dict[str, Any]:
    active_profile, profiles = list_profiles()
    jira_settings: dict[str, Any] = {}

    if active_profile:
        jira_settings['active_profile'] = active_profile
    if profiles:
        jira_settings['profiles'] = {
            profile_name: {
                'name': profile.name,
                **_dump_profile(profile),
            }
            for profile_name, profile in profiles.items()
        }

    return {'jira': jira_settings} if jira_settings else {}
