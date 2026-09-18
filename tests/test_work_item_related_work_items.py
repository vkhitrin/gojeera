import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from gojeera.components.work_item.work_item_related_work_items import RelatedWorkItemsWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import WorkItemStatus, WorkItemType
from gojeera.internal.models.work_items import JiraWorkItem, JiraWorkItemSearchResponse

from .test_helpers import (
    accept_confirmation,
    assert_main_screen,
    assert_snapshot_matches,
    create_related_work_item_link,
    focus_work_item_tab,
    prepare_related_work_items_widget,
    with_snapshot_assertion_fixture,
)


async def open_related_widget(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=3)
    return pilot.app.screen.query_one(RelatedWorkItemsWidget)


async def test_created_related_item_survives_stale_follow_up_fetch(monkeypatch) -> None:
    monkeypatch.setattr(RelatedWorkItemsWidget, 'watch_work_items', lambda self, items: None)
    widget = RelatedWorkItemsWidget()
    linked_item = JiraWorkItem(
        id='8',
        key='ENG-8',
        summary='Linked item',
        status=WorkItemStatus(id='1', name='Open'),
        work_item_type=WorkItemType(id='10001', name='Task'),
    )
    stale_parent = JiraWorkItem(
        id='3',
        key='ENG-3',
        summary='Parent item',
        status=WorkItemStatus(id='1', name='Open'),
        work_item_type=WorkItemType(id='10001', name='Task'),
        related_work_items=[],
    )
    link_work_items = AsyncMock(return_value=APIControllerResponse())
    get_work_item = AsyncMock(
        return_value=APIControllerResponse(
            result=JiraWorkItemSearchResponse(work_items=[stale_parent])
        )
    )
    fake_app = SimpleNamespace(
        api=SimpleNamespace(
            link_work_items=link_work_items,
            get_work_item=get_work_item,
        )
    )
    monkeypatch.setattr(
        RelatedWorkItemsWidget,
        'app',
        property(lambda self: fake_app),
    )
    monkeypatch.setattr(widget, 'notify', Mock())
    widget.work_item_key = 'ENG-3'

    await widget.link_work_items(
        {
            'right_work_item_key': 'ENG-8',
            'right_work_item': linked_item,
            'link_type': 'outward',
            'link_type_id': '10000',
            'link_type_name': 'blocks',
        }
    )

    assert [(item.key, item.link_type) for item in widget.work_items or []] == [('ENG-8', 'blocks')]


async def prepare_related_widget(pilot):
    return await prepare_related_work_items_widget(pilot)


async def select_work_item_and_highlight_related_work_item(pilot):
    related_widget = await open_related_widget(pilot)
    related_widget.record_list.focus()
    await asyncio.sleep(0.3)


async def delete_issue_link_and_verify(pilot):
    related_widget = await prepare_related_widget(pilot)
    initial_count = related_widget.displayed_count
    assert initial_count > 0, f'Expected related work items, got {initial_count}'

    table = related_widget.record_list
    table.select_index(0, scroll_into_view=True, focus=True)
    await asyncio.sleep(0.2)

    await related_widget.action_unlink_work_item()
    await asyncio.sleep(0.3)
    await accept_confirmation(pilot, wait_after=0.5)
    main_screen = assert_main_screen(pilot.app)

    related_widget = main_screen.query_one(RelatedWorkItemsWidget)

    final_count = related_widget.displayed_count

    assert final_count == initial_count - 1, (
        f'Expected {initial_count - 1} related work items after deletion, got {final_count}'
    )


async def create_issue_link_and_verify(pilot):
    related_widget = await prepare_related_widget(pilot)
    initial_count = related_widget.displayed_count

    await create_related_work_item_link(pilot, related_widget=related_widget)

    main_screen = assert_main_screen(pilot.app)

    related_widget = main_screen.query_one(RelatedWorkItemsWidget)
    final_count = related_widget.displayed_count

    assert final_count == initial_count + 1, (
        f'Expected {initial_count + 1} related work items, got {final_count}'
    )

    assert related_widget.work_items is not None, 'Expected work_items to be populated'
    new_related_item = related_widget.work_items[-1]
    assert new_related_item.key == 'ENG-8', f'Expected key "ENG-8", got "{new_related_item.key}"'
    assert new_related_item.link_type == 'blocks', (
        f'Expected link type "blocks", got "{new_related_item.link_type}"'
    )


HIGHLIGHT = select_work_item_and_highlight_related_work_item
DELETE = delete_issue_link_and_verify
CREATE = create_issue_link_and_verify


class TestWorkItemRelatedWorkItems:
    def test_work_item_related_work_items_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, HIGHLIGHT)

    @with_snapshot_assertion_fixture(DELETE, fixture_name='mock_jira_api_with_issue_link_deletion')
    def test_delete_issue_link(self): ...

    @with_snapshot_assertion_fixture(
        CREATE,
        fixture_name='mock_jira_api_with_related_work_item_link',
    )
    def test_create_issue_link(self): ...
