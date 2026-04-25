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
    if table := web_links_widget.record_list:
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

    if table := web_links_widget.record_list:
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
