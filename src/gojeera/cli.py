from __future__ import annotations

import asyncio
import logging
import re
import sys
from typing import TYPE_CHECKING, Any, cast

import click
import httpx
from rich.prompt import Confirm, Prompt

from gojeera.internal.auth.oauth2 import OAUTH2_SCOPES, get_atlassian_accessible_resources
from gojeera.internal.auth.profiles import (
    ATLASSIAN_OAUTH2_AUTHORIZATION_URL,
    ATLASSIAN_OAUTH2_REDIRECT_URI,
    BasicAuthProfile,
    OAuth2AuthProfile,
    list_profiles,
    remove_profile,
    upsert_profile,
)
from gojeera.internal.store.secret import (
    SecretStoreError,
    delete_jira_api_token,
    delete_jira_oauth2_client_id,
    delete_jira_oauth2_client_secret,
    delete_jira_oauth2_refresh_token,
    set_jira_api_token,
    set_jira_oauth2_client_id,
    set_jira_oauth2_client_secret,
    set_jira_oauth2_refresh_token,
)
from gojeera.utils.jira.urls import extract_work_item_key

if TYPE_CHECKING:
    from rich.console import Console

    from gojeera.internal.auth.oauth2 import AtlassianAccessibleResource, OAuth2TokenResponse
    from gojeera.internal.auth.profiles import AuthProfile
    from gojeera.internal.auth.service import AuthProfileStatus

from gojeera.internal.auth.service import AuthService

logger = logging.getLogger('gojeera')
_console: Console | None = None


def _get_console() -> Console:
    global _console
    if _console is None:
        from rich.console import Console

        _console = Console()
    return _console


auth_service = AuthService()


def _echo_invalid_auth_profile_error(message: str) -> bool:
    match = re.fullmatch(r'Invalid auth profile "([^"]+)": (.+)', message)
    if match is None:
        return False

    profile_name, details = match.groups()
    click.secho(f'Invalid auth profile "{profile_name}": {details}.', fg='red')
    return True


def _echo_invalid_configuration_field_error(message: str) -> bool:
    match = re.fullmatch(r'Invalid configuration field "([^"]+)"', message)
    if match is None:
        return False

    click.secho(f'Invalid configuration field "{match.group(1)}".', fg='red')
    return True


def _echo_invalid_theme_file_error(message: str) -> bool:
    match = re.fullmatch(r'Invalid theme file "([^"]+)": (.+)', message)
    if match is None:
        return False

    theme_file, details = match.groups()
    click.secho(f'Invalid theme file "{theme_file}": {details}.', fg='red')
    return True


def _format_validation_error_location(location: tuple[Any, ...] | list[Any]) -> str:
    path_parts: list[str] = []
    for item in location:
        if item == '__root__':
            continue
        if isinstance(item, int):
            if not path_parts:
                path_parts.append(f'[{item}]')
            else:
                path_parts[-1] = f'{path_parts[-1]}[{item}]'
            continue
        path_parts.append(str(item))
    return '.'.join(path_parts)


def _echo_invalid_configuration_validation_error(exc: Exception) -> bool:
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return False

    field_paths: list[str] = []
    for error in exc.errors():
        if error.get('type') not in {'extra_forbidden', 'unexpected_keyword_argument'}:
            return False
        location = error.get('loc')
        if not location:
            return False
        field_paths.append(_format_validation_error_location(cast(tuple[Any, ...], location)))

    for field_path in dict.fromkeys(field_paths):
        click.secho(f'Invalid configuration field "{field_path}".', fg='red')
    return bool(field_paths)


def _refresh_oauth2_access_token_on_startup(settings: Any) -> None:
    active_profile = settings.jira.active_profile
    if not isinstance(active_profile, OAuth2AuthProfile):
        return
    if (
        settings.jira.oauth2_access_token is not None
        and not auth_service.should_refresh_oauth2_access_token_on_startup(active_profile)
    ):
        return

    token_response = auth_service.refresh_oauth2_access_token(active_profile)
    settings.jira.update_active_oauth2_session(
        access_token=token_response.access_token,
        refresh_token=token_response.refresh_token,
        oauth2_access_token_expiration_timestamp=token_response.access_token_expiration_timestamp,
    )


