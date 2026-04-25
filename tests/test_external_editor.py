import pytest

from gojeera.utils.system.external_editor import ExternalEditorError, edit_text_in_external_editor


def test_edit_text_in_external_editor_rejects_invalid_editor_command(monkeypatch):
    monkeypatch.setenv('EDITOR', '"')

    with pytest.raises(ExternalEditorError, match='Invalid external editor command'):
        edit_text_in_external_editor('hello')
