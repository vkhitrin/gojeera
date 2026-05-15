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
    update_oauth2_access_token_expiry,
)
from gojeera.internal.store.secret import (
    get_jira_api_token,
    get_jira_oauth2_access_token,
    get_jira_oauth2_credentials,
    get_jira_oauth2_client_secret,
    set_jira_oauth2_access_token,
    set_jira_oauth2_refresh_token,
)


@dataclass(frozen=True)
class AuthValidationResult:
    is_valid: bool
    message: str
    account_id: str | None = None


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
        if profile.account_id is None:
            return None
        return get_jira_oauth2_access_token(profile.account_id)

    def get_oauth2_client_secret(
        self, profile: OAuth2AuthProfile, *, prefer_environment: bool = True
    ) -> str | None:
        if prefer_environment and (secret := os.getenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET')):
            return secret
        if profile.account_id is None:
            return None
        return get_jira_oauth2_client_secret(profile.account_id)

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

                response = httpx.get(
                    f'{profile.site.rstrip("/")}/rest/api/3/myself',
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
            return AuthValidationResult(
                True,
                str(display_name),
                account_id=payload.get('accountId') or payload.get('account_id'),
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
        if not profile.client_id:
            raise ValueError('OAuth2 profile is missing client_id.')

        refresh_token = os.getenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN')
        client_secret = os.getenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET')
        stored_secrets = (
            {} if refresh_token and client_secret else self._get_oauth2_store_secrets(profile)
        )
        refresh_token = refresh_token or stored_secrets.get('refresh_token')
        if not refresh_token:
            raise ValueError('OAuth2 refresh token is not available.')

        client_secret = client_secret or stored_secrets.get('client_secret')
        if not client_secret:
            raise ValueError('OAuth2 client secret is not available.')

        token_response = refresh_atlassian_oauth2_token(
            client_id=profile.client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            token_url=ATLASSIAN_OAUTH2_TOKEN_URL,
        )
        if profile.account_id is None:
            raise ValueError('OAuth2 profile is missing account_id.')
        set_jira_oauth2_access_token(profile.account_id, token_response.access_token)
        if token_response.refresh_token:
            set_jira_oauth2_refresh_token(profile.account_id, token_response.refresh_token)
        update_oauth2_access_token_expiry(
            profile.name,
            token_response.access_token_expiration_timestamp,
        )
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
            if access_token := access_token or stored_secrets.get('access_token'):
                secrets['oauth2_access_token'] = access_token
            if refresh_token := refresh_token or stored_secrets.get('refresh_token'):
                secrets['oauth2_refresh_token'] = refresh_token
            if client_secret := client_secret or stored_secrets.get('client_secret'):
                secrets['oauth2_client_secret'] = client_secret
            return secrets

        if api_token := self.get_basic_api_token(profile, prefer_environment=prefer_environment):
            return {'api_token': api_token}
        return {}
