from datetime import datetime, timedelta, timezone

from gojeera.internal.auth.oauth2 import OAuth2TokenResponse
from gojeera.internal.auth.profiles import BasicAuthProfile, OAuth2AuthProfile
from gojeera.internal.auth.service import AuthService, AuthValidationResult


def _oauth2_profile() -> OAuth2AuthProfile:
    return OAuth2AuthProfile(
        name='work',
        site='https://example.atlassian.net',
        cloud_id='cloud-123',
        account_id='account-123',
        client_id='client-123',
    )


def _basic_profile() -> BasicAuthProfile:
    return BasicAuthProfile(
        name='work',
        site='example.atlassian.net',
        email='user@example.com',
    )


def _oauth2_profile_with_expiry(expiration_delta: timedelta) -> OAuth2AuthProfile:
    return _oauth2_profile().model_copy(
        update={
            'oauth2_access_token_expiration_timestamp': int(
                (datetime.now(timezone.utc) + expiration_delta).timestamp()
            )
        }
    )


def _mock_oauth2_store_credentials(
    monkeypatch, credentials: dict[str, str]
) -> tuple[AuthService, OAuth2AuthProfile, list[str]]:
    auth_service = AuthService()
    profile = _oauth2_profile()
    calls: list[str] = []

    def mock_get_jira_oauth2_credentials(account_id: str) -> dict[str, str]:
        calls.append(account_id)
        return credentials

    monkeypatch.setattr(
        'gojeera.internal.auth.service.get_jira_oauth2_credentials',
        mock_get_jira_oauth2_credentials,
    )
    return auth_service, profile, calls


def test_validate_basic_profile_uses_hostname_site_and_derives_ids(monkeypatch):
    auth_service = AuthService()
    calls = []

    class Response:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    def mock_get(url, **kwargs):
        calls.append((url, kwargs))
        if url == 'https://example.atlassian.net/rest/api/3/myself':
            return Response(
                200,
                {
                    'displayName': 'Test User',
                    'accountId': 'account-123',
                    'emailAddress': 'user@example.com',
                },
            )
        if url == 'https://example.atlassian.net/_edge/tenant_info':
            return Response(200, {'cloudId': 'cloud-123'})
        raise AssertionError(f'unexpected URL: {url}')

    monkeypatch.setattr('gojeera.internal.auth.service.httpx.get', mock_get)

    result = auth_service.validate_profile(_basic_profile(), api_token='token')

    assert result == AuthValidationResult(
        True,
        'Test User',
        account_id='account-123',
        email='user@example.com',
        cloud_id='cloud-123',
    )
    assert [url for url, _ in calls] == [
        'https://example.atlassian.net/rest/api/3/myself',
        'https://example.atlassian.net/_edge/tenant_info',
    ]


def _oauth2_store_secret_credentials() -> dict[str, str]:
    return {
        'refresh_token': 'refresh-token',
        'client_secret': 'client-secret',
    }


def _mock_oauth2_refresh_response(monkeypatch, refresh_token: str) -> list[tuple]:
    monkeypatch.setattr(
        'gojeera.internal.auth.service.refresh_atlassian_oauth2_token',
        lambda **kwargs: OAuth2TokenResponse(
            access_token='fresh-access-token',
            refresh_token=refresh_token,
        ),
    )
    refresh_token_writes = []
    monkeypatch.setattr(
        'gojeera.internal.auth.service.set_jira_oauth2_refresh_token',
        lambda *args, **kwargs: refresh_token_writes.append((args, kwargs)),
    )
    return refresh_token_writes


def _raise_unexpected_call(message: str):
    return (_ for _ in ()).throw(AssertionError(message))


def _profile_status_subject() -> tuple[AuthService, OAuth2AuthProfile]:
    return AuthService(), _oauth2_profile()


def test_refresh_oauth2_access_token_reads_store_bundle_once(monkeypatch):
    auth_service, profile, calls = _mock_oauth2_store_credentials(
        monkeypatch,
        _oauth2_store_secret_credentials(),
    )
    refresh_token_writes = _mock_oauth2_refresh_response(monkeypatch, 'fresh-refresh-token')

    response = auth_service.refresh_oauth2_access_token(profile)

    assert response.access_token == 'fresh-access-token'
    assert calls == ['account-123']
    assert refresh_token_writes == [(('account-123', 'fresh-refresh-token'), {})]
    assert auth_service.get_oauth2_access_token(profile) == 'fresh-access-token'


def test_refresh_oauth2_access_token_skips_store_when_credentials_are_complete(monkeypatch):
    auth_service, profile, calls = _mock_oauth2_store_credentials(monkeypatch, {})
    monkeypatch.setenv('GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN', 'env-refresh-token')
    monkeypatch.setenv('GOJEERA_JIRA__OAUTH2_CLIENT_SECRET', 'env-client-secret')
    refresh_calls = []
    monkeypatch.setattr(
        'gojeera.internal.auth.service.refresh_atlassian_oauth2_token',
        lambda **kwargs: (
            refresh_calls.append(kwargs) or OAuth2TokenResponse(access_token='fresh-access-token')
        ),
    )

    response = auth_service.refresh_oauth2_access_token(profile)

    assert response.access_token == 'fresh-access-token'
    assert calls == []
    assert refresh_calls == [
        {
            'client_id': 'client-123',
            'client_secret': 'env-client-secret',
            'refresh_token': 'env-refresh-token',
            'token_url': 'https://auth.atlassian.com/oauth/token',
        }
    ]


