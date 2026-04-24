import logging
from pathlib import Path

from textual.theme import Theme
import yaml

from gojeera.constants import LOGGER_NAME
from gojeera.logging_utils import build_log_extra

logger = logging.getLogger(LOGGER_NAME)


def create_theme_from_config(config: dict) -> Theme:
    """Create a Textual Theme object from a configuration dictionary.

    Args:
        config: A theme configuration dictionary with at minimum 'name' and 'primary' keys.

    Returns:
        A Theme object ready to be registered with the app.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    if 'name' not in config:
        raise ValueError("Theme configuration must include 'name' field")
    if 'primary' not in config:
        raise ValueError(f"Theme '{config['name']}' must include 'primary' color")

    kwargs = {
        'name': config['name'],
        'primary': config['primary'],
        'dark': config.get('dark', True),
    }

    optional_colors = [
        'secondary',
        'accent',
        'foreground',
        'background',
        'surface',
        'panel',
        'success',
        'warning',
        'error',
        'boost',
    ]
    for color in optional_colors:
        if color in config:
            kwargs[color] = config[color]

    if 'luminosity_spread' in config:
        kwargs['luminosity_spread'] = config['luminosity_spread']
    if 'text_alpha' in config:
        kwargs['text_alpha'] = config['text_alpha']

    if 'variables' in config:
        kwargs['variables'] = config['variables']

    return Theme(**kwargs)


def create_themes_from_config(theme_configs: list[dict] | None) -> list[Theme]:
    """Create Textual Theme objects from configuration dictionaries.

    Args:
        theme_configs: A list of theme configuration dictionaries from the config file.

    Returns:
        A list of Theme objects ready to be registered with the app.

    Raises:
        ValueError: If a theme configuration is invalid.
    """
    if not theme_configs:
        return []

    themes = []
    for config in theme_configs:
        try:
            themes.append(create_theme_from_config(config))
        except Exception as e:
            raise ValueError(
                f"Invalid theme configuration for '{config.get('name', 'unknown')}': {str(e)}"
            ) from e

    return themes


def load_themes_from_directory(themes_directory: Path) -> list[Theme]:
    """Load custom themes from YAML files in the themes directory.

    Args:
        themes_directory: Path to the directory containing theme YAML files.

    Returns:
        A list of Theme objects loaded from the directory.
    """
    themes = []

    if not themes_directory.exists():
        logger.debug(
            'Themes directory does not exist',
            extra=build_log_extra({'themes_directory': str(themes_directory)}),
        )
        return themes

    yaml_files = list(themes_directory.glob('*.yaml')) + list(themes_directory.glob('*.yml'))

    for yaml_file in yaml_files:
        try:
            with open(yaml_file, encoding='utf-8') as f:
                theme_config = yaml.safe_load(f)

            if not theme_config:
                logger.warning(
                    'Empty theme file',
                    extra=build_log_extra({'theme_file': yaml_file.name}),
                )
                continue

            theme = create_theme_from_config(theme_config)
            themes.append(theme)
            logger.debug(
                'Loaded theme from file',
                extra=build_log_extra({'theme_name': theme.name, 'theme_file': yaml_file.name}),
            )

        except yaml.YAMLError as e:
            logger.error(
                'Failed to parse theme file',
                extra=build_log_extra({'theme_file': yaml_file.name, 'error': str(e)}),
            )
        except ValueError as e:
            logger.error(
                'Invalid theme definition',
                extra=build_log_extra({'theme_file': yaml_file.name, 'error': str(e)}),
            )
        except Exception as e:
            logger.warning(
                'Unexpected error loading theme',
                extra=build_log_extra({'theme_file': yaml_file.name, 'error': str(e)}),
            )

    return themes
