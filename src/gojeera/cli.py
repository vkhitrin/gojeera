import logging
import re
import sys
from typing import cast

import click
import httpx
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.text import Text

from gojeera.auth_profiles import (
    ATLASSIAN_OAUTH2_AUTHORIZATION_URL,
    ATLASSIAN_OAUTH2_REDIRECT_URI,
    AuthProfile,
    BasicAuthProfile,
    OAuth2AuthProfile,
    list_profiles,
    remove_profile,
    upsert_profile,
)
from gojeera.auth_service import AuthProfileStatus, AuthService
from gojeera.constants import LOGGER_NAME
from gojeera.oauth2 import (
    EXTENDED_OAUTH2_SCOPES,
    AtlassianAccessibleResource,
    OAuth2TokenResponse,
    get_atlassian_accessible_resources,
    run_atlassian_oauth2_authorization_flow,
)
from gojeera.secret_store import (
    SecretStoreError,
    delete_jira_api_token,
    delete_jira_oauth2_access_token,
    delete_jira_oauth2_client_secret,
    delete_jira_oauth2_refresh_token,
    set_jira_api_token,
    set_jira_oauth2_access_token,
    set_jira_oauth2_client_secret,
    set_jira_oauth2_refresh_token,
)
from gojeera.utils.urls import extract_work_item_key

logger = logging.getLogger(LOGGER_NAME)
console = Console()
auth_service = AuthService()


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
    return 'OAuth2' if auth_type == 'oauth2' else 'Basic'


def _resolve_oauth2_resource(
    *, access_token: str, instance_url: str | None = None
) -> tuple[str, AtlassianAccessibleResource]:
    try:
        resources = get_atlassian_accessible_resources(access_token=access_token)
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f'Unable to retrieve Atlassian sites: {exc}') from exc

    matching_resources = resources
    if instance_url is not None:
        normalized_instance_url = _normalize_url_for_comparison(instance_url)
        matching_resources = [
            resource
            for resource in resources
            if _normalize_url_for_comparison(resource.url) == normalized_instance_url
        ]

    if not matching_resources:
        if instance_url is not None:
            raise click.ClickException(
                f'No Atlassian site matching {instance_url} was found for the provided OAuth2 token.'
            )
        raise click.ClickException('No Atlassian sites were found for the provided OAuth2 token.')

    if len(matching_resources) == 1:
        selected_resource = matching_resources[0]
        return selected_resource.id, selected_resource

    selected_resource_id = _select_option(
        'Atlassian site',
        [
            (resource.id, f'{resource.name} {resource.url}'.rstrip())
            for resource in matching_resources
        ],
    )
    selected_resource = next(
        resource for resource in matching_resources if resource.id == selected_resource_id
    )
    return selected_resource_id, selected_resource


def _run_oauth2_login_flow(
    *,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    redirect_uri: str | None = None,
    authorization_url: str | None = None,
) -> OAuth2TokenResponse:
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


def _resolve_existing_profile_selection() -> tuple[str, AuthProfile | None, bool]:
    active_profile, profiles = list_profiles()
    if not profiles:
        return _prompt_profile_name(), None, False

    profile_options: list[tuple[str, str]] = []
    profile_names = list(profiles.keys())
    for profile_name in profile_names:
        profile = profiles[profile_name]
        auth_type = profile.auth_type
        instance_url = profile.instance_url
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
    console.print(f'[bold]Profile[/bold]: {selected_label}')
    return selected_profile, profiles.get(selected_profile), True


