from unittest.mock import AsyncMock, Mock

import pytest
from textual.widgets import TabPane

from gojeera.components.screens.for_you_screen import ForYouScreen
from gojeera.internal.jira.for_you import ForYouResult, ForYouService

from .test_helpers import wait_until


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'result,severity,message',
    [
        (ForYouResult(), None, None),
        (ForYouResult(error='Forbidden'), 'error', 'Forbidden'),
        (ForYouResult(error='Current user is not loaded.'), 'error', 'Current user is not loaded'),
        (ForYouResult(limited=True), None, None),
        (ForYouResult(failed_comment_items=1), 'warning', 'Comments unavailable for 1'),
        (
            ForYouResult(limited=True, failed_comment_items=1),
            'warning',
            'Comments unavailable for 1 item(s). Refresh to retry.',
        ),
    ],
)
async def test_section_feedback_reports_failures_but_not_scan_limits(
    for_you_app, monkeypatch, result, severity, message
):
    async def load(_service, section, _account_id):
        return result if section == 'mentions' else ForYouResult()

    monkeypatch.setattr(ForYouService, 'load', load)
    async with for_you_app.run_test(size=(120, 40)):
        notify = Mock()
        monkeypatch.setattr(for_you_app, 'notify', notify)
        await for_you_app.action_show_for_you()
        screen = for_you_app.screen
        await wait_until(lambda: all(not pane.loading for pane in screen.query(TabPane)))
        if severity is None:
            notify.assert_not_called()
        else:
            notify.assert_called_once()
            assert notify.call_args.kwargs['severity'] == severity
            assert notify.call_args.kwargs['title'] == 'For You — Mentions'
            notification = notify.call_args.args[0]
            assert message in notification
            assert 'limit' not in notification
            assert 'scan incomplete' not in notification
        assert isinstance(screen, ForYouScreen)


@pytest.mark.asyncio
async def test_comment_scan_cap_does_not_notify(for_you_app, monkeypatch):
    for_you_app.config.for_you.comments_per_item = 1
    async with for_you_app.run_test(size=(120, 40)):
        service = ForYouService(for_you_app.api, for_you_app.config.for_you)
        result = await service.load('mentions', for_you_app.atlassian_context.user_info.account_id)
        assert 'Comment scan incomplete' in result.note
        assert result.failed_comment_items == 0
        notify = Mock()
        monkeypatch.setattr(for_you_app, 'notify', notify)
        await for_you_app.action_show_for_you()
        await wait_until(
            lambda: all(not pane.loading for pane in for_you_app.screen.query(TabPane))
        )
        notify.assert_not_called()


@pytest.mark.asyncio
async def test_unexpected_service_error_has_structured_feedback(for_you_app, monkeypatch):
    monkeypatch.setattr(
        for_you_app.api, 'search_work_items', AsyncMock(side_effect=RuntimeError('Network failed'))
    )
    result = await ForYouService(for_you_app.api, for_you_app.config.for_you).load('due', None)
    assert result.error == 'Network failed'
    assert not result.entries


@pytest.mark.asyncio
@pytest.mark.parametrize('section', ['due', 'updated', 'mentions'])
async def test_display_caps_preserve_rows_and_report_limited_results(for_you_app, section):
    for_you_app.config.for_you.items_per_section = 1
    async with for_you_app.run_test(size=(120, 40)):
        service = ForYouService(for_you_app.api, for_you_app.config.for_you)
        result = await service.load(section, for_you_app.atlassian_context.user_info.account_id)
        assert len(result.entries) == 1
        assert result.limited
        assert result.error is None
        assert result.failed_comment_items == 0
