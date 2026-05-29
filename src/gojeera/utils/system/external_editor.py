import os
from pathlib import Path
import shlex
import subprocess
from tempfile import TemporaryDirectory


class ExternalEditorError(RuntimeError):
    """Raised when launching or using the external editor fails."""


def _build_editor_env() -> dict[str, str]:
    """Return a sanitized environment for launching the external editor."""

    return {key: value for key, value in os.environ.items() if not key.startswith('GOJEERA_')}


def _editor_command() -> list[str]:
    editor = os.environ.get('EDITOR') or os.environ.get('VISUAL')
    if not editor:
        raise ExternalEditorError('Set $EDITOR to use external editing.')

    try:
        editor_command = shlex.split(editor)
    except ValueError as error:
        raise ExternalEditorError(f'Invalid external editor command: {error}') from error

    if not editor_command:
        raise ExternalEditorError('Set $EDITOR to a valid executable to use external editing.')
    return editor_command


def _run_editor(path: Path) -> None:
    try:
        result = subprocess.run(
            [*_editor_command(), str(path)],
            check=False,
            env=_build_editor_env(),
        )
    except FileNotFoundError as error:
        raise ExternalEditorError(f'Failed to launch external editor: {error}') from error

    if result.returncode != 0:
        raise ExternalEditorError(f'External editor exited with status {result.returncode}.')


def edit_text_in_external_editor(text: str, *, suffix: str = '.txt') -> str:
    """Open text in the user's external editor and return the edited result."""

    with TemporaryDirectory(prefix='gojeera-') as temp_dir:
        temp_path = Path(temp_dir) / f'edit{suffix}'
        temp_path.write_text(text, encoding='utf-8')
        _run_editor(temp_path)
        return temp_path.read_text(encoding='utf-8')