def _clear_inline_selector(lines: int) -> None:
    if lines <= 0:
        return

    # Move back through the rendered selector block and clear it line by line.
    for _ in range(lines):
        sys.stdout.write('\r\x1b[2K')
        sys.stdout.write('\x1b[1A')
    sys.stdout.write('\r\x1b[2K')
    sys.stdout.flush()


def _normalize_url_for_comparison(url: str) -> str:
    return re.sub(r'/$', '', url.strip().lower())


def _mask_token(token: str | None) -> str:
    if not token:
        return 'not found'
    return '********'


def _format_auth_type_label(auth_type: str) -> str:
    return 'OAuth2' if auth_type == 'oauth2' else 'API token'


async def _get_auth_profile_statuses(
    profiles: dict[str, AuthProfile],
    *,
    active_profile: str | None,
) -> list[AuthProfileStatus]:
    tasks = [
        asyncio.to_thread(
            auth_service.get_profile_status,
            profile_name,
            profile,
            active_profile_name=active_profile,
        )
        for profile_name, profile in profiles.items()
    ]
    return list(await asyncio.gather(*tasks))


def _print_selected_oauth2_resource(resource: AtlassianAccessibleResource) -> None:
    label = f'{resource.name} {resource.url}'.strip()
    _get_console().print(f'[bold]Selected Atlassian site[/bold]: [cyan]{label}[/cyan]')


def _resolve_oauth2_resource(
    *, access_token: str, instance_url: str | None = None
) -> tuple[str, AtlassianAccessibleResource]:
    import httpx

    try:
        resources = get_atlassian_accessible_resources(access_token=access_token)
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f'Unable to retrieve Atlassian sites: {exc}') from exc

    if not resources:
        raise click.ClickException('No Atlassian sites were found for the provided OAuth2 token.')

    if len(resources) == 1:
        resource = resources[0]
        _print_selected_oauth2_resource(resource)
        return resource.id, resource

    default_index = 0
    if instance_url is not None:
        normalized_instance_url = _normalize_url_for_comparison(instance_url)
        matching_index = next(
            (
                index
                for index, resource in enumerate(resources)
                if _normalize_url_for_comparison(resource.url) == normalized_instance_url
            ),
            None,
        )
        if matching_index is not None:
            default_index = matching_index

    selected_resource_id = _select_option(
        'Atlassian site',
        [(resource.id, f'{resource.name} {resource.url}'.rstrip()) for resource in resources],
        default_index=default_index,
    )
    selected_resource = next(
        resource for resource in resources if resource.id == selected_resource_id
    )
    _print_selected_oauth2_resource(selected_resource)
    return selected_resource_id, selected_resource


def _run_oauth2_login_flow(
    *,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    redirect_uri: str | None = None,
    authorization_url: str | None = None,
) -> OAuth2TokenResponse:
    from gojeera.internal.auth.oauth2 import run_atlassian_oauth2_authorization_flow

    return run_atlassian_oauth2_authorization_flow(
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        redirect_uri=redirect_uri or ATLASSIAN_OAUTH2_REDIRECT_URI,
        authorization_url=authorization_url or ATLASSIAN_OAUTH2_AUTHORIZATION_URL,
    )


def _prompt_profile_name() -> str:
    while True:
        profile_name = Prompt.ask('[bold]Profile name[/bold]').strip()
        if profile_name:
            return profile_name


def _prompt_masked_secret(prompt_text: str, *, default: str = '') -> str:
    return Prompt.ask(prompt_text, password=True, default=default).strip()


def _resolve_existing_profile_selection() -> tuple[str, AuthProfile | None, bool]:
    active_profile, profiles = list_profiles()
    if not profiles:
        return _prompt_profile_name(), None, False

    profile_options: list[tuple[str, str]] = []
    profile_names = list(profiles.keys())
    for profile_name in profile_names:
        profile = profiles[profile_name]
        auth_type = profile.auth_type
        instance_url = profile.site
        marker = ' (active)' if profile_name == active_profile else ''
        profile_options.append(
            (profile_name, f'{profile_name} [{auth_type}] {instance_url}{marker}'.rstrip())
        )
    profile_options.append(('__new__', 'Create new profile'))

    default_index = 0
    if active_profile in profile_names:
        default_index = profile_names.index(active_profile)

    selected_profile = _select_option('Profile', profile_options, default_index=default_index)
    if selected_profile == '__new__':
        return _prompt_profile_name(), None, False
    selected_label = next(label for value, label in profile_options if value == selected_profile)
    _get_console().print(f'[bold]Profile[/bold]: {selected_label}')
    return selected_profile, profiles.get(selected_profile), True


