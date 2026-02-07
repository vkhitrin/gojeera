import asyncio

from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.web_link_screen import RemoteLinkScreen
from gojeera.components.work_item_web_links import WorkItemRemoteLinksWidget


async def select_work_item_and_highlight_web_link(pilot):
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
        await asyncio.sleep(0.3)


async def create_web_link_and_verify(pilot):

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
    initial_count = web_links_widget.displayed_count

    web_links_widget.focus()
    await asyncio.sleep(0.2)

    await web_links_widget.action_add_remote_link()
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    assert isinstance(screen, RemoteLinkScreen)

    url_field = screen.link_url
    url_field.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'https://docs.example.com/api')
    await asyncio.sleep(0.2)

    title_field = screen.link_name
    title_field.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'API Documentation')
    await asyncio.sleep(0.2)

    await pilot.press('tab')
    await asyncio.sleep(0.3)

    assert not screen.save_button.disabled, 'Save button should be enabled'

    screen.save_button.press()

    await asyncio.sleep(1.5)

    assert not isinstance(pilot.app.screen, RemoteLinkScreen)

    await asyncio.sleep(1.0)

    web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
    new_count = web_links_widget.displayed_count

    assert new_count == initial_count + 1, (
        f'Expected {initial_count + 1} web links, got {new_count}'
    )

    if table := web_links_widget.data_table:
        assert table.row_count == new_count, (
            f'Expected {new_count} rows in table, got {table.row_count}'
        )


async def delete_web_link_and_verify(pilot):

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
    initial_count = web_links_widget.displayed_count

    if table := web_links_widget.data_table:
        table.focus()
        await asyncio.sleep(0.2)

        if table.row_count > 0:
            table.move_cursor(row=0)
            await asyncio.sleep(0.2)

        await pilot.press('d')
        await asyncio.sleep(0.5)

        from gojeera.components.confirmation_screen import ConfirmationScreen

        screen = pilot.app.screen
        assert isinstance(screen, ConfirmationScreen), (
            f'Expected ConfirmationScreen, got {type(screen)}'
        )

        await pilot.press('enter')
        await asyncio.sleep(1.5)

        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(1.0)

        web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
        web_links_widget.work_item_key = 'EXAMPLE-19539'
        await asyncio.sleep(1.0)
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.5)

        assert not isinstance(pilot.app.screen, ConfirmationScreen)

        web_links_widget = pilot.app.screen.query_one(WorkItemRemoteLinksWidget)
        new_count = web_links_widget.displayed_count

        assert new_count == initial_count - 1, (
            f'Expected {initial_count - 1} web links, got {new_count}'
        )

        if updated_table := web_links_widget.data_table:
            assert updated_table.row_count == new_count, (
                f'Expected {new_count} rows in table, got {updated_table.row_count}'
            )


class TestWorkItemWebLinks:
    def test_work_item_web_links_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=select_work_item_and_highlight_web_link,
        )

    def test_create_web_link_and_verify_in_table(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_web_link_creation,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=create_web_link_and_verify)

    def test_delete_web_link_and_verify_in_table(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_web_link_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=delete_web_link_and_verify)
