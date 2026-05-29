import asyncio
import json
from pathlib import Path

from httpx import Response
import respx

from gojeera.app import JiraApp
from gojeera.components.screens.create_work_item_screen import AddWorkItemScreen
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.utils.system import clipboard_attachments as clipboard_attachments_module
from gojeera.utils.ui.widgets_factory_utils import DynamicFieldWrapper
from gojeera.widgets.selection.popup_menu import PopupMenu
from gojeera.widgets.selection.selection import SelectionWidget

from .test_helpers import (
    search_for_work_item_key_and_assert_single_result,
    stage_clipboard_upload,
    wait_for_mount,
    wait_for_screen_to_settle,
    wait_for_worker_idle,
    wait_until,
)

ENG_8_SUMMARY = json.loads(
    Path(__file__).parent.joinpath('fixtures', 'jira_work_items', 'ENG-8.json').read_text()
)['fields']['summary']
ENG_8_WORK_ITEM = json.loads(
    Path(__file__).parent.joinpath('fixtures', 'jira_work_items', 'ENG-8.json').read_text()
)


async def open_create_work_item_screen(pilot):
    """Open the create work item screen."""
    await wait_for_mount(pilot)
    await pilot.press('ctrl+n')
    await wait_until(lambda: isinstance(pilot.app.screen, AddWorkItemScreen), timeout=3.0)


async def open_create_work_item_screen_from_menu(pilot):
    await wait_for_mount(pilot)
    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    search_bar.create_work_item_button.press()
    await wait_until(
        lambda: (
            pilot.app.screen.query_one('#unified-search-new-work-item-menu', PopupMenu).expanded
        ),
        timeout=3.0,
    )
    await pilot.press('enter')
    await wait_until(lambda: isinstance(pilot.app.screen, AddWorkItemScreen), timeout=3.0)
    await asyncio.sleep(0.2)


async def open_and_select_project(pilot):
    """Open create work item screen and select a project."""
    await open_create_work_item_screen(pilot)
    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen)

    await wait_until(
        lambda: screen.project_selector.prompt == 'Select a project',
        timeout=3.0,
    )
    await pilot.press('enter')
    await pilot.pause()
    await pilot.press('down', 'enter')
    await wait_until(
        lambda: screen.project_selector.value != screen.project_selector.BLANK, timeout=3.0
    )
    await wait_until(lambda: screen._selected_project_key is not None, timeout=3.0)
    await wait_for_worker_idle(pilot)


async def fill_required_fields(pilot):
    """Open create work item screen and fill required fields."""
    await open_and_select_project(pilot)

    # Select work item type
    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    await pilot.press('tab')
    await pilot.pause()
    await pilot.press('enter')
    await pilot.pause()
    await pilot.press('down', 'enter')
    await wait_until(
        lambda: screen.work_item_type_selector.value != screen.work_item_type_selector.BLANK,
        timeout=3.0,
    )
    await wait_until(lambda: not screen.dynamic_fields_container.loading, timeout=3.0)
    await wait_until(lambda: screen._metadata_loaded_for is not None, timeout=3.0)
    await wait_for_worker_idle(pilot)

    await pilot.press('tab')
    await pilot.pause()

    await pilot.press('tab')
    await pilot.pause()

    await pilot.press('tab')
    await pilot.pause()
    await pilot.press(*ENG_8_SUMMARY)
    await wait_until(lambda: screen.summary_field.value == ENG_8_SUMMARY, timeout=3.0)

    await pilot.press('tab')
    await pilot.pause()

    priority_widget = None
    for wrapper in screen.dynamic_fields_container.query(DynamicFieldWrapper):
        selection_widgets = wrapper.query(SelectionWidget)
        for widget in selection_widgets:
            if hasattr(widget, 'field_id') and widget.field_id == 'priority':
                priority_widget = widget
                break
        if priority_widget:
            break

    assert priority_widget is not None, 'Priority widget not found'

    priority_widget.value = '1'
    await wait_until(lambda: priority_widget.value == '1', timeout=3.0)

    screen.save_button.disabled = not screen._validate_required_fields()
    await wait_until(lambda: not screen.save_button.disabled, timeout=3.0)

    pending_fields = screen._get_pending_dynamic_fields()
    assert len(pending_fields) == 0, f'Required fields still pending: {pending_fields}'