def test_get_oauth2_access_token_reads_runtime_cache(monkeypatch):
    auth_service = AuthService()
    profile = _oauth2_profile()
    future_timestamp = int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp())

    auth_service._cache_oauth2_access_token(
        profile,
        OAuth2TokenResponse(
            access_token='cached-access-token',
            access_token_expiration_timestamp=future_timestamp,
        ),
    )

    assert auth_service.get_oauth2_access_token(profile) == 'cached-access-token'


def test_get_oauth2_access_token_ignores_expired_runtime_cache(monkeypatch):
    auth_service = AuthService()
    profile = _oauth2_profile()
    expired_timestamp = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())

    auth_service._cache_oauth2_access_token(
        profile,
        OAuth2TokenResponse(
            access_token='expired-access-token',
            access_token_expiration_timestamp=expired_timestamp,
        ),
    )

    assert auth_service.get_oauth2_access_token(profile) is None


def test_get_runtime_secrets_reads_store_bundle_once(monkeypatch):
    auth_service, profile, calls = _mock_oauth2_store_credentials(
        monkeypatch,
        {
            'access_token': 'access-token',
            'refresh_token': 'refresh-token',
            'client_secret': 'client-secret',
        },
    )

    secrets = auth_service.get_runtime_secrets(profile, prefer_environment=False)

    assert secrets == {
        'oauth2_refresh_token': 'refresh-token',
        'oauth2_client_secret': 'client-secret',
    }
    assert calls == ['account-123']


def test_refresh_oauth2_access_token_does_not_write_unchanged_refresh_token(monkeypatch):
    auth_service, profile, calls = _mock_oauth2_store_credentials(
        monkeypatch,
        _oauth2_store_secret_credentials(),
    )
    refresh_token_writes = _mock_oauth2_refresh_response(monkeypatch, 'refresh-token')

    response = auth_service.refresh_oauth2_access_token(profile)

    assert response.access_token == 'fresh-access-token'
    assert calls == ['account-123']
    assert refresh_token_writes == []


def test_should_refresh_oauth2_access_token_on_startup_when_expiring_within_a_day():
    auth_service = AuthService()
    profile = _oauth2_profile_with_expiry(timedelta(hours=12))

    assert auth_service.should_refresh_oauth2_access_token_on_startup(profile)


def test_should_refresh_oauth2_access_token_when_expired():
    auth_service = AuthService()
    profile = _oauth2_profile_with_expiry(-timedelta(minutes=1))

    assert auth_service.should_refresh_oauth2_access_token(profile)


def test_should_not_refresh_oauth2_access_token_on_startup_when_expiry_is_more_than_a_day_away():
    auth_service = AuthService()
    profile = _oauth2_profile_with_expiry(timedelta(days=2))

    assert not auth_service.should_refresh_oauth2_access_token_on_startup(profile)


def test_should_not_refresh_oauth2_access_token_when_environment_token_is_set(monkeypatch):
    auth_service = AuthService()
    profile = _oauth2_profile_with_expiry(-timedelta(minutes=1))
    monkeypatch.setenv('GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN', 'env-access-token')

    assert not auth_service.should_refresh_oauth2_access_token(profile)


def test_get_profile_status_does_not_refresh_invalid_oauth2_token(monkeypatch):
    auth_service, profile = _profile_status_subject()

    monkeypatch.setattr(
        auth_service,
        'get_oauth2_access_token',
        lambda *args, **kwargs: 'expired-token',
    )
    monkeypatch.setattr(
        auth_service,
        'validate_profile',
        lambda *args, **kwargs: AuthValidationResult(False, '401: expired'),
    )
    monkeypatch.setattr(
        auth_service,
        'refresh_oauth2_access_token',
        lambda *args, **kwargs: _raise_unexpected_call('unexpected refresh'),
    )

    status = auth_service.get_profile_status('work', profile, active_profile_name='work')

    assert status.validation == AuthValidationResult(False, '401: expired')
    assert status.token == 'expired-token'


def test_get_profile_status_refreshes_missing_oauth2_access_token(monkeypatch):
    auth_service, profile = _profile_status_subject()

    monkeypatch.setattr(auth_service, 'get_oauth2_access_token', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auth_service,
        'refresh_oauth2_access_token',
        lambda *args, **kwargs: OAuth2TokenResponse(access_token='fresh-access-token'),
    )
    monkeypatch.setattr(
        auth_service,
        'validate_profile',
        lambda *args, **kwargs: AuthValidationResult(True, 'OAuth User'),
    )

    status = auth_service.get_profile_status('work', profile, active_profile_name='work')

    assert status.validation == AuthValidationResult(True, 'OAuth User')
    assert status.token == 'fresh-access-token'


def test_get_profile_status_reports_oauth2_refresh_failure(monkeypatch):
    auth_service, profile = _profile_status_subject()

    monkeypatch.setattr(auth_service, 'get_oauth2_access_token', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auth_service,
        'refresh_oauth2_access_token',
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('refresh unavailable')),
    )
    monkeypatch.setattr(
        auth_service,
        'validate_profile',
        lambda *args, **kwargs: _raise_unexpected_call('unexpected validation'),
    )

    status = auth_service.get_profile_status('work', profile, active_profile_name='work')

    assert status.validation == AuthValidationResult(False, 'refresh unavailable')
    assert status.token is None
