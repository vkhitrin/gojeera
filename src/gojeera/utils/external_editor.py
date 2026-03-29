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


def edit_text_in_external_editor(text: str, *, suffix: str = '.txt') -> str:
    """Open text in the user's external editor and return the edited result."""

    editor = os.environ.get('EDITOR') or os.environ.get('VISUAL')
    if not editor:
        raise ExternalEditorError('Set $EDITOR to use external editing.')

    try:
        with TemporaryDirectory(prefix='gojeera-') as temp_dir:
            temp_path = Path(temp_dir) / f'edit{suffix}'
            temp_path.write_text(text, encoding='utf-8')

            result = subprocess.run(
                [*shlex.split(editor), str(temp_path)],
                check=False,
                env=_build_editor_env(),
            )
            if result.returncode != 0:
                raise ExternalEditorError(
                    f'External editor exited with status {result.returncode}.'
                )

            return temp_path.read_text(encoding='utf-8')
    except FileNotFoundError as error:
        raise ExternalEditorError(f'Failed to launch external editor: {error}') from error
