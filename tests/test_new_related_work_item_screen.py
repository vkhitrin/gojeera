import asyncio

import pytest

from gojeera.components.screens.new_related_work_item_screen import AddWorkItemRelationshipScreen
from gojeera.components.work_item.work_item_related_work_items import RelatedWorkItemsWidget

from .test_helpers import focus_work_item_tab, with_snapshot_assertion


async def open_add_related_work_item_screen(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=3)

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

    await pilot.press(*'ENG-8')
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


async def fill_browse_url_and_verify_save_enabled(pilot):
    await open_add_related_work_item_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemRelationshipScreen), (
        f'Expected AddWorkItemRelationshipScreen, got {type(screen)}'
    )

    screen.linked_work_item_key.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'https://example.atlassian.acme.net/browse/ENG-8')
    await asyncio.sleep(0.3)

    screen.relationship_type.value = '10000:outward'
    await asyncio.sleep(0.3)

    assert not screen.save_button.disabled, 'Save button should be enabled for a valid browse URL'


class TestNewRelatedWorkItemScreen:
    @with_snapshot_assertion(open_add_related_work_item_screen, terminal_size=(120, 40))
    def test_new_related_work_item_screen_initial_state(self): ...

    @with_snapshot_assertion(fill_required_fields_and_verify_save_enabled, terminal_size=(120, 40))
    def test_new_related_work_item_screen_with_filled_fields(self): ...

    @pytest.mark.asyncio
    async def test_new_related_work_item_screen_accepts_browse_url(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        from gojeera.app import JiraApp

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async with app.run_test() as pilot:
            await fill_browse_url_and_verify_save_enabled(pilot)
