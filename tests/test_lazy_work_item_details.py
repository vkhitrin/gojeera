from types import MethodType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from gojeera.app import DEFERRED_COUNT_BADGE, DEFERRED_COUNT_TAB_IDS, WorkspaceMixin
from gojeera.components.work_item.work_item_information import WorkItemInformation
from gojeera.internal.jira.controller import INITIAL_WORK_ITEM_FIELDS, APIControllerResponse


def _badge_test_app(**state: Any) -> tuple[Any, Mock]:
    set_tab_badge = Mock()
    app = cast(
        Any,
        SimpleNamespace(
            _pending_detail_count_tabs=set(),
            tabs=SimpleNamespace(set_tab_badge=set_tab_badge),
            **state,
        ),
    )
    app._update_information_tab_badge = MethodType(
        WorkspaceMixin._update_information_tab_badge,
        app,
    )
    return app, set_tab_badge


def test_deferred_tab_counts_show_pending_indicator_until_loaded() -> None:
    app, set_tab_badge = _badge_test_app()

    WorkspaceMixin._mark_detail_tab_count_pending(app)

    assert app._pending_detail_count_tabs == set(DEFERRED_COUNT_TAB_IDS)
    assert {call.args for call in set_tab_badge.call_args_list} == {
        (tab_id, DEFERRED_COUNT_BADGE) for tab_id in DEFERRED_COUNT_TAB_IDS
    }

    WorkspaceMixin._update_information_tab_badge(app, 'tab-history', 3)
    set_tab_badge.assert_called_with('tab-history', DEFERRED_COUNT_BADGE)

    WorkspaceMixin.mark_detail_tab_count_loaded(app, 'tab-history', 0)
    assert 'tab-history' not in app._pending_detail_count_tabs
    set_tab_badge.assert_called_with('tab-history', '0')

    WorkspaceMixin._update_information_tab_badge(app, 'tab-history', 3)
    set_tab_badge.assert_called_with('tab-history', 3)


def test_comment_mutation_count_survives_tab_reactivation() -> None:
    app, set_tab_badge = _badge_test_app(
        current_loaded_work_item_key='ENG-1',
        _comments_loaded_work_item_key='ENG-1',
        _comments_total=3,
    )
    app.mark_detail_tab_count_loaded = MethodType(
        WorkspaceMixin.mark_detail_tab_count_loaded,
        app,
    )

    WorkspaceMixin.adjust_loaded_comment_total(app, 'ENG-1', 1)
    WorkspaceMixin._update_comments_tab_title(app, 2)

    assert app._comments_total == 4
    set_tab_badge.assert_called_with('tab-comments', 4)


def test_comments_and_subtasks_load_only_for_the_active_tab() -> None:
    scheduled_groups: list[str] = []

    async def load_comments(work_item_key: str) -> None:
        pass

    async def load_subtasks(work_item_key: str) -> None:
        pass

    def run_worker(coroutine, *, exclusive: bool, group: str):
        coroutine.close()
        scheduled_groups.append(group)
        return SimpleNamespace(is_finished=False)

    work_item = SimpleNamespace(key='ENG-1', comments=[], subtasks=[])
    load_comment_permission = Mock()
    app = cast(
        Any,
        SimpleNamespace(
            information_panel=SimpleNamespace(work_item=work_item),
            _is_current_loaded_work_item=lambda key: key == 'ENG-1',
            _comments_loaded_work_item_key=None,
            _subtasks_loaded_work_item_key=None,
            _work_item_details_mounted=True,
            _comments_loading_worker=None,
            _subtasks_loading_worker=None,
            work_item_comments_widget=SimpleNamespace(
                show_loading=Mock(),
                load_permission_if_needed=load_comment_permission,
            ),
            work_item_child_work_items_widget=SimpleNamespace(show_loading=Mock()),
            _load_work_item_comments=load_comments,
            _load_work_item_subtasks=load_subtasks,
            run_worker=run_worker,
        ),
    )

    WorkspaceMixin.load_work_item_detail_tab_if_needed(app, 'tab-description')
    assert scheduled_groups == []
    load_comment_permission.assert_not_called()

    WorkspaceMixin.load_work_item_detail_tab_if_needed(app, 'tab-comments')
    WorkspaceMixin.load_work_item_detail_tab_if_needed(app, 'tab-comments')
    assert scheduled_groups == ['work-item-comments']
    assert load_comment_permission.call_count == 2

    WorkspaceMixin.load_work_item_detail_tab_if_needed(app, 'tab-subtasks')
    assert scheduled_groups == ['work-item-comments', 'work-item-subtasks']


def test_detail_tab_switching_keeps_same_work_item_loads_alive(monkeypatch) -> None:
    information = WorkItemInformation()
    switcher = SimpleNamespace(current=None)
    load_detail_tab = Mock()
    history_widget = SimpleNamespace(load_if_needed=Mock(), cancel_loading=Mock())
    development_widget = SimpleNamespace(load_if_needed=Mock(), cancel_loading=Mock())
    remote_links_widget = SimpleNamespace(load_if_needed=Mock(), cancel_loading=Mock())

    monkeypatch.setattr(
        WorkItemInformation,
        'app',
        property(
            lambda _self: SimpleNamespace(load_work_item_detail_tab_if_needed=load_detail_tab)
        ),
    )
    monkeypatch.setattr(
        WorkItemInformation,
        'content_switcher',
        property(lambda _self: switcher),
    )
    monkeypatch.setattr(
        WorkItemInformation,
        'history_widget',
        property(lambda _self: history_widget),
    )
    monkeypatch.setattr(
        WorkItemInformation,
        'development_widget',
        property(lambda _self: development_widget),
    )
    monkeypatch.setattr(
        WorkItemInformation,
        'remote_links_widget',
        property(lambda _self: remote_links_widget),
    )

    information.set_active_tab('tab-history')
    information.set_active_tab('tab-description')
    information.set_active_tab('tab-development')
    information.set_active_tab('tab-links')

    history_widget.load_if_needed.assert_called_once_with()
    development_widget.load_if_needed.assert_called_once_with()
    remote_links_widget.load_if_needed.assert_called_once_with()
    history_widget.cancel_loading.assert_not_called()
    development_widget.cancel_loading.assert_not_called()
    remote_links_widget.cancel_loading.assert_not_called()
    assert switcher.current == 'pane-links'


async def test_initial_work_item_load_uses_reduced_field_list() -> None:
    get_work_item = AsyncMock(return_value=APIControllerResponse(success=False))
    ensure_work_item_details_mounted = AsyncMock()
    app = cast(
        Any,
        SimpleNamespace(
            _active_work_item_load_key=None,
            _is_current_loaded_work_item=lambda key: False,
            api=SimpleNamespace(get_work_item=get_work_item),
            is_loading=False,
            notify=Mock(),
            _ensure_work_item_details_mounted=ensure_work_item_details_mounted,
        ),
    )

    assert not await WorkspaceMixin.load_work_item(app, 'ENG-1')
    get_work_item.assert_awaited_once_with(
        work_item_id_or_key='ENG-1',
        fields=INITIAL_WORK_ITEM_FIELDS,
    )
    ensure_work_item_details_mounted.assert_awaited_once_with()