def _select_option(title: str, options: list[tuple[str, str]], default_index: int = 0) -> str:
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
    def move_up(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(options)

    @key_bindings.add('down')
    @key_bindings.add('j')
    def move_down(event) -> None:
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

    if ctx.invoked_subcommand is not None:
        return

    if version:
        from importlib.metadata import version as get_version

        click.echo(get_version('gojeera'))
        return

    if theme:
        from textual.theme import BUILTIN_THEMES

        from gojeera.config import ApplicationConfiguration
        from gojeera.files import get_themes_directory
        from gojeera.themes import create_themes_from_config, load_themes_from_directory

        valid_themes = set(BUILTIN_THEMES.keys())

        try:
            themes_dir = get_themes_directory()
            directory_themes = load_themes_from_directory(themes_dir)
            valid_themes.update(t.name for t in directory_themes)
        except Exception as e:
            logger.debug(f'Failed to load themes from directory: {e}')

        try:
            settings = ApplicationConfiguration()
            if hasattr(settings, 'custom_themes'):
                custom_themes_attr = settings.custom_themes
                if custom_themes_attr:
                    config_themes = create_themes_from_config(cast(list[dict], custom_themes_attr))
                    valid_themes.update(t.name for t in config_themes)
        except Exception as e:
            logger.debug(f'Failed to load themes from config: {e}')

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

    from gojeera.config import ApplicationConfiguration

    try:
        settings = ApplicationConfiguration()
        if profile is not None:
            if profile not in settings.jira.profiles:
                click.echo(f'Authentication profile not found: {profile}')
                sys.exit(1)
            settings.jira.activate_profile(profile)
        settings.search_on_startup = search_on_startup
    except FileNotFoundError as e:
        click.echo(str(e))
        sys.exit(1)
    except (ValidationError, ValueError) as e:
        if isinstance(e, ValidationError):
            error_messages = [str(_e.get('msg', '')) for _e in e.errors()]
            if (
                'Value error, jira.active_profile is required when authentication profiles exist.'
                in error_messages
            ):
                click.echo(
                    'No active authentication profile is configured. '
                    'Use `gojeera auth login` to set one active or pass `--profile <name>`.'
                )
                sys.exit(1)
        elif str(e) == 'jira.active_profile is required when authentication profiles exist.':
            click.echo(
                'No active authentication profile is configured. '
                'Use `gojeera auth login` to set one active or pass `--profile <name>`.'
            )
            sys.exit(1)
        click.echo('Configuration validation error. Make sure your config file is correct.')
        if isinstance(e, ValidationError):
            for _e in e.errors():
                if location := _e.get('loc'):
                    click.echo(f'Configuration error at {location[0]}: {_e.get("msg")}')
                else:
                    click.echo(f'Configuration error: {_e.get("msg")}')
        else:
            click.echo(f'Configuration error: {e}')
        sys.exit(1)

    from gojeera.app import JiraApp

    JiraApp(
        settings,
        project_key=project_key,
        assignee=assignee,
        jql_filter=jql_filter,
        work_item_key=work_item_key,
        user_theme=theme,
        focus_item_on_startup=focus_item_on_startup,
    ).run()


@cli.group()
def auth():
    """Manage Jira secrets in the operating system secret store."""


@auth.command('login')
def auth_login():
    """Create a Jira auth profile and store its secret in the operating system secret store."""
    try:
        profile_name, existing_profile, is_edit_mode = _resolve_existing_profile_selection()
        existing_auth_type = existing_profile.auth_type if existing_profile is not None else None
        auth_type_options = [
            ('basic', 'Basic (email + API token)'),
            ('oauth2', 'OAuth2'),
        ]
        auth_type = _select_option(
            'Authentication type',
            auth_type_options,
            default_index=0 if existing_auth_type != 'oauth2' else 1,
        )
        auth_type_label = next(label for value, label in auth_type_options if value == auth_type)
        console.print(f'[bold]Authentication type[/bold]: {auth_type_label}')

        if not profile_name:
            click.echo('Profile name is required.')
            sys.exit(1)

        if auth_type == 'oauth2':
            console.print('[bold magenta]OAuth2 Settings[/bold magenta]')
            existing_instance_url = (
                existing_profile.instance_url
                if isinstance(existing_profile, OAuth2AuthProfile)
                else None
            )
            existing_client_id = (
                existing_profile.client_id
                if isinstance(existing_profile, OAuth2AuthProfile) and existing_profile.client_id
                else ''
            )
            console.print('[bold]OAuth2 scope mode[/bold]: Extended + User Identity')
            client_id = Prompt.ask(
                '[bold]Atlassian client ID[/bold]', default=existing_client_id
            ).strip()
            authorization_url = ATLASSIAN_OAUTH2_AUTHORIZATION_URL
            redirect_uri = ATLASSIAN_OAUTH2_REDIRECT_URI
            scopes = EXTENDED_OAUTH2_SCOPES
            client_secret_prompt = (
                '[bold]Atlassian client secret[/bold] [dim](leave blank to keep existing)[/dim]'
                if is_edit_mode
                else '[bold]Atlassian client secret[/bold]'
            )
            client_secret = Prompt.ask(client_secret_prompt, password=True, default='').strip()
            scopes_text = Text('Requested OAuth2 scopes: ', style='cyan')
            scopes_text.append(', '.join(scopes))
            console.print(scopes_text)
            console.print(
                '[cyan]Runtime OAuth2 refresh scope:[/cyan] offline_access '
                '[dim](requested in the authorize URL, not configured in the developer console)[/dim]'
            )

            if not client_id:
                click.echo('Atlassian client ID is required.')
                sys.exit(1)
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
                    name=profile_name,
                    instance_url=instance_url,
                    cloud_id=cloud_id,
                    client_id=client_id,
                    account_display_name=None,
                    scopes=scopes,
                ),
                access_token=access_token,
            )
            if not validation_result.is_valid:
                click.echo(f'Authentication validation failed: {validation_result.message}')
                sys.exit(1)

            activate = Confirm.ask('[bold]Set as active profile?[/bold]', default=True)

            upsert_profile(
                profile_name,
                auth_type='oauth2',
                instance_url=instance_url,
                email=None,
                account_display_name=validation_result.message,
                cloud_id=cloud_id,
                client_id=client_id,
                scopes=scopes,
                activate=activate,
            )
            set_jira_oauth2_access_token(instance_url, cloud_id, access_token)
            set_jira_oauth2_refresh_token(instance_url, cloud_id, token_response.refresh_token)
            set_jira_oauth2_client_secret(instance_url, cloud_id, client_secret)
        else:
            console.print('[bold green]Basic Auth Settings[/bold green]')
            existing_instance_url = (
                existing_profile.instance_url
                if isinstance(existing_profile, BasicAuthProfile)
                else ''
            )
            existing_email = (
                existing_profile.email if isinstance(existing_profile, BasicAuthProfile) else ''
            )
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
            if not api_token and is_edit_mode and isinstance(existing_profile, BasicAuthProfile):
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
                    instance_url=instance_url,
                    email=email,
                ),
                api_token=api_token,
            )
            if not validation_result.is_valid:
                click.echo(f'Authentication validation failed: {validation_result.message}')
                sys.exit(1)

            activate = Confirm.ask('[bold]Set as active profile?[/bold]', default=True)

            upsert_profile(
                profile_name,
                auth_type='basic',
                instance_url=instance_url,
                email=email,
                account_display_name=None,
                cloud_id=None,
                client_id=None,
                scopes=None,
                activate=activate,
            )
            set_jira_api_token(instance_url, email, api_token)
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
            instance_url = profile.instance_url
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
            if delete_jira_oauth2_access_token(profile.instance_url, profile.cloud_id):
                pass
            if delete_jira_oauth2_refresh_token(profile.instance_url, profile.cloud_id):
                pass
            if delete_jira_oauth2_client_secret(profile.instance_url, profile.cloud_id):
                pass
        else:
            if delete_jira_api_token(profile.instance_url, profile.email):
                pass
    except SecretStoreError as e:
        click.echo(str(e))
        sys.exit(1)

    remove_profile(selected_profile_name)


@auth.command('status')
@click.option('--show-token', is_flag=True, help='Show a truncated token preview.')
def auth_status(show_token: bool):
    """Show auth profile status."""

    active_profile, profiles = list_profiles()
    if not profiles:
        click.echo('No profiles configured.')
        return

    for index, (profile_name, profile) in enumerate(profiles.items()):
        status: AuthProfileStatus = auth_service.get_profile_status(
            profile_name,
            profile,
            active_profile_name=active_profile,
        )

        click.echo(status.profile.instance_url or profile_name)
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

        if isinstance(status.profile, OAuth2AuthProfile) and status.profile.scopes:
            formatted_scopes = ', '.join(f"'{scope}'" for scope in status.profile.scopes)
            click.echo(f'  - Token scopes: {formatted_scopes}')

        if index < len(profiles) - 1:
            click.echo()


def gojeeraCLI():
    cli()


if __name__ == '__main__':
    gojeeraCLI()
