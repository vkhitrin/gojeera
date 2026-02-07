import asyncio

from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.new_related_work_item_screen import AddWorkItemRelationshipScreen
from gojeera.components.work_item_related_work_items import RelatedWorkItemsWidget


async def open_add_related_work_item_screen(pilot):
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
    related_widget.focus()
    await asyncio.sleep(0.2)

    await related_widget.action_link_work_item()

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemRelationshipScreen), (
        f'Expected AddWorkItemRelationshipScreen, got {type(screen)}'
    )

    await pilot.app.workers.wait_for_complete()

    await asyncio.sleep(0.8)

    assert screen.save_button.disabled, 'Expected Save button to be disabled initially'


async def fill_required_fields_and_verify_save_enabled(pilot):
    await open_add_related_work_item_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemRelationshipScreen), (
        f'Expected AddWorkItemRelationshipScreen, got {type(screen)}'
    )

    assert screen.save_button.disabled, 'Expected Save button to be disabled before filling fields'

    work_item_key_field = screen.linked_work_item_key
    work_item_key_field.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'EXAMPLE-100')
    await asyncio.sleep(0.3)

    link_type_selector = screen.relationship_type

    await asyncio.sleep(0.3)

    link_type_selector.value = '10000:outward'
    await asyncio.sleep(0.3)

    assert not screen.save_button.disabled, (
        f'Expected Save button to be enabled after filling fields. '
        f'Link type: "{screen.relationship_type.selection}", '
        f'Work item key: "{screen.linked_work_item_key.value}"'
    )


class TestNewRelatedWorkItemScreen:
    def test_new_related_work_item_screen_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app, terminal_size=(120, 40), run_before=open_add_related_work_item_screen
        )

    def test_new_related_work_item_screen_with_filled_fields(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=fill_required_fields_and_verify_save_enabled,
        )
