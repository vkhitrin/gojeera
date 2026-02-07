import asyncio

from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.new_related_work_item_screen import AddWorkItemRelationshipScreen
from gojeera.components.work_item_related_work_items import RelatedWorkItemsWidget


async def create_related_work_item_and_verify(pilot):
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.5)

    related_widget = pilot.app.screen.query_one(RelatedWorkItemsWidget)
    initial_count = related_widget.displayed_count

    related_widget.focus()
    await asyncio.sleep(0.2)

    await related_widget.action_link_work_item()
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.8)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemRelationshipScreen)

    work_item_key_field = screen.linked_work_item_key
    work_item_key_field.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'EXAMPLE-100')
    await asyncio.sleep(0.3)

    link_type_selector = screen.relationship_type
    link_type_selector.value = '10000:outward'
    await asyncio.sleep(0.3)

    assert not screen.save_button.disabled, 'Save button should be enabled'

    screen.save_button.press()

    await asyncio.sleep(1.5)

    assert not isinstance(pilot.app.screen, AddWorkItemRelationshipScreen)

    await asyncio.sleep(1.0)

    related_widget = pilot.app.screen.query_one(RelatedWorkItemsWidget)
    new_count = related_widget.displayed_count

    assert new_count == initial_count + 1, (
        f'Expected {initial_count + 1} related work items, got {new_count}'
    )

    assert related_widget.work_items is not None
    new_related_item = related_widget.work_items[-1]
    assert new_related_item.key == 'EXAMPLE-100', (
        f'Expected key "EXAMPLE-100", got "{new_related_item.key}"'
    )
    assert new_related_item.link_type == 'blocks', (
        f'Expected link type "blocks", got "{new_related_item.link_type}"'
    )


async def delete_issue_link_and_verify(pilot):
    """Delete an issue link and verify it's removed from the table."""
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.5)

    related_widget = pilot.app.screen.query_one(RelatedWorkItemsWidget)

    await asyncio.sleep(0.5)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.3)

    assert related_widget.displayed_count > 0, (
        f'Expected related work items, got {related_widget.displayed_count}'
    )

    table = related_widget.data_table
    table.focus()
    await asyncio.sleep(0.2)

    await related_widget.action_unlink_work_item()
    await asyncio.sleep(0.3)

    screen = pilot.app.screen
    assert isinstance(screen, ConfirmationScreen), (
        f'Expected ConfirmationScreen, got {type(screen)}'
    )

    await pilot.press('enter')

    await asyncio.sleep(1.0)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)


class TestRelatedWorkItem:
    def test_create_related_work_item_and_verify_in_table(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_related_work_item_link,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app, terminal_size=(120, 40), run_before=create_related_work_item_and_verify
        )

    def test_delete_issue_link_and_verify_in_table(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_issue_link_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=delete_issue_link_and_verify)
