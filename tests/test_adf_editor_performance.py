from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from gojeera.utils.data.fields import FieldMode
from gojeera.widgets.markdown import extended_adf_markdown_textarea as adf_editor
from gojeera.widgets.markdown.extended_adf_markdown_textarea import (
    ADF_WARNING_LOOKUP_DELAY_SECONDS,
    ExtendedADFMarkdownTextArea,
)


def test_adf_warning_analysis_is_scheduled_after_typing(monkeypatch) -> None:
    widget = ExtendedADFMarkdownTextArea(mode=FieldMode.CREATE)
    previous_timer = cast(Any, SimpleNamespace())
    previous_worker = cast(Any, SimpleNamespace())
    next_timer = cast(Any, SimpleNamespace())
    cancel = Mock(return_value=(None, None))
    schedule = Mock(return_value=next_timer)
    monkeypatch.setattr(adf_editor, 'cancel_delayed_lookup', cancel)
    monkeypatch.setattr(adf_editor, 'schedule_delayed_lookup', schedule)
    monkeypatch.setattr(widget, '_update_warning_display', Mock())
    monkeypatch.setattr(widget, '_update_tab_label', Mock())
    widget._warning_timer = previous_timer
    widget._warning_worker = previous_worker

    widget._schedule_adf_warning_check('new description')

    cancel.assert_called_once_with(previous_timer, previous_worker)
    assert schedule.call_args is not None
    assert schedule.call_args.kwargs['delay'] == ADF_WARNING_LOOKUP_DELAY_SECONDS
    assert schedule.call_args.kwargs['worker_attr'] == '_warning_worker'
    assert widget._warning_timer is next_timer


async def test_adf_warning_analysis_runs_off_event_loop_and_ignores_stale_text(
    monkeypatch,
) -> None:
    widget = ExtendedADFMarkdownTextArea(mode=FieldMode.CREATE)
    update_warning_display = Mock()
    update_tab_label = Mock()
    monkeypatch.setattr(widget, '_update_warning_display', update_warning_display)
    monkeypatch.setattr(widget, '_update_tab_label', update_tab_label)
    to_thread = AsyncMock(return_value=['Unsupported node'])
    monkeypatch.setattr(adf_editor.asyncio, 'to_thread', to_thread)

    widget._text = 'current'
    await widget._check_adf_warnings_async('current')

    assert to_thread.await_args is not None
    assert to_thread.await_args.args == (adf_editor._adf_warnings_for_text, 'current')
    assert widget._adf_warnings == ['Unsupported node']
    update_warning_display.assert_called_once()
    update_tab_label.assert_called_once()

    update_warning_display.reset_mock()
    update_tab_label.reset_mock()
    widget._text = 'newer'
    await widget._check_adf_warnings_async('stale')

    update_warning_display.assert_not_called()
    update_tab_label.assert_not_called()
