import asyncio

from gojeera.components.screens.web_link_screen import RemoteLinkScreen
from gojeera.components.work_item.work_item_web_links import WorkItemRemoteLinksWidget

from .test_helpers import focus_work_item_tab, with_snapshot_assertion


async def open_add_web_link_screen(pilot):
    """Navigate to work item and open Add Web Link screen."""
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=4)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    web_links_widget.focus()
    await asyncio.sleep(0.2)

    await web_links_widget.action_add_remote_link()

    screen = pilot.app.screen
    assert isinstance(screen, RemoteLinkScreen), f'Expected RemoteLinkScreen, got {type(screen)}'

    await asyncio.sleep(0.5)

    assert screen.save_button.disabled, 'Expected Save button to be disabled initially'

    assert not screen.is_edit_mode, 'Expected screen to be in add mode'


async def fill_web_link_fields_and_verify_save_enabled(pilot):
    """Fill required fields and verify Save button becomes enabled."""
    await open_add_web_link_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, RemoteLinkScreen), f'Expected RemoteLinkScreen, got {type(screen)}'

    assert screen.save_button.disabled, 'Expected Save button to be disabled before filling fields'

    url_field = screen.link_url
    url_field.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'https://example.com/docs')
    await asyncio.sleep(0.2)

    title_field = screen.link_name
    title_field.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'Example Documentation')
    await asyncio.sleep(0.2)

    await pilot.press('tab')
    await asyncio.sleep(0.3)

    assert not screen.save_button.disabled, (
        f'Expected Save button to be enabled after filling fields. '
        f'URL: "{screen.link_url.value}", '
        f'Title: "{screen.link_name.value}"'
    )


async def open_edit_web_link_screen(pilot):
    """Navigate to work item, select a web link, and open Edit Web Link screen."""
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=4)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    if table := web_links_widget.record_list:
        table.select_index(0, scroll_into_view=True, focus=True)
        await asyncio.sleep(0.2)

        await web_links_widget.action_edit_remote_link()
        await asyncio.sleep(0.5)

        screen = pilot.app.screen
        assert isinstance(screen, RemoteLinkScreen), (
            f'Expected RemoteLinkScreen, got {type(screen)}'
        )

        await asyncio.sleep(0.5)

        assert screen.is_edit_mode, 'Expected screen to be in edit mode'

        assert not screen.save_button.disabled, (
            'Expected Save button to be enabled in edit mode with existing data'
        )

        assert screen.link_url.value, 'Expected URL field to be pre-filled'
        assert screen.link_name.value, 'Expected Title field to be pre-filled'


class TestWebLinkScreen:
    """Snapshot tests to verify RemoteLinkScreen appearance in add and edit modes."""

    @with_snapshot_assertion(open_add_web_link_screen)
    def test_web_link_screen_add_mode_initial_state(self):
        """Snapshot: Add Web Link screen with empty fields.

        Verifies:
        - Title shows "Add Remote Link - Work Item: ENG-1"
        - URL field empty
        - Title field empty with placeholder
        - Save button disabled (no fields filled yet)
        """

    @with_snapshot_assertion(fill_web_link_fields_and_verify_save_enabled)
    def test_web_link_screen_add_mode_with_filled_fields(self):
        """Snapshot: Add Web Link screen with all required fields filled.

        Verifies:
        - URL entered: https://example.com/docs
        - Title entered: Example Documentation
        - Save button becomes enabled after filling both fields
        """

    @with_snapshot_assertion(open_edit_web_link_screen)
    def test_web_link_screen_edit_mode_with_existing_link(self):
        """Snapshot: Edit Web Link screen with existing link data pre-filled.

        Verifies:
        - Title shows "Edit Remote Link - Work Item: ENG-1"
        - URL field pre-filled from existing link
        - Title field pre-filled from existing link
        - Save button enabled (fields already have valid data)
        """
