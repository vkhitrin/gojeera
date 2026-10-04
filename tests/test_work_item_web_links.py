from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from gojeera.app import JiraApp
from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.web_link_screen import RemoteLinkScreen
from gojeera.components.work_item.work_item_web_links import WorkItemRemoteLinksWidget

from .test_helpers import (
    accept_confirmation,
    assert_snapshot_matches,
    focus_work_item_tab,
    wait_until,
)


async def select_work_item_and_highlight_web_link(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=4)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    if table := web_links_widget.table:
        table.focus()
        await pilot.pause()


async def create_web_link_and_verify(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=4)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    initial_count = web_links_widget.displayed_count

    web_links_widget.focus()
    await pilot.pause()

    await web_links_widget.action_add_remote_link()
    await wait_until(lambda: isinstance(pilot.app.screen, RemoteLinkScreen), timeout=3.0)

    screen = pilot.app.screen
    assert isinstance(screen, RemoteLinkScreen)

    url_field = screen.link_url
    url_field.focus()
    await wait_until(lambda: url_field.has_focus, timeout=3.0)

    await pilot.press(*'https://docs.example.com/api')
    await wait_until(lambda: url_field.value == 'https://docs.example.com/api', timeout=3.0)

    title_field = screen.link_name
    title_field.focus()
    await wait_until(lambda: title_field.has_focus, timeout=3.0)

    await pilot.press(*'API Documentation')
    await wait_until(lambda: title_field.value == 'API Documentation', timeout=3.0)

    await pilot.press('tab')
    await wait_until(lambda: not screen.save_button.disabled, timeout=3.0)

    assert not screen.save_button.disabled, 'Save button should be enabled'

    screen.save_button.press()

    await wait_until(lambda: not isinstance(pilot.app.screen, RemoteLinkScreen), timeout=3.0)

    assert not isinstance(pilot.app.screen, RemoteLinkScreen)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    await wait_until(lambda: web_links_widget.displayed_count == initial_count + 1, timeout=3.0)
    new_count = web_links_widget.displayed_count

    assert new_count == initial_count + 1, (
        f'Expected {initial_count + 1} web links, got {new_count}'
    )

    assert len(web_links_widget.remote_links or []) == new_count, (
        f'Expected {new_count} remote links in widget state, got {len(web_links_widget.remote_links or [])}'
    )


async def delete_web_link_and_verify(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=4)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    initial_count = web_links_widget.displayed_count

    if table := web_links_widget.table:
        table.select_index(0, scroll_into_view=True, focus=True)
        await pilot.pause()

        await web_links_widget.action_delete_remote_link()
        await wait_until(lambda: isinstance(pilot.app.screen, ConfirmationScreen), timeout=3.0)
        await accept_confirmation(pilot)
        assert not isinstance(pilot.app.screen, ConfirmationScreen)

        web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
        await wait_until(
            lambda: web_links_widget.displayed_count == initial_count - 1,
            timeout=3.0,
        )
        new_count = web_links_widget.displayed_count

        assert new_count == initial_count - 1, (
            f'Expected {initial_count - 1} web links, got {new_count}'
        )

        assert web_links_widget.displayed_count == new_count


HIGHLIGHT = select_work_item_and_highlight_web_link
CREATE = create_web_link_and_verify
DELETE = delete_web_link_and_verify


def test_remote_links_load_only_when_requested(monkeypatch) -> None:
    monkeypatch.setattr(WorkItemRemoteLinksWidget, 'watch_remote_links', lambda self, links: None)
    monkeypatch.setattr(WorkItemRemoteLinksWidget, 'watch_is_loading', lambda self, loading: None)
    widget = WorkItemRemoteLinksWidget()
    worker = SimpleNamespace(is_finished=False)

    def run_worker(coroutine, *, exclusive: bool):
        coroutine.close()
        return worker

    run = Mock(side_effect=run_worker)
    monkeypatch.setattr(widget, 'run_worker', run)
    monkeypatch.setattr(widget, 'show_loading', Mock())
    monkeypatch.setattr(widget, 'hide_loading', Mock())

    widget.work_item_key = 'ENG-1'

    run.assert_not_called()
    widget.load_if_needed()
    widget.load_if_needed()

    run.assert_called_once()
    assert run.call_args.kwargs == {'exclusive': True}


async def test_created_remote_link_is_not_replaced_by_eager_refetch(monkeypatch) -> None:
    monkeypatch.setattr(WorkItemRemoteLinksWidget, 'watch_remote_links', lambda self, links: None)
    monkeypatch.setattr(WorkItemRemoteLinksWidget, 'watch_is_loading', lambda self, loading: None)
    widget = WorkItemRemoteLinksWidget()
    create_remote_link = AsyncMock(return_value=SimpleNamespace(success=True))
    fake_app = SimpleNamespace(
        api=SimpleNamespace(create_work_item_remote_link=create_remote_link),
    )
    monkeypatch.setattr(
        WorkItemRemoteLinksWidget,
        'app',
        property(lambda self: fake_app),
    )
    monkeypatch.setattr(widget, 'notify', Mock())
    run_worker = Mock()
    monkeypatch.setattr(widget, 'run_worker', run_worker)
    widget.work_item_key = 'ENG-1'
    widget._loaded_work_item_key = 'ENG-1'

    await widget.create_link(
        {
            'link_url': 'https://docs.example.com/api',
            'link_title': 'API documentation',
        }
    )
    widget.load_if_needed()

    create_remote_link.assert_awaited_once()
    assert [link.url for link in widget.remote_links or []] == ['https://docs.example.com/api']
    run_worker.assert_not_called()


class TestWorkItemWebLinks:
    def test_work_item_web_links_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, HIGHLIGHT)

    def test_create_web_link(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_web_link_creation,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=CREATE)

    def test_delete_web_link(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_web_link_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=DELETE)
