import yaml

from gojeera.internal.auth.profiles import list_profiles, upsert_profile


def auth_profiles_file(monkeypatch, tmp_path):
    profiles_file = tmp_path / 'auth_profiles.yaml'
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(profiles_file))
    return profiles_file


def write_profile_config(profiles_file, *, current_profile: str, auth_type: str, name: str | None):
    lines = [
        'version: 1',
        f'current_profile: "{current_profile}"',
        'profiles:',
    ]
    if name is not None:
        lines.append(f'  - name: "{name}"')
    else:
        lines.append('  - site: "example.atlassian.net"')
    if name is not None:
        lines.append('    site: "example.atlassian.net"')
    lines.extend(
        [
            '    cloud_id: "cloud-123"',
            '    account_id: "account-123"',
            '    display_name: "Test User"',
            '    email: "user@example.com"',
            f'    auth_type: "{auth_type}"',
        ]
    )
    profiles_file.write_text('\n'.join(lines))


def upsert_work_profile(profiles_file, **profile_kwargs):
    upsert_profile(
        'work',
        site=profile_kwargs.pop('site', 'plainid.atlassian.net'),
        client_id=profile_kwargs.pop('client_id', None),
        oauth2_access_token_expiration_timestamp=profile_kwargs.pop(
            'oauth2_access_token_expiration_timestamp', None
        ),
        activate=True,
        **profile_kwargs,
    )
    return yaml.safe_load(profiles_file.read_text())


def expected_single_profile_config(**profile):
    return {
        'profiles': [
            {
                'name': 'work',
                'site': 'plainid.atlassian.net',
                **profile,
            }
        ],
        'current_profile': 'work',
    }


def test_upsert_oauth2_profile_writes_named_oauth_profile_without_secrets(monkeypatch, tmp_path):
    profiles_file = auth_profiles_file(monkeypatch, tmp_path)

    config = upsert_work_profile(
        profiles_file,
        auth_type='oauth2',
        email=None,
        account_id='712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        display_name='Vadim Khitrin',
        cloud_id='156d871e-bab7-4cd0-b529-a8a5af3f792e',
        client_id='client-123',
        oauth2_access_token_expiration_timestamp=123,
    )

    assert config == expected_single_profile_config(
        cloud_id='156d871e-bab7-4cd0-b529-a8a5af3f792e',
        account_id='712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        display_name='Vadim Khitrin',
        auth_type='oauth',
    )

    assert 'client_id' not in config['profiles'][0]
    assert 'oauth2_access_token_expiration_timestamp' not in config['profiles'][0]


def test_upsert_oauth2_profile_writes_api_token_fallback_profile(monkeypatch, tmp_path):
    profiles_file = auth_profiles_file(monkeypatch, tmp_path)

    config = upsert_work_profile(
        profiles_file,
        auth_type='oauth2',
        email=None,
        account_id='712020:403b9a3f-d68e-46a1-83f3-8f87a7b55857',
        display_name='Vadim Khitrin',
        cloud_id='156d871e-bab7-4cd0-b529-a8a5af3f792e',
        client_id='client-123',
        api_token_fallback_profile='work-api-token',
    )

    assert config['profiles'][0]['api_token_fallback_profile'] == 'work-api-token'

    _, profiles = list_profiles()
    assert profiles['work'].api_token_fallback_profile() == 'work-api-token'


def test_upsert_basic_profile_writes_api_token_profile_with_resolved_ids(monkeypatch, tmp_path):
    profiles_file = auth_profiles_file(monkeypatch, tmp_path)

    config = upsert_work_profile(
        profiles_file,
        auth_type='basic',
        email='tools@example.com',
        account_id='account-123',
        display_name='Tools User',
        cloud_id='cloud-123',
    )

    assert config == expected_single_profile_config(
        email='tools@example.com',
        cloud_id='cloud-123',
        account_id='account-123',
        display_name='Tools User',
        auth_type='api_token',
    )


def test_list_profiles_reads_named_oauth_profile(monkeypatch, tmp_path):
    profiles_file = auth_profiles_file(monkeypatch, tmp_path)
    write_profile_config(
        profiles_file,
        current_profile='work',
        auth_type='oauth',
        name='work',
    )

    current_profile, profiles = list_profiles()

    assert current_profile == 'work'
    assert list(profiles) == ['work']
    assert profiles['work'].auth_type == 'oauth2'


def test_list_profiles_reads_acli_style_oauth_profile(monkeypatch, tmp_path):
    profiles_file = auth_profiles_file(monkeypatch, tmp_path)
    write_profile_config(
        profiles_file,
        current_profile='cloud-123:account-123',
        auth_type='oauth',
        name=None,
    )

    current_profile, profiles = list_profiles()

    assert current_profile == 'cloud-123:account-123'
    assert list(profiles) == ['cloud-123:account-123']
    assert profiles['cloud-123:account-123'].auth_type == 'oauth2'


def test_list_profiles_reads_acli_style_api_token_profile(monkeypatch, tmp_path):
    profiles_file = auth_profiles_file(monkeypatch, tmp_path)
    write_profile_config(
        profiles_file,
        current_profile='cloud-123:account-123',
        auth_type='api_token',
        name=None,
    )

    current_profile, profiles = list_profiles()

    assert current_profile == 'cloud-123:account-123'
    assert list(profiles) == ['cloud-123:account-123']
    assert profiles['cloud-123:account-123'].auth_type == 'basic'
