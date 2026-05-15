def write_config_and_set_basic_auth(monkeypatch, tmp_path, *lines: str):
    config_file = tmp_path / 'gojeera.yaml'
    config_file.write_text('\n'.join(lines))
    monkeypatch.setenv('GOJEERA_CONFIG_FILE', str(config_file))
    monkeypatch.setenv('GOJEERA_AUTH_PROFILES_FILE', str(tmp_path / 'auth_profiles.yaml'))
    monkeypatch.setenv('GOJEERA_JIRA__API_EMAIL', 'testuser@example.com')
    monkeypatch.setenv('GOJEERA_JIRA__API_BASE_URL', 'https://example.atlassian.acme.net')
    monkeypatch.setenv('GOJEERA_JIRA__API_TOKEN', 'token')
    return config_file


def write_custom_theme_config(monkeypatch, tmp_path, *theme_lines: str):
    return write_config_and_set_basic_auth(
        monkeypatch,
        tmp_path,
        'custom_themes:',
        *theme_lines,
    )