def _select_option(title: str, options: list[tuple[str, str]], default_index: int = 0) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    selected_index = default_index
    rendered_line_count = len(title.splitlines()) + len(options) + 1

    def get_fragments():
        fragments: list[tuple[str, str]] = [('class:title', f'{title}:\n')]
        for index, (_, label) in enumerate(options):
            prefix = '› ' if index == selected_index else '  '
            style = 'reverse' if index == selected_index else ''
            fragments.append((style, f'{prefix}{label}\n'))
        return fragments

    key_bindings = KeyBindings()

    @key_bindings.add('up')
    @key_bindings.add('k')
    def move_up(_event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(options)

    @key_bindings.add('down')
    @key_bindings.add('j')
    def move_down(_event) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(options)

    @key_bindings.add('enter')
    def accept(event) -> None:
        event.app.exit(result=options[selected_index][0])

    @key_bindings.add('c-c')
    @key_bindings.add('escape')
    def cancel(event) -> None:
        event.app.exit(result=None)

    application = Application(
        layout=Layout(
            Window(FormattedTextControl(get_fragments, focusable=True, show_cursor=False))
        ),
        key_bindings=key_bindings,
        full_screen=False,
        style=Style.from_dict({'title': 'bold'}),
    )
    result = application.run()
    _clear_inline_selector(rendered_line_count)
    if result is None:
        sys.exit(1)
    selected_value = cast(str, result)
    return selected_value


@click.group(invoke_without_command=True)
@click.option('--project-key', '-p', default=None, help='A case-sensitive Jira project key.')
@click.option('--work-item-key', '-w', default=None, help='A case-sensitive work item key.')
@click.option(
    '--assignee',
    '-u',
    default=None,
    help='A Jira user display name or account ID to pre-select in the assignee dropdown.',
)
@click.option(
    '--jql-filter',
    '-j',
    default=None,
    type=str,
    help='The label of a JQL filter query to load on startup, as defined in the config.',
)
@click.option('--theme', '-t', default=None, help='The name of the theme to use.')
@click.option(
    '--search-on-startup',
    is_flag=True,
    default=False,
    help='Trigger search automatically when the UI starts.',
)
@click.option(
    '--focus-item-on-startup',
    '-f',
    default=None,
    type=int,
    help='Focus and open the work item at the specified position on startup. Requires --search-on-startup.',
)
@click.option(
    '--profile',
    default=None,
    help='The authentication profile to use for this invocation.',
)
@click.option(
    '--version',
    is_flag=True,
    default=False,
    help='Show the version of the tool.',
)
@click.pass_context
def cli(
    ctx: click.Context,
    project_key: str | None = None,
    work_item_key: str | None = None,
    assignee: str | None = None,
    jql_filter: str | None = None,
    theme: str | None = None,
    search_on_startup: bool = False,
    focus_item_on_startup: int | None = None,
    profile: str | None = None,
    version: bool = False,
):
    """Launches gojeera."""
    directory_themes = None

    if ctx.invoked_subcommand is not None:
        return

    if version:
        from importlib.metadata import version as get_version

        click.echo(get_version('gojeera'))
        return

    if theme:
        from textual.theme import BUILTIN_THEMES

        from gojeera.internal.store.config import ApplicationConfiguration
        from gojeera.internal.store.files import get_themes_directory
        from gojeera.internal.styling.themes import (
            create_themes_from_config,
            load_themes_from_directory,
        )

        valid_themes = set(BUILTIN_THEMES.keys())

        try:
            themes_dir = get_themes_directory()
            directory_themes = load_themes_from_directory(themes_dir)
            valid_themes.update(t.name for t in directory_themes)
        except ValueError as e:
            if _echo_invalid_theme_file_error(str(e)):
                sys.exit(1)
            raise
        except Exception:
            pass

        try:
            settings = ApplicationConfiguration()
            if hasattr(settings, 'custom_themes'):
                custom_themes_attr = settings.custom_themes
                if custom_themes_attr:
                    config_themes = create_themes_from_config(custom_themes_attr)
                    valid_themes.update(t.name for t in config_themes)
        except Exception:
            pass

        if theme not in valid_themes:
            click.echo('The name of the theme you provided is not supported.')
            click.echo('To see the list of supported themes, check the documentation.')
            sys.exit(1)

    exclusive_options = [project_key, work_item_key, jql_filter]
    provided_options = [opt for opt in exclusive_options if opt is not None]
    if len(provided_options) > 1:
        click.echo(
            'Error: --project-key, --work-item-key, and --jql-filter are mutually exclusive.'
        )
        click.echo('Please provide only one of these options.')
        sys.exit(1)

    if work_item_key and search_on_startup:
        click.echo('Error: --search-on-startup cannot be used with --work-item-key.')
        click.echo('--work-item-key already triggers the initial search automatically.')
        sys.exit(1)

    if project_key:
        project_key_pattern = r'^[A-Z][A-Z0-9]{1,9}$'
        if not re.match(project_key_pattern, project_key):
            click.echo(f'Error: Invalid project key format: "{project_key}"')
            click.echo('Project keys must be 2-10 uppercase characters, starting with a letter.')
            click.echo('Examples: PROJ, DEV, PLATFORM, ABC123')
            sys.exit(1)

    if work_item_key:
        raw_work_item_key = work_item_key
        if (work_item_key := extract_work_item_key(raw_work_item_key)) is None:
            click.echo(f'Error: Invalid work item key format: "{raw_work_item_key}"')
            click.echo(
                'Work item keys must follow the format <PROJECT>-<NUMBER> or be a Jira browse URL.'
            )
            click.echo(
                'Examples: PROJ-123, ABC-456, DEV-1, https://your-domain.atlassian.net/browse/PROJ-123'
            )
            sys.exit(1)

    if assignee is not None and project_key is None:
        click.echo('Error: --assignee requires --project-key to be defined.')
        sys.exit(1)

    if focus_item_on_startup is not None:
        if not search_on_startup:
            click.echo('--focus-item-on-startup requires --search-on-startup to be enabled.')
            sys.exit(1)
        if focus_item_on_startup < 1:
            click.echo('--focus-item-on-startup must be a positive integer (1 or greater).')
            sys.exit(1)

    from pydantic import ValidationError

    from gojeera.internal.store.config import ApplicationConfiguration

    try:
        settings = ApplicationConfiguration()
        if profile is not None:
            if profile not in settings.jira.profiles:
                click.echo(f'Authentication profile not found: {profile}')
                sys.exit(1)
            settings.jira.activate_profile(profile)
        try:
            _refresh_oauth2_access_token_on_startup(settings)
        except (httpx.HTTPError, SecretStoreError, ValueError) as e:
            click.echo(f'Authentication refresh failed during startup: {e}')
            sys.exit(1)
        settings.search_on_startup = search_on_startup
    except FileNotFoundError as e:
        click.echo(str(e))
        sys.exit(1)
    except (ValidationError, ValueError) as e:
        if isinstance(e, ValueError) and _echo_invalid_auth_profile_error(str(e)):
            sys.exit(1)
        if isinstance(e, ValueError) and _echo_invalid_configuration_field_error(str(e)):
            sys.exit(1)
        if _echo_invalid_configuration_validation_error(e):
            sys.exit(1)

        def echo_config_error(message: str) -> None:
            click.secho(message, fg='red')

        missing_credentials_message = (
            'No Jira credentials are configured. '
            'Use `gojeera auth login` to configure your credentials.'
        )
        if isinstance(e, ValidationError):
            error_messages = [str(_e.get('msg', '')) for _e in e.errors()]
            if (
                'Value error, jira.active_profile is required when authentication profiles exist.'
                in error_messages
            ):
                echo_config_error(
                    'No active authentication profile is configured. '
                    'Use `gojeera auth login` to set one active or pass `--profile <name>`.'
                )
                sys.exit(1)
            if any(
                'Value error, No Jira authentication is configured.' in msg
                for msg in error_messages
            ):
                echo_config_error(missing_credentials_message)
                sys.exit(1)
        elif str(e) == 'jira.active_profile is required when authentication profiles exist.':
            echo_config_error(
                'No active authentication profile is configured. '
                'Use `gojeera auth login` to set one active or pass `--profile <name>`.'
            )
            sys.exit(1)
        elif str(e).startswith('No Jira authentication is configured.'):
            echo_config_error(missing_credentials_message)
            sys.exit(1)
        echo_config_error('Configuration validation error. Make sure your config file is correct.')
        if isinstance(e, ValidationError):
            for _e in e.errors():
                if location := _e.get('loc'):
                    echo_config_error(f'Configuration error at {location[0]}: {_e.get("msg")}')
                else:
                    echo_config_error(f'Configuration error: {_e.get("msg")}')
        else:
            echo_config_error(f'Configuration error: {e}')
        sys.exit(1)

    from gojeera.app import JiraApp

    try:
        JiraApp(
            settings,
            directory_themes=directory_themes,
            project_key=project_key,
            assignee=assignee,
            jql_filter=jql_filter,
            work_item_key=work_item_key,
            user_theme=theme,
            focus_item_on_startup=focus_item_on_startup,
        ).run()
    except ValueError as e:
        if _echo_invalid_theme_file_error(str(e)):
            sys.exit(1)
        raise


@cli.group()
def auth():
    """Manage Jira secrets in the operating system secret store."""


@auth.command('login')
def auth_login():
    """Create a Jira auth profile and store its secret in the operating system secret store."""
    from rich.text import Text

    console = _get_console()

    try:
        profile_name, existing_profile, is_edit_mode = _resolve_existing_profile_selection()
        existing_auth_type = existing_profile.auth_type if existing_profile is not None else None
        auth_type_options = [
            ('basic', 'API token'),
            ('oauth2', 'OAuth2'),
        ]
        auth_type = _select_option(
            'Authentication type',
            auth_type_options,
            default_index=0 if existing_auth_type != 'oauth2' else 1,
        )
        auth_type_label = next(label for value, label in auth_type_options if value == auth_type)
        console.print(f'[bold]Authentication type[/bold]: {auth_type_label}')

        if auth_type == 'oauth2':
            console.print('[bold magenta]OAuth2 Settings[/bold magenta]')
            console.print(
                '[dim]Create or manage your Atlassian OAuth 2.0 app at '
                'https://developer.atlassian.com/[/dim]'
            )
            existing_instance_url = (
                existing_profile.site if isinstance(existing_profile, OAuth2AuthProfile) else None
            )
            existing_client_id = (
                auth_service.get_oauth2_client_id(existing_profile, prefer_environment=False)
                if isinstance(existing_profile, OAuth2AuthProfile)
                else ''
            ) or ''
            client_id = Prompt.ask(
                '[bold]Atlassian client ID[/bold]', default=existing_client_id
            ).strip()
            authorization_url = ATLASSIAN_OAUTH2_AUTHORIZATION_URL
            redirect_uri = ATLASSIAN_OAUTH2_REDIRECT_URI
            scopes = OAUTH2_SCOPES
            client_secret_prompt = (
                '[bold]Atlassian client secret[/bold] [dim](leave blank to keep existing)[/dim]'
                if is_edit_mode
                else '[bold]Atlassian client secret[/bold]'
            )
            client_secret = _prompt_masked_secret(client_secret_prompt, default='')
            scopes_text = Text('Requested OAuth2 scopes: ', style='cyan')
            scopes_text.append(', '.join(scopes))
            console.print(scopes_text)

            if not client_id:
                click.echo('Atlassian client ID is required.')
                sys.exit(1)
            skip_oauth_login = (
                is_edit_mode
                and isinstance(existing_profile, OAuth2AuthProfile)
                and client_id == existing_client_id
                and not client_secret
            )
            if skip_oauth_login:
                oauth_site = existing_profile.site
                oauth_account_id = existing_profile.account_id
                oauth_display_name = existing_profile.display_name
                oauth_cloud_id = existing_profile.cloud_id
                oauth_client_id = existing_profile.client_id
                oauth_email = existing_profile.email
                oauth_access_token_expiration_timestamp = (
                    existing_profile.oauth2_access_token_expiration_timestamp
                )
            else:
                if (
                    not client_secret
                    and is_edit_mode
                    and isinstance(existing_profile, OAuth2AuthProfile)
                ):
                    client_secret = (
                        auth_service.get_oauth2_client_secret(
                            existing_profile, prefer_environment=False
                        )
                        or ''
                    )
                if not client_secret:
                    click.echo('Atlassian client secret is required.')
                    sys.exit(1)

                console.print(
                    '[cyan]Waiting for Atlassian authorization in your browser on '
                    f'{redirect_uri}[/cyan]'
                )
                token_response = _run_oauth2_login_flow(
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=scopes,
                    redirect_uri=redirect_uri,
                    authorization_url=authorization_url,
                )
                access_token = token_response.access_token
                if not access_token:
                    click.echo('OAuth2 login did not return an access token.')
                    sys.exit(1)
                if token_response.refresh_token is None:
                    click.echo(
                        'OAuth2 login did not return a refresh token. Make sure offline_access scope is granted.'
                    )
                    sys.exit(1)

                cloud_id, selected_resource = _resolve_oauth2_resource(
                    access_token=access_token,
                    instance_url=existing_instance_url,
                )
                instance_url = selected_resource.url.rstrip('/')

                validation_result = auth_service.validate_profile(
                    OAuth2AuthProfile(
                        name='oauth',
                        site=instance_url,
                        cloud_id=cloud_id,
                        account_id=None,
                        client_id=client_id,
                        display_name=None,
                    ),
                    access_token=access_token,
                )
                if not validation_result.is_valid:
                    click.echo(f'Authentication validation failed: {validation_result.message}')
                    sys.exit(1)
                if validation_result.account_id is None:
                    click.echo('OAuth2 login did not return an Atlassian account ID.')
                    sys.exit(1)

                oauth_site = instance_url
                oauth_account_id = validation_result.account_id
                oauth_display_name = validation_result.message
                oauth_cloud_id = cloud_id
                oauth_client_id = client_id
                oauth_email = validation_result.email
                oauth_access_token_expiration_timestamp = (
                    token_response.access_token_expiration_timestamp
                )

            activate = Confirm.ask('[bold]Set as active profile?[/bold]', default=True)

            upsert_profile(
                profile_name,
                auth_type='oauth2',
                site=oauth_site,
                email=oauth_email,
                account_id=oauth_account_id,
                display_name=oauth_display_name,
                cloud_id=oauth_cloud_id,
                client_id=oauth_client_id,
                oauth2_access_token_expiration_timestamp=oauth_access_token_expiration_timestamp,
                activate=activate,
            )
            if not skip_oauth_login:
                if oauth_account_id is None:
                    click.echo('OAuth2 login did not return an Atlassian account ID.')
                    sys.exit(1)
                refresh_token = cast(str, token_response.refresh_token)
                set_jira_oauth2_refresh_token(oauth_account_id, refresh_token)
                set_jira_oauth2_client_secret(oauth_account_id, client_secret)
                set_jira_oauth2_client_id(oauth_account_id, client_id)
        else:
            console.print('[bold green]API Token Settings[/bold green]')
            existing_instance_url = (
                existing_profile.site if isinstance(existing_profile, BasicAuthProfile) else ''
            )
            existing_email = existing_profile.existing_email() if existing_profile else ''
            instance_url = (
                Prompt.ask('[bold]Jira instance URL[/bold]', default=existing_instance_url)
                .strip()
                .rstrip('/')
            )
            email = Prompt.ask('[bold]Jira email[/bold]', default=existing_email).strip()
            api_token_prompt = (
                '[bold]Jira API token[/bold] [dim](leave blank to keep existing)[/dim]'
                if is_edit_mode
                else '[bold]Jira API token[/bold]'
            )
            api_token = Prompt.ask(api_token_prompt, password=True, default='').strip()

            if not instance_url:
                click.echo('Jira instance URL is required.')
                sys.exit(1)
            if not email:
                click.echo('Email and Jira API token are required.')
                sys.exit(1)
            skip_basic_login = (
                is_edit_mode
                and isinstance(existing_profile, BasicAuthProfile)
                and instance_url == existing_instance_url
                and email == existing_email
                and not api_token
            )
            if skip_basic_login:
                basic_site = existing_profile.site
                basic_email = existing_profile.email
                basic_account_id = existing_profile.account_id
                basic_display_name = existing_profile.display_name
                basic_cloud_id = existing_profile.cloud_id
            else:
                if (
                    not api_token
                    and is_edit_mode
                    and isinstance(existing_profile, BasicAuthProfile)
                ):
                    api_token = (
                        auth_service.get_basic_api_token(existing_profile, prefer_environment=False)
                        or ''
                    )
                if not api_token:
                    click.echo('Email and Jira API token are required.')
                    sys.exit(1)

                validation_result = auth_service.validate_profile(
                    BasicAuthProfile(
                        name=profile_name,
                        site=instance_url,
                        email=email,
                    ),
                    api_token=api_token,
                )
                if not validation_result.is_valid:
                    click.echo(f'Authentication validation failed: {validation_result.message}')
                    sys.exit(1)

                basic_site = instance_url
                basic_email = email
                basic_account_id = validation_result.account_id
                basic_display_name = validation_result.message
                basic_cloud_id = validation_result.cloud_id

            activate = Confirm.ask('[bold]Set as active profile?[/bold]', default=True)

            upsert_profile(
                profile_name,
                auth_type='basic',
                site=basic_site,
                email=basic_email,
                account_id=basic_account_id,
                display_name=basic_display_name,
                cloud_id=basic_cloud_id,
                client_id=None,
                oauth2_access_token_expiration_timestamp=None,
                activate=activate,
            )

            if not skip_basic_login:
                set_jira_api_token(email, api_token)
    except (click.Abort, KeyboardInterrupt):
        sys.exit(1)
    except SecretStoreError as e:
        click.echo(str(e))
        sys.exit(1)

    action_label = 'Updated profile' if is_edit_mode else 'Created profile'
    console.print(f'[bold green]{action_label}[/bold green] [cyan]{profile_name}[/cyan].')


@auth.command('logout')
@click.argument('profile_name', required=False)
def auth_logout(profile_name: str | None):
    """Remove a profile and its stored Jira secrets."""
    active_profile, profiles = list_profiles()
    if not profiles:
        click.echo('No profiles configured.')
        return

    selected_profile_name = profile_name
    if selected_profile_name is None:
        profile_options = []
        for current_profile_name, profile in profiles.items():
            auth_type = profile.auth_type
            instance_url = profile.site
            marker = ' (active)' if current_profile_name == active_profile else ''
            profile_options.append(
                (
                    current_profile_name,
                    f'{current_profile_name} [{auth_type}] {instance_url}{marker}'.rstrip(),
                )
            )
        selected_profile_name = _select_option('Profile to remove', profile_options)

    if selected_profile_name is None or selected_profile_name not in profiles:
        click.echo(f'Profile not found: {selected_profile_name}')
        sys.exit(1)

    profile = profiles[selected_profile_name]

    try:
        if isinstance(profile, OAuth2AuthProfile):
            if profile.account_id and delete_jira_oauth2_refresh_token(profile.account_id):
                pass
            if profile.account_id and delete_jira_oauth2_client_secret(profile.account_id):
                pass
            if profile.account_id and delete_jira_oauth2_client_id(profile.account_id):
                pass
        else:
            if delete_jira_api_token(profile.email):
                pass
    except SecretStoreError as e:
        click.echo(str(e))
        sys.exit(1)

    remove_profile(selected_profile_name)


@auth.command('status')
@click.option('--show-token', is_flag=True, help='Show a truncated token preview.')
def auth_status(show_token: bool):
    """Show auth profile status."""
    console = _get_console()

    active_profile, profiles = list_profiles()
    if not profiles:
        click.echo('No profiles configured.')
        return

    statuses = asyncio.run(_get_auth_profile_statuses(profiles, active_profile=active_profile))
    for index, status in enumerate(statuses):
        click.echo(status.profile.site or status.profile_name)
        if status.validation.is_valid:
            console.print(
                f'  [green]\u2713[/green] Logged in as {status.validation.message} ({status.token_source})'
            )
        else:
            console.print(f'  [red]\u2717[/red] Login check failed ({status.token_source})')
            click.echo(f'  - Validation error: {status.validation.message}')

        click.echo(f'  - Profile: {status.profile_name}')
        click.echo(f'  - Active profile: {"true" if status.is_active else "false"}')
        click.echo(f'  - Authentication type: {_format_auth_type_label(status.profile.auth_type)}')
        click.echo(f'  - Token: {status.token if show_token else _mask_token(status.token)}')
        if show_token:
            click.echo(f'  - Token source: {status.token_source}')

        if scopes := status.profile.oauth_scopes():
            formatted_scopes = ', '.join(f"'{scope}'" for scope in scopes)
            click.echo(f'  - Token scopes: {formatted_scopes}')

        if index < len(statuses) - 1:
            click.echo()


def gojeeraCLI():
    cli()


if __name__ == '__main__':
    gojeeraCLI()
