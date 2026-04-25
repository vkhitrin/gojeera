import asyncio

from gojeera.components.work_item.work_item_related_work_items import RelatedWorkItemsWidget

from .test_helpers import (
    assert_confirmation_screen,
    create_related_work_item_link,
    focus_work_item_tab,
    prepare_related_work_items_widget,
    with_snapshot_assertion_fixture,
)


async def create_related_work_item_and_verify(pilot):
    related_widget = await prepare_related_work_items_widget(pilot)
    initial_count = related_widget.displayed_count

    await create_related_work_item_link(pilot, related_widget=related_widget)

    related_widget = pilot.app.screen.query_one(RelatedWorkItemsWidget)
    new_count = related_widget.displayed_count

    assert new_count == initial_count + 1, (
        f'Expected {initial_count + 1} related work items, got {new_count}'
    )

    assert related_widget.work_items is not None
    new_related_item = related_widget.work_items[-1]
    assert new_related_item.key == 'ENG-8', f'Expected key "ENG-8", got "{new_related_item.key}"'
    assert new_related_item.link_type == 'blocks', (
        f'Expected link type "blocks", got "{new_related_item.link_type}"'
    )


async def delete_issue_link_and_verify(pilot):
    """Delete an issue link and verify it's removed from the table."""
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=3)

    related_widget = pilot.app.screen.query_one(RelatedWorkItemsWidget)

    await asyncio.sleep(0.5)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.3)

    assert related_widget.displayed_count > 0, (
        f'Expected related work items, got {related_widget.displayed_count}'
    )

    table = related_widget.record_list
    table.select_index(0, scroll_into_view=True, focus=True)
    await asyncio.sleep(0.2)

    await related_widget.action_unlink_work_item()
    await asyncio.sleep(0.3)

    assert_confirmation_screen(pilot.app.screen)

    await pilot.press('enter')

    await asyncio.sleep(1.0)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)


class TestRelatedWorkItem:
    @with_snapshot_assertion_fixture(
        create_related_work_item_and_verify,
        fixture_name='mock_jira_api_with_related_work_item_link',
    )
    def test_create_related_work_item(self): ...

    @with_snapshot_assertion_fixture(
        delete_issue_link_and_verify,
        fixture_name='mock_jira_api_with_issue_link_deletion',
    )
    def test_delete_issue_link(self): ...
