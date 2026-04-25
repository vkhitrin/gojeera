import json
import logging

import keyring

JIRA_SECRET_SERVICE = 'gojeera'


class SecretStoreError(RuntimeError):
    """Raised when gojeera cannot read or write the operating system secret store."""


def _basic_auth_account_name(api_email: str) -> str:
    return f'basic_auth:{api_email.strip()}'


def _oauth2_account_name(account_id: str) -> str:
    return f'oauth:{account_id.strip()}'


def _logger() -> logging.Logger:
    return logging.getLogger('gojeera')


def _decode_oauth2_bundle(payload: str) -> dict[str, str]:
    try:
        parsed = json.loads(payload)
    except Exception as exc:
        raise SecretStoreError(
            'Unable to decode the Jira OAuth2 secret from the operating system keyring.'
        ) from exc

    if not isinstance(parsed, dict):
        raise SecretStoreError(
            'The Jira OAuth2 secret stored in the operating system keyring is invalid.'
        )

    normalized: dict[str, str] = {}
    for key in ('access_token', 'refresh_token', 'client_secret'):
        value = parsed.get(key)
        if isinstance(value, str) and value:
            normalized[key] = value
    return normalized


def _encode_oauth2_bundle(bundle: dict[str, str]) -> str:
    return json.dumps(bundle, separators=(',', ':'), sort_keys=True)


def _read_oauth2_bundle(account_id: str) -> dict[str, str]:
    account_name = _oauth2_account_name(account_id)
    try:
        payload = keyring.get_password(JIRA_SECRET_SERVICE, account_name)
    except Exception as exc:
        raise SecretStoreError(
            f'Unable to read the Jira OAuth2 secret from the operating system keyring: {exc}'
        ) from exc

    if payload:
        return _decode_oauth2_bundle(payload)

    return {}


def _delete_password_if_exists(service_name: str, account_name: str) -> bool:
    try:
        if keyring.get_password(service_name, account_name) is None:
            return False
        keyring.delete_password(service_name, account_name)
        return True
    except Exception as exc:
        raise SecretStoreError(f'Unable to delete Jira OAuth2 secret from keyring: {exc}') from exc


def _write_oauth2_bundle(account_id: str, bundle: dict[str, str]) -> None:
    try:
        keyring.set_password(
            JIRA_SECRET_SERVICE,
            _oauth2_account_name(account_id),
            _encode_oauth2_bundle(bundle),
        )
    except Exception as exc:
        raise SecretStoreError(f'Unable to write Jira OAuth2 bundle to keyring: {exc}') from exc


def _update_oauth2_bundle_value(account_id: str, field_name: str, value: str) -> None:
    bundle = _read_oauth2_bundle(account_id)
    bundle[field_name] = value
    _write_oauth2_bundle(account_id, bundle)


def _delete_oauth2_bundle_value(account_id: str, field_name: str) -> bool:
    deleted_any = False
    bundle = _read_oauth2_bundle(account_id)
    if field_name in bundle:
        deleted_any = True
        del bundle[field_name]
        account_name = _oauth2_account_name(account_id)
        if bundle:
            _write_oauth2_bundle(account_id, bundle)
        else:
            deleted_any = (
                _delete_password_if_exists(JIRA_SECRET_SERVICE, account_name) or deleted_any
            )
    return deleted_any


def get_jira_api_token(api_email: str) -> str | None:
    try:
        return keyring.get_password(JIRA_SECRET_SERVICE, _basic_auth_account_name(api_email))
    except Exception as exc:
        _logger().debug('Unable to read Jira API token from keyring: %s', exc)
        return None


def set_jira_api_token(api_email: str, api_token: str) -> None:
    try:
        keyring.set_password(
            JIRA_SECRET_SERVICE,
            _basic_auth_account_name(api_email),
            api_token,
        )
    except Exception as exc:
        raise SecretStoreError(f'Unable to write Jira API token to keyring: {exc}') from exc


def get_jira_oauth2_access_token(account_id: str) -> str | None:
    return _read_oauth2_bundle(account_id).get('access_token')


def set_jira_oauth2_access_token(account_id: str, access_token: str) -> None:
    _update_oauth2_bundle_value(account_id, 'access_token', access_token)


def get_jira_oauth2_refresh_token(account_id: str) -> str | None:
    return _read_oauth2_bundle(account_id).get('refresh_token')


def set_jira_oauth2_refresh_token(account_id: str, refresh_token: str) -> None:
    _update_oauth2_bundle_value(account_id, 'refresh_token', refresh_token)


def get_jira_oauth2_client_secret(account_id: str) -> str | None:
    return _read_oauth2_bundle(account_id).get('client_secret')


def set_jira_oauth2_client_secret(account_id: str, client_secret: str) -> None:
    _update_oauth2_bundle_value(account_id, 'client_secret', client_secret)


def delete_jira_api_token(api_email: str) -> bool:
    try:
        account_name = _basic_auth_account_name(api_email)
        if keyring.get_password(JIRA_SECRET_SERVICE, account_name) is None:
            return False
        keyring.delete_password(JIRA_SECRET_SERVICE, account_name)
        return True
    except Exception as exc:
        raise SecretStoreError(f'Unable to delete Jira API token from keyring: {exc}') from exc


def delete_jira_oauth2_access_token(account_id: str) -> bool:
    return _delete_oauth2_bundle_value(account_id, 'access_token')


def delete_jira_oauth2_refresh_token(account_id: str) -> bool:
    return _delete_oauth2_bundle_value(account_id, 'refresh_token')


def delete_jira_oauth2_client_secret(account_id: str) -> bool:
    return _delete_oauth2_bundle_value(account_id, 'client_secret')
