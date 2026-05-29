from pathlib import Path
from typing import Any

import yaml
from xdg_base_dirs import xdg_config_home, xdg_state_home

LOG_FILE_FILE_NAME = 'gojeera.log'


def _gojeera_directory(root: Path) -> Path:
    """Returns the path to a directory associated with the application.

    Args:
        root: the root directory path where the application directory exists or is created.

    Returns:
        A `Path` expression of the application directory.
    """
    directory = root / 'gojeera'
    directory.mkdir(exist_ok=True, parents=True)
    return directory


def get_config_directory() -> Path:
    """Retrieves the (default) directory where the configuration file of the application will be stored.

    Returns:
        A `Path` of the config directory.
    """
    return _gojeera_directory(xdg_config_home())


def get_logs_directory() -> Path:
    """Retrieves the (default) directory where the logs of the application will be stored.

    Returns:
        A `Path` of the logs directory.
    """
    return _gojeera_directory(xdg_state_home())


def get_config_file() -> Path:
    """Retrieves the (default) path of the config file.

    Returns:
        A `Path` of the config file.
    """
    return get_config_directory() / 'config.yaml'


def get_log_file() -> Path:
    """Retrieves the (default) path of the logs file.

    Returns:
        A `Path` of the logs file.
    """
    return get_logs_directory() / LOG_FILE_FILE_NAME


def get_themes_directory() -> Path:
    """Retrieves the directory where custom theme files are stored.

    Returns:
        A `Path` of the themes directory.
    """
    themes_dir = get_config_directory() / 'themes'
    themes_dir.mkdir(exist_ok=True, parents=True)
    return themes_dir


def get_templates_directory() -> Path:
    """Retrieves the directory where work item template files are stored.

    Returns:
        A `Path` of the templates directory.
    """
    templates_dir = get_config_directory() / 'templates'
    templates_dir.mkdir(exist_ok=True, parents=True)
    return templates_dir


def list_yaml_files(directory: Path) -> list[Path]:
    """Return YAML files from a directory in deterministic order."""
    if not directory.exists():
        return []
    return sorted([*directory.glob('*.yaml'), *directory.glob('*.yml')])


def load_yaml_file(path: Path) -> Any:
    """Load a YAML file with UTF-8 encoding."""
    with path.open(encoding='utf-8') as yaml_file:
        return yaml.safe_load(yaml_file)


def load_yaml_mapping(path: Path, *, default_empty: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load a YAML file that must contain a mapping."""
    data = load_yaml_file(path)
    if data is None and default_empty is not None:
        return default_empty
    if not isinstance(data, dict):
        raise TypeError('YAML file must contain a mapping')
    return data
