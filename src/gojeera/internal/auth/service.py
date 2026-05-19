from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os

import httpx

from gojeera.internal.auth.oauth2 import OAuth2TokenResponse, refresh_atlassian_oauth2_token
from gojeera.internal.auth.profiles import (
    ATLASSIAN_OAUTH2_TOKEN_URL,
    AuthProfile,
    BasicAuthProfile,
    OAuth2AuthProfile,
)
from gojeera.internal.store.secret import (
    get_jira_api_token,
    get_jira_oauth2_credentials,
    get_jira_oauth2_client_id,
    get_jira_oauth2_client_secret,
    set_jira_oauth2_refresh_token,
)


@dataclass(frozen=True)
class AuthValidationResult:
    is_valid: bool
    message: str
    account_id: str | None = None
    email: str | None = None
    cloud_id: str | None = None


@dataclass(frozen=True)
class AuthProfileStatus:
    profile_name: str
    profile: AuthProfile
    is_active: bool
    token_source: str
    token: str | None
    validation: AuthValidationResult


class AuthService:
    OAUTH2_STARTUP_REFRESH_WINDOW = timedelta(days=1)

    def __init__(self) -> None:
        self._oauth2_access_token_cache: dict[str, OAuth2TokenResponse] = {}

    def _oauth2_cache_key(self, profile: OAuth2AuthProfile) -> str:
        return profile.account_id or profile.name

    def _get_cached_oauth2_access_token(
        self, profile: OAuth2AuthProfile, *, now: datetime | None = None
    ) -> str | None:
        token_response = self._oauth2_access_token_cache.get(self._oauth2_cache_key(profile))
        if token_response is None:
            return None

        expiration_timestamp = token_response.access_token_expiration_timestamp
        if expiration_timestamp is not None:
            current_time = now or datetime.now(timezone.utc)
            if expiration_timestamp <= int(current_time.timestamp()):
                self._oauth2_access_token_cache.pop(self._oauth2_cache_key(profile), None)
                return None

        return token_response.access_token

    def _cache_oauth2_access_token(
        self, profile: OAuth2AuthProfile, token_response: OAuth2TokenResponse
    ) -> None:
        self._oauth2_access_token_cache[self._oauth2_cache_key(profile)] = token_response

    def _get_oauth2_store_secrets(self, profile: OAuth2AuthProfile) -> dict[str, str]:
        if profile.account_id is None:
            return {}
        return get_jira_oauth2_credentials(profile.account_id)

    def get_basic_api_token(
        self, profile: BasicAuthProfile, *, prefer_environment: bool = True
    ) -> str | None:
        if prefer_environment and (token := os.getenv('GOJEERA_JIRA__API_TOKEN')):
            return token
        return get_jira_api_token(profile.email)

    def get_oauth2_access_token(
        self, profile: OAuth2AuthProfile, *, prefer_environment: bool = True
    ) -> str | None:
        if prefer_environment and (token := os.getenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN')):
            return token
        return self._get_cached_oauth2_access_token(profile)

    def get_oauth2_client_secret(
        self, profile: OAuth2AuthProfile, *, prefer_environment: bool = True
    ) -> str | None:
        if prefer_environment and (secret := os.getenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET')):
            return secret
        if profile.account_id is None:
            return None
        return get_jira_oauth2_client_secret(profile.account_id)

    def get_oauth2_client_id(
        self, profile: OAuth2AuthProfile, *, prefer_environment: bool = True
    ) -> str | None:
        if prefer_environment and (client_id := os.getenv('GOJEERA_JIRA__OAUTH2_CLIENT_ID')):
            return client_id
        if profile.client_id:
            return profile.client_id
        if profile.account_id is None:
            return None
        return get_jira_oauth2_client_id(profile.account_id)

    def get_token_source(self, profile: AuthProfile) -> str:
        if isinstance(profile, OAuth2AuthProfile):
            return 'env' if os.getenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN') else 'keyring'
        return 'env' if os.getenv('GOJEERA_JIRA__API_TOKEN') else 'keyring'

    def should_refresh_oauth2_access_token(
        self,
        profile: OAuth2AuthProfile,
        *,
        now: datetime | None = None,
        refresh_window: timedelta = timedelta(0),
        skip_environment_override: bool = False,
    ) -> bool:
        if not skip_environment_override and os.getenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN'):
            return False

        expiration_timestamp = profile.oauth2_access_token_expiration_timestamp
        if expiration_timestamp is None:
            return True

        current_time = now or datetime.now(timezone.utc)
        refresh_cutoff = current_time + refresh_window
        return expiration_timestamp <= int(refresh_cutoff.timestamp())

    def should_refresh_oauth2_access_token_on_startup(
        self, profile: OAuth2AuthProfile, *, now: datetime | None = None
    ) -> bool:
        return self.should_refresh_oauth2_access_token(
            profile,
            now=now,
            refresh_window=self.OAUTH2_STARTUP_REFRESH_WINDOW,
        )

    def validate_profile(
        self,
        profile: AuthProfile,
        *,
        api_token: str | None = None,
        access_token: str | None = None,
    ) -> AuthValidationResult:
        try:
            if isinstance(profile, OAuth2AuthProfile):
                token = access_token
                if not token:
                    return AuthValidationResult(False, 'missing oauth2 access token')

                response = httpx.get(
                    'https://api.atlassian.com/me',
                    headers={
                        'Accept': 'application/json',
                        'Authorization': f'Bearer {token}',
                    },
                    timeout=10.0,
                )
            else:
                token = api_token
                if not token:
                    return AuthValidationResult(False, 'missing api token')

                site_url = profile.site_url()
                response = httpx.get(
                    f'{site_url}/rest/api/3/myself',
                    headers={'Accept': 'application/json'},
                    auth=httpx.BasicAuth(profile.email, token),
                    timeout=10.0,
                )
        except httpx.HTTPError as exc:
            return AuthValidationResult(False, f'connection error: {exc}')

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            display_name = (
                payload.get('displayName')
                or payload.get('name')
                or payload.get('nickname')
                or payload.get('accountId')
                or payload.get('account_id')
                or 'authenticated'
            )
            cloud_id = None
            if isinstance(profile, BasicAuthProfile):
                try:
                    tenant_response = httpx.get(
                        f'{profile.site_url()}/_edge/tenant_info',
                        headers={'Accept': 'application/json'},
                        auth=httpx.BasicAuth(profile.email, api_token or ''),
                        timeout=10.0,
                    )
                    if tenant_response.status_code == 200:
                        tenant_payload = tenant_response.json()
                        if isinstance(tenant_payload, dict):
                            cloud_id = tenant_payload.get('cloudId') or tenant_payload.get(
                                'cloud_id'
                            )
                except (httpx.HTTPError, ValueError):
                    cloud_id = None

            return AuthValidationResult(
                True,
                str(display_name),
                account_id=payload.get('accountId') or payload.get('account_id'),
                email=payload.get('email') or payload.get('emailAddress'),
                cloud_id=cloud_id,
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        error_message = 'authentication failed'
        if isinstance(payload, dict):
            if error_messages := payload.get('errorMessages'):
                if isinstance(error_messages, list) and error_messages:
                    error_message = str(error_messages[0])

        return AuthValidationResult(False, f'{response.status_code}: {error_message}')

    def refresh_oauth2_access_token(self, profile: OAuth2AuthProfile) -> OAuth2TokenResponse:
        client_id = os.getenv('GOJEERA_JIRA__OAUTH2_CLIENT_ID') or profile.client_id
        refresh_token = os.getenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN')
        client_secret = os.getenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET')

        if not (client_id and refresh_token and client_secret):
            stored_secrets = self._get_oauth2_store_secrets(profile)
            client_id = client_id or stored_secrets.get('client_id')
            refresh_token = refresh_token or stored_secrets.get('refresh_token')
            client_secret = client_secret or stored_secrets.get('client_secret')

        if not client_id:
            raise ValueError('OAuth2 profile is missing client_id.')
        if not refresh_token:
            raise ValueError('OAuth2 refresh token is not available.')
        if not client_secret:
            raise ValueError('OAuth2 client secret is not available.')

        token_response = refresh_atlassian_oauth2_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            token_url=ATLASSIAN_OAUTH2_TOKEN_URL,
        )
        if profile.account_id is None:
            raise ValueError('OAuth2 profile is missing account_id.')
        if token_response.refresh_token and token_response.refresh_token != refresh_token:
            set_jira_oauth2_refresh_token(profile.account_id, token_response.refresh_token)
        self._cache_oauth2_access_token(profile, token_response)
        return token_response

    def get_profile_status(
        self,
        profile_name: str,
        profile: AuthProfile,
        *,
        active_profile_name: str | None,
    ) -> AuthProfileStatus:
        token_source = self.get_token_source(profile)

        if isinstance(profile, OAuth2AuthProfile):
            token = self.get_oauth2_access_token(profile)
            if token is None:
                try:
                    token = self.refresh_oauth2_access_token(profile).access_token
                except (ValueError, RuntimeError) as exc:
                    validation = AuthValidationResult(False, str(exc))
                except httpx.HTTPError as exc:
                    validation = AuthValidationResult(False, f'connection error: {exc}')
                else:
                    validation = self.validate_profile(profile, access_token=token)
            else:
                validation = self.validate_profile(profile, access_token=token)
        else:
            token = self.get_basic_api_token(profile)
            validation = self.validate_profile(profile, api_token=token)

        return AuthProfileStatus(
            profile_name=profile_name,
            profile=profile,
            is_active=profile_name == active_profile_name,
            token_source=token_source,
            token=token,
            validation=validation,
        )

    def get_runtime_secrets(
        self, profile: AuthProfile, *, prefer_environment: bool = True
    ) -> dict[str, str]:
        if isinstance(profile, OAuth2AuthProfile):
            secrets: dict[str, str] = {}
            access_token = (
                os.getenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN') if prefer_environment else None
            )
            refresh_token = (
                os.getenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN') if prefer_environment else None
            )
            client_secret = (
                os.getenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET') if prefer_environment else None
            )
            stored_secrets = (
                {}
                if access_token and refresh_token and client_secret
                else self._get_oauth2_store_secrets(profile)
            )
            if access_token := access_token:
                secrets['oauth2_access_token'] = access_token
            if refresh_token := refresh_token or stored_secrets.get('refresh_token'):
                secrets['oauth2_refresh_token'] = refresh_token
            if client_id := stored_secrets.get('client_id'):
                secrets['oauth2_client_id'] = client_id
            if client_secret := client_secret or stored_secrets.get('client_secret'):
                secrets['oauth2_client_secret'] = client_secret
            return secrets

        if api_token := self.get_basic_api_token(profile, prefer_environment=prefer_environment):
            return {'api_token': api_token}
        return {}
