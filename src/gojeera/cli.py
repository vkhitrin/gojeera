import logging
import re
import sys
from typing import cast

import click

from gojeera.constants import LOGGER_NAME
from gojeera.utils.urls import extract_work_item_key

logger = logging.getLogger(LOGGER_NAME)


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
        settings.search_on_startup = search_on_startup
    except FileNotFoundError as e:
        click.echo(str(e))
        sys.exit(1)
    except ValidationError as e:
        click.echo('Configuration validation error. Make sure your config file is correct.')
        for _e in e.errors():
            if location := _e.get('loc'):
                click.echo(f'Configuration error at {location[0]}: {_e.get("msg")}')
            else:
                click.echo(f'Configuration error: {_e.get("msg")}')
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


def gojeeraCLI():
    cli()


if __name__ == '__main__':
    gojeeraCLI()
