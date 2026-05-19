import yaml

from gojeera.internal.auth.profiles import list_profiles, upsert_profile


def test_upsert_oauth2_profile_writes_named_oauth_profile_without_secrets(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))

    upsert_profile(
        'work',
        auth_type='oauth2',
        site='plainid.atlassian.net',
        email=None,
        account_id='712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        display_name='Vadim Khitrin',
        cloud_id='156d871e-bab7-4cd0-b529-a8a5af3f792e',
        client_id='client-123',
        oauth2_access_token_expiration_timestamp=123,
        activate=True,
    )

    config = yaml.safe_load(profiles_file.read_text())

    assert config == {
        'profiles': [
            {
                'name': 'work',
                'site': 'plainid.atlassian.net',
                'cloud_id': '156d871e-bab7-4cd0-b529-a8a5af3f792e',
                'account_id': '712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
                'display_name': 'Vadim Khitrin',
                'auth_type': 'oauth',
            }
        ],
        'current_profile': 'work',
    }

    assert 'client_id' not in config['profiles'][0]
    assert 'oauth2_access_token_expiration_timestamp' not in config['profiles'][0]


def test_upsert_basic_profile_writes_api_token_profile_with_resolved_ids(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))

    upsert_profile(
        'work',
        auth_type='basic',
        site='plainid.atlassian.net',
        email='tools@example.com',
        account_id='account-123',
        display_name='Tools User',
        cloud_id='cloud-123',
        client_id=None,
        oauth2_access_token_expiration_timestamp=None,
        activate=True,
    )

    config = yaml.safe_load(profiles_file.read_text())

    assert config == {
        'profiles': [
            {
                'name': 'work',
                'site': 'plainid.atlassian.net',
                'email': 'tools@example.com',
                'cloud_id': 'cloud-123',
                'account_id': 'account-123',
                'display_name': 'Tools User',
                'auth_type': 'api_token',
            }
        ],
        'current_profile': 'work',
    }


def test_list_profiles_reads_named_oauth_profile(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))
    profiles_file.write_text(
        '\n'.join(
            [
                'current_profile: "work"',
                'profiles:',
                '  - name: "work"',
                '    site: "example.atlassian.net"',
                '    cloud_id: "cloud-123"',
                '    account_id: "account-123"',
                '    display_name: "Test User"',
                '    email: "user@example.com"',
                '    auth_type: "oauth"',
            ]
        )
    )

    current_profile, profiles = list_profiles()

    assert current_profile == 'work'
    assert list(profiles) == ['work']
    assert profiles['work'].auth_type == 'oauth2'


def test_list_profiles_reads_acli_style_oauth_profile(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))
    profiles_file.write_text(
        '\n'.join(
            [
                'version: 1',
                'current_profile: "cloud-123:account-123"',
                'profiles:',
                '  - site: "example.atlassian.net"',
                '    cloud_id: "cloud-123"',
                '    account_id: "account-123"',
                '    display_name: "Test User"',
                '    email: "user@example.com"',
                '    auth_type: "oauth"',
            ]
        )
    )

    current_profile, profiles = list_profiles()

    assert current_profile == 'cloud-123:account-123'
    assert list(profiles) == ['cloud-123:account-123']
    assert profiles['cloud-123:account-123'].auth_type == 'oauth2'


def test_list_profiles_reads_acli_style_api_token_profile(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))
    profiles_file.write_text(
        '\n'.join(
            [
                'version: 1',
                'current_profile: "cloud-123:account-123"',
                'profiles:',
                '  - site: "example.atlassian.net"',
                '    cloud_id: "cloud-123"',
                '    account_id: "account-123"',
                '    display_name: "Test User"',
                '    email: "user@example.com"',
                '    auth_type: "api_token"',
            ]
        )
    )

    current_profile, profiles = list_profiles()

    assert current_profile == 'cloud-123:account-123'
    assert list(profiles) == ['cloud-123:account-123']
    assert profiles['cloud-123:account-123'].auth_type == 'basic'
