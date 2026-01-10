import asyncio
import logging
import sys
from typing import cast

import click
from pydantic import ValidationError
from rich.console import Console
from textual.theme import BUILTIN_THEMES

from gojeera.api_controller.controller import APIController
from gojeera.app import JiraApp
from gojeera.config import ApplicationConfiguration
from gojeera.constants import LOGGER_NAME
from gojeera.files import get_themes_directory
from gojeera.models import JiraMyselfInfo
from gojeera.themes import create_themes_from_config, load_themes_from_directory

console = Console()
logger = logging.getLogger(LOGGER_NAME)


async def check_authentication(
    settings: ApplicationConfiguration,
) -> tuple[bool, str | None, JiraMyselfInfo | None]:
    try:
        api_controller = APIController(configuration=settings)
        response = await api_controller.myself()

        try:
            await api_controller.api.client.close_async_client()
            await api_controller.api.async_http_client.close_async_client()
        except Exception as e:
            logger.debug(f'Failed to close async clients: {e}')

        if not response.success:
            if response.error:
                error = str(response.error) if response.error else 'Please check your credentials.'
                error_msg = error.lower()

                if 'unauthorized' in error_msg or '401' in error_msg:
                    return False, 'Please check your credentials.', None
                elif 'forbidden' in error_msg or '403' in error_msg:
                    return False, 'Access forbidden. Please check your permissions.', None
                elif 'not found' in error_msg or '404' in error_msg:
                    return False, 'Jira instance not found. Please check your API base URL.', None
                elif 'timeout' in error_msg or 'timed out' in error_msg:
                    return False, 'Connection timed out.', None
                elif 'connection' in error_msg:
                    return (
                        False,
                        'Connection error. Please check your network and Jira instance URL.',
                        None,
                    )

                elif 'contextvar' in error_msg or '<' in error_msg:
                    return False, 'Please check your credentials.', None
                else:
                    return False, error, None
            return False, 'Please check your credentials.', None

        if response.result is None:
            return False, 'Authentication succeeded but no user info received.', None

        user_info: JiraMyselfInfo = response.result
        return True, None, user_info

    except Exception as e:
        error = str(e)
        error_msg = error.lower()

        if 'contextvar' in error_msg or ('<' in error_msg and '0x' in error_msg):
            return False, 'Please check your credentials.', None
        elif 'certificate' in error_msg or 'ssl' in error_msg:
            return False, 'SSL certificate error.', None
        elif 'connection' in error_msg:
            return False, 'Connection error. Please check your network and Jira instance URL.', None
        elif 'timeout' in error_msg:
            return False, 'Connection timed out.', None
        else:
            return False, error, None


@click.command()
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
    '--version',
    is_flag=True,
    default=False,
    help='Show the version of the tool.',
)
def cli(
    project_key: str | None = None,
    work_item_key: str | None = None,
    assignee: str | None = None,
    jql_filter: str | None = None,
    theme: str | None = None,
    search_on_startup: bool = False,
    focus_item_on_startup: int | None = None,
    version: bool = False,
):
    """Launches gojeera."""

    if version:
        from importlib.metadata import version as get_version

        console.print(get_version('gojeera'))
        return

    if theme:
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
            console.print('The name of the theme you provided is not supported.')
            console.print('To see the list of supported themes, check the documentation.')
            sys.exit(1)

    exclusive_options = [project_key, work_item_key, jql_filter]
    provided_options = [opt for opt in exclusive_options if opt is not None]
    if len(provided_options) > 1:
        console.print(
            'Error: --project-key, --work-item-key, and --jql-filter are mutually exclusive.'
        )
        console.print('Please provide only one of these options.')
        sys.exit(1)

    import re

    if project_key:
        project_key_pattern = r'^[A-Z][A-Z0-9]{1,9}$'
        if not re.match(project_key_pattern, project_key):
            console.print(f'Error: Invalid project key format: "{project_key}"')
            console.print('Project keys must be 2-10 uppercase characters, starting with a letter.')
            console.print('Examples: PROJ, DEV, PLATFORM, ABC123')
            sys.exit(1)

    if work_item_key:
        work_item_pattern = r'^[A-Z][A-Z0-9]+-\d+$'
        if not re.match(work_item_pattern, work_item_key):
            console.print(f'Error: Invalid work item key format: "{work_item_key}"')
            console.print('Work item keys must follow the format: <PROJECT>-<NUMBER>')
            console.print('Examples: PROJ-123, ABC-456, DEV-1')
            sys.exit(1)

    if assignee is not None and project_key is None:
        console.print('Error: --assignee requires --project-key to be defined.')
        sys.exit(1)

    if focus_item_on_startup is not None:
        if not search_on_startup:
            console.print('--focus-item-on-startup requires --search-on-startup to be enabled.')
            sys.exit(1)
        if focus_item_on_startup < 1:
            console.print('--focus-item-on-startup must be a positive integer (1 or greater).')
            sys.exit(1)

    try:
        settings = ApplicationConfiguration()
        settings.search_on_startup = search_on_startup
    except FileNotFoundError as e:
        console.print(e)
        sys.exit(1)
    except ValidationError as e:
        console.print('Configuration validation error. Make sure your config file is correct.')
        for _e in e.errors():
            if location := _e.get('loc'):
                console.print(f'Configuration error at {location[0]}: {_e.get("msg")}')
            else:
                console.print(f'Configuration error: {_e.get("msg")}')
        sys.exit(1)

    success, error_message, user_info = asyncio.run(check_authentication(settings))

    if not success:
        console.print(f'[bold red]Authentication failed:[/bold red] {error_message}')
        sys.exit(1)

    JiraApp(
        settings,
        user_info=user_info,
        project_key=project_key,
        assignee=assignee,
        jql_filter=jql_filter,
        work_item_key=work_item_key,
        user_theme=theme,
        focus_item_on_startup=focus_item_on_startup,
    ).run()


def gojeeraCLI():
    cli()


if __name__ == '__main__':
    gojeeraCLI()
