from datetime import datetime, timedelta, timezone

from gojeera.internal.auth.oauth2 import OAuth2TokenResponse
from gojeera.internal.auth.profiles import OAuth2AuthProfile
from gojeera.internal.auth.service import AuthService, AuthValidationResult


def _oauth2_profile() -> OAuth2AuthProfile:
    return OAuth2AuthProfile(
        name='work',
        site='https://example.atlassian.net',
        cloud_id='cloud-123',
        account_id='account-123',
        client_id='client-123',
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


def test_refresh_oauth2_access_token_reads_store_bundle_once(monkeypatch):
    auth_service, profile, calls = _mock_oauth2_store_credentials(
        monkeypatch,
        {
            'refresh_token': 'refresh-token',
            'client_secret': 'client-secret',
        },
    )
    monkeypatch.setattr(
        'gojeera.internal.auth.service.refresh_atlassian_oauth2_token',
        lambda **kwargs: OAuth2TokenResponse(
            access_token='fresh-access-token',
            refresh_token='fresh-refresh-token',
        ),
    )
    monkeypatch.setattr(
        'gojeera.internal.auth.service.set_jira_oauth2_access_token',
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        'gojeera.internal.auth.service.set_jira_oauth2_refresh_token',
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        'gojeera.internal.auth.service.update_oauth2_access_token_expiry',
        lambda *args, **kwargs: None,
    )

    response = auth_service.refresh_oauth2_access_token(profile)

    assert response.access_token == 'fresh-access-token'
    assert calls == ['account-123']


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
        'oauth2_access_token': 'access-token',
        'oauth2_refresh_token': 'refresh-token',
        'oauth2_client_secret': 'client-secret',
    }
    assert calls == ['account-123']


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
    auth_service = AuthService()
    profile = _oauth2_profile()

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
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('unexpected refresh')),
    )

    status = auth_service.get_profile_status('work', profile, active_profile_name='work')

    assert status.validation == AuthValidationResult(False, '401: expired')
    assert status.token == 'expired-token'
