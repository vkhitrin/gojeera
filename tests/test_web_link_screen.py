import asyncio

from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.web_link_screen import RemoteLinkScreen
from gojeera.components.work_item_web_links import WorkItemRemoteLinksWidget


async def open_add_web_link_screen(pilot):
    """Navigate to work item and open Add Web Link screen."""
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
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.5)

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
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.5)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    if table := web_links_widget.data_table:
        table.focus()
        await asyncio.sleep(0.2)

        await pilot.press('e')
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

    def test_web_link_screen_add_mode_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        """Snapshot: Add Web Link screen with empty fields.

        Verifies:
        - Title shows "Add Remote Link - Work Item: EXAMPLE-19539"
        - URL field empty
        - Title field empty with placeholder
        - Save button disabled (no fields filled yet)
        """
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_add_web_link_screen)

    def test_web_link_screen_add_mode_with_filled_fields(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        """Snapshot: Add Web Link screen with all required fields filled.

        Verifies:
        - URL entered: https://example.com/docs
        - Title entered: Example Documentation
        - Save button becomes enabled after filling both fields
        """
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=fill_web_link_fields_and_verify_save_enabled,
        )

    def test_web_link_screen_edit_mode_with_existing_link(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        """Snapshot: Edit Web Link screen with existing link data pre-filled.

        Verifies:
        - Title shows "Edit Remote Link - Work Item: EXAMPLE-19539"
        - URL field pre-filled from existing link
        - Title field pre-filled from existing link
        - Save button enabled (fields already have valid data)
        """
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_edit_web_link_screen,
        )