async def fill_and_save_work_item(pilot):
    """Fill required fields and press the Save button."""
    await fill_required_fields(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    assert not screen.save_button.disabled, 'Save button should be enabled before pressing'

    screen.save_button.press()
    await wait_until(lambda: not isinstance(pilot.app.screen, AddWorkItemScreen), timeout=3.0)
    await wait_for_screen_to_settle(pilot)

    assert not isinstance(pilot.app.screen, AddWorkItemScreen), (
        f'Expected to return to the workspace, but still on {type(pilot.app.screen)}'
    )


async def fill_save_and_search_work_item(pilot):
    """Fill required fields, save, open unified search, and search for the created work item."""
    await fill_and_save_work_item(pilot)

    await search_for_work_item_key_and_assert_single_result(
        pilot,
        work_item_key='ENG-8',
        expected_summary=ENG_8_SUMMARY,
    )


async def fill_save_and_upload_clipboard_attachment(pilot):
    await fill_required_fields(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen)

    await screen.action_paste_clipboard_attachment()
    await pilot.pause()

    screen.save_button.press()
    await wait_until(lambda: not isinstance(pilot.app.screen, AddWorkItemScreen), timeout=3.0)
    await wait_for_screen_to_settle(pilot)

    assert not isinstance(pilot.app.screen, AddWorkItemScreen)


async def fill_save_and_open_created_work_item_attachments(pilot):
    await fill_save_and_upload_clipboard_attachment(pilot)

    await pilot.app.load_work_item('ENG-8')
    await wait_for_worker_idle(pilot)
    await wait_until(lambda: pilot.app.current_loaded_work_item_key == 'ENG-8', timeout=3.0)

    pilot.app.tabs.active = 'tab-attachments'
    pilot.app.information_panel.set_active_tab('tab-attachments')
    await wait_until(
        lambda: pilot.app.work_item_attachments_widget.record_list is not None,
        timeout=3.0,
    )
    await wait_until(
        lambda: not pilot.app.work_item_attachments_widget.is_loading,
        timeout=3.0,
    )


class TestCreateWorkItemScreen:
    """Snapshot tests to verify create work item screen display and interactions."""

    def test_create_work_item_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_with_create_work_item, mock_user_info
    ):
        """Snapshot: Create work item screen in initial state."""
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_create_work_item_screen)

    def test_create_work_item_menu_entry_opens_create_work_item_screen(
        self, snap_compare, mock_configuration, mock_jira_api_with_create_work_item, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_create_work_item_screen_from_menu,
        )

    def test_create_work_item_all_required_filled(
        self, snap_compare, mock_configuration, mock_jira_api_with_create_work_item, mock_user_info
    ):
        """Snapshot: Create work item screen with all required fields filled."""
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_required_fields)

    def test_create_work_item_save_and_search(
        self, snap_compare, mock_configuration, mock_jira_api_with_create_work_item, mock_user_info
    ):
        """Snapshot: After saving create work item and searching for it, results appear."""
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_save_and_search_work_item)

    def test_create_work_item_uploads_clipboard_attachment_after_creation(
        self,
        snap_compare,
        monkeypatch,
        mock_configuration,
        mock_jira_api_with_create_work_item,
        mock_jira_new_attachment,
        mock_user_info,
        staged_upload_file,
        mock_attachment_upload,
    ):
        stage_clipboard_upload(monkeypatch, clipboard_attachments_module, staged_upload_file)

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        created_work_item = json.loads(json.dumps(ENG_8_WORK_ITEM))
        uploaded_attachment = json.loads(json.dumps(mock_jira_new_attachment))
        uploaded_attachment['filename'] = 'clipboard-upload.png'
        uploaded_attachment['mimeType'] = 'image/png'
        uploaded_attachment['size'] = 3
        created_work_item['fields']['attachment'] = [
            *created_work_item['fields'].get('attachment', []),
            uploaded_attachment,
        ]
        upload_route = mock_attachment_upload('ENG-8')
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-8(?:\?.*)?$'
        ).mock(return_value=Response(200, json=created_work_item))
        update_route = respx.put(
            'https://example.atlassian.acme.net/rest/api/3/issue/ENG-8',
            params={'returnIssue': 'true'},
        ).mock(return_value=Response(200, json=created_work_item))

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=fill_save_and_open_created_work_item_attachments,
        )
        assert upload_route.called
        assert upload_route.call_count == 1
        assert b'filename="clipboard-upload.png"' in upload_route.calls[0].request.content
        assert update_route.called
        assert (
            b'https://example.atlassian.acme.net/secure/attachment/66812/clipboard-upload.png'
            in update_route.calls[0].request.content
        )
