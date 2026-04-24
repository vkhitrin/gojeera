import logging

import keyring

from gojeera.constants import LOGGER_NAME

JIRA_API_TOKEN_SERVICE = 'gojeera:jira_api_token'
JIRA_OAUTH2_ACCESS_TOKEN_SERVICE = 'gojeera:jira_oauth2_access_token'
JIRA_OAUTH2_REFRESH_TOKEN_SERVICE = 'gojeera:jira_oauth2_refresh_token'
JIRA_OAUTH2_CLIENT_SECRET_SERVICE = 'gojeera:jira_oauth2_client_secret'


class SecretStoreError(RuntimeError):
    """Raised when gojeera cannot write to the operating system secret store."""


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip('/')


def _jira_account_name(base_url: str, api_email: str) -> str:
    return f'{_normalize_base_url(base_url)}|{api_email.strip()}'


def _oauth2_account_name(base_url: str, cloud_id: str) -> str:
    return f'{_normalize_base_url(base_url)}|{cloud_id.strip()}'


def _logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def get_jira_api_token(base_url: str, api_email: str) -> str | None:
    try:
        return keyring.get_password(JIRA_API_TOKEN_SERVICE, _jira_account_name(base_url, api_email))
    except Exception as exc:
        _logger().debug('Unable to read Jira API token from keyring: %s', exc)
        return None


def set_jira_api_token(base_url: str, api_email: str, api_token: str) -> None:
    try:
        keyring.set_password(
            JIRA_API_TOKEN_SERVICE,
            _jira_account_name(base_url, api_email),
            api_token,
        )
    except Exception as exc:
        raise SecretStoreError(f'Unable to write Jira API token to keyring: {exc}') from exc


def get_jira_oauth2_access_token(base_url: str, cloud_id: str) -> str | None:
    try:
        return keyring.get_password(
            JIRA_OAUTH2_ACCESS_TOKEN_SERVICE, _oauth2_account_name(base_url, cloud_id)
        )
    except Exception as exc:
        _logger().debug('Unable to read Jira OAuth2 access token from keyring: %s', exc)
        return None


def set_jira_oauth2_access_token(base_url: str, cloud_id: str, access_token: str) -> None:
    try:
        keyring.set_password(
            JIRA_OAUTH2_ACCESS_TOKEN_SERVICE,
            _oauth2_account_name(base_url, cloud_id),
            access_token,
        )
    except Exception as exc:
        raise SecretStoreError(
            f'Unable to write Jira OAuth2 access token to keyring: {exc}'
        ) from exc


def get_jira_oauth2_refresh_token(base_url: str, cloud_id: str) -> str | None:
    try:
        return keyring.get_password(
            JIRA_OAUTH2_REFRESH_TOKEN_SERVICE, _oauth2_account_name(base_url, cloud_id)
        )
    except Exception as exc:
        _logger().debug('Unable to read Jira OAuth2 refresh token from keyring: %s', exc)
        return None


def set_jira_oauth2_refresh_token(base_url: str, cloud_id: str, refresh_token: str) -> None:
    try:
        keyring.set_password(
            JIRA_OAUTH2_REFRESH_TOKEN_SERVICE,
            _oauth2_account_name(base_url, cloud_id),
            refresh_token,
        )
    except Exception as exc:
        raise SecretStoreError(
            f'Unable to write Jira OAuth2 refresh token to keyring: {exc}'
        ) from exc


def get_jira_oauth2_client_secret(base_url: str, cloud_id: str) -> str | None:
    try:
        return keyring.get_password(
            JIRA_OAUTH2_CLIENT_SECRET_SERVICE, _oauth2_account_name(base_url, cloud_id)
        )
    except Exception as exc:
        _logger().debug('Unable to read Jira OAuth2 client secret from keyring: %s', exc)
        return None


def set_jira_oauth2_client_secret(base_url: str, cloud_id: str, client_secret: str) -> None:
    try:
        keyring.set_password(
            JIRA_OAUTH2_CLIENT_SECRET_SERVICE,
            _oauth2_account_name(base_url, cloud_id),
            client_secret,
        )
    except Exception as exc:
        raise SecretStoreError(
            f'Unable to write Jira OAuth2 client secret to keyring: {exc}'
        ) from exc


def delete_jira_api_token(base_url: str, api_email: str) -> bool:
    try:
        if (
            keyring.get_password(JIRA_API_TOKEN_SERVICE, _jira_account_name(base_url, api_email))
            is None
        ):
            return False
        keyring.delete_password(JIRA_API_TOKEN_SERVICE, _jira_account_name(base_url, api_email))
        return True
    except Exception as exc:
        raise SecretStoreError(f'Unable to delete Jira API token from keyring: {exc}') from exc


def delete_jira_oauth2_access_token(base_url: str, cloud_id: str) -> bool:
    try:
        if (
            keyring.get_password(
                JIRA_OAUTH2_ACCESS_TOKEN_SERVICE, _oauth2_account_name(base_url, cloud_id)
            )
            is None
        ):
            return False
        keyring.delete_password(
            JIRA_OAUTH2_ACCESS_TOKEN_SERVICE, _oauth2_account_name(base_url, cloud_id)
        )
        return True
    except Exception as exc:
        raise SecretStoreError(
            f'Unable to delete Jira OAuth2 access token from keyring: {exc}'
        ) from exc


def delete_jira_oauth2_refresh_token(base_url: str, cloud_id: str) -> bool:
    try:
        if (
            keyring.get_password(
                JIRA_OAUTH2_REFRESH_TOKEN_SERVICE, _oauth2_account_name(base_url, cloud_id)
            )
            is None
        ):
            return False
        keyring.delete_password(
            JIRA_OAUTH2_REFRESH_TOKEN_SERVICE, _oauth2_account_name(base_url, cloud_id)
        )
        return True
    except Exception as exc:
        raise SecretStoreError(
            f'Unable to delete Jira OAuth2 refresh token from keyring: {exc}'
        ) from exc


def delete_jira_oauth2_client_secret(base_url: str, cloud_id: str) -> bool:
    try:
        if (
            keyring.get_password(
                JIRA_OAUTH2_CLIENT_SECRET_SERVICE, _oauth2_account_name(base_url, cloud_id)
            )
            is None
        ):
            return False
        keyring.delete_password(
            JIRA_OAUTH2_CLIENT_SECRET_SERVICE, _oauth2_account_name(base_url, cloud_id)
        )
        return True
    except Exception as exc:
        raise SecretStoreError(
            f'Unable to delete Jira OAuth2 client secret from keyring: {exc}'
        ) from exc
