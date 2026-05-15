from dataclasses import fields as dataclass_fields
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import TypeAdapter
from textual.theme import Theme
import yaml

from gojeera.utils.system.logging_utils import build_log_extra

logger = logging.getLogger('gojeera')
THEME_ADAPTER = TypeAdapter(Theme)
THEME_FIELD_NAMES = {field.name for field in dataclass_fields(Theme)}


def find_unexpected_theme_field(config: Mapping[str, Any]) -> str | None:
    for key in config:
        if key not in THEME_FIELD_NAMES:
            return key
    return None


def create_theme_from_config(config: dict) -> Theme:
    """Create a Textual Theme object from a configuration dictionary.

    Args:
        config: A theme configuration dictionary with at minimum 'name' and 'primary' keys.

    Returns:
        A Theme object ready to be registered with the app.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    if unexpected_field := find_unexpected_theme_field(config):
        raise ValueError(f"Theme configuration contains unexpected field '{unexpected_field}'")
    try:
        return THEME_ADAPTER.validate_python(config)
    except Exception as exc:
        if 'name' not in config:
            raise ValueError("Theme configuration must include 'name' field") from exc
        if 'primary' not in config:
            raise ValueError(f"Theme '{config['name']}' must include 'primary' color") from exc
        raise


def create_themes_from_config(
    theme_configs: Sequence[Theme] | Sequence[dict[str, Any]] | None,
) -> list[Theme]:
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
            if isinstance(config, Theme):
                themes.append(config)
            else:
                themes.append(create_theme_from_config(config))
        except Exception as e:
            theme_name = config.name if isinstance(config, Theme) else config.get('name', 'unknown')
            raise ValueError(f"Invalid theme configuration for '{theme_name}': {str(e)}") from e

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

        except yaml.YAMLError as e:
            raise ValueError(f'Invalid theme file "{yaml_file.name}": failed to parse YAML') from e
        except ValueError as e:
            raise ValueError(f'Invalid theme file "{yaml_file.name}": {str(e)}') from e
        except Exception as e:
            raise ValueError(f'Invalid theme file "{yaml_file.name}": {str(e)}') from e

    return themes
