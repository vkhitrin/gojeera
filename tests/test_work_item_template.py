import json
from pathlib import Path

import yaml

from httpx import Response
import respx

from gojeera.app import JiraApp
from gojeera.components.screens.create_work_item_screen import AddWorkItemScreen
from gojeera.components.screens.work_item_template_screen import WorkItemTemplatePickerScreen
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.widgets.search.work_item_search_results_scroll import WorkItemSearchResultsScroll
from gojeera.widgets.selection.popup_menu import PopupMenu

from .test_helpers import wait_for_mount, wait_for_worker_idle, wait_until

FIXTURES_DIR = Path(__file__).parent / 'fixtures'
TEMPLATE = yaml.safe_load((FIXTURES_DIR / 'work_item_template_bug.yaml').read_text())
TEMPLATE_SUMMARY = TEMPLATE['summary']


def create_templates_directory(tmp_path, monkeypatch):
    config_home = tmp_path / 'xdg-config'
    templates_dir = config_home / 'gojeera' / 'templates'
    templates_dir.mkdir(parents=True)
    monkeypatch.setattr('gojeera.internal.store.files.xdg_config_home', lambda: config_home)
    return templates_dir


def write_bug_template(templates_dir: Path) -> None:
    (templates_dir / 'bug.yaml').write_text(yaml.safe_dump(TEMPLATE), encoding='utf-8')


def build_app_with_templates(tmp_path, monkeypatch, mock_configuration, mock_user_info):
    templates_dir = create_templates_directory(tmp_path, monkeypatch)
    write_bug_template(templates_dir)
    return JiraApp(settings=mock_configuration, user_info=mock_user_info), templates_dir


def assert_template_snapshot(
    snap_compare,
    mock_configuration,
    mock_user_info,
    monkeypatch,
    tmp_path,
    run_before,
):
    app, _templates_dir = build_app_with_templates(
        tmp_path, monkeypatch, mock_configuration, mock_user_info
    )
    assert snap_compare(app, terminal_size=(120, 40), run_before=run_before)


async def open_create_work_item_menu(pilot) -> None:
    await wait_for_mount(pilot)
    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    search_bar.create_work_item_button.press()
    await wait_until(
        lambda: (
            pilot.app.screen.query_one('#unified-search-new-work-item-menu', PopupMenu).expanded
        ),
        timeout=3.0,
    )
    await wait_until(
        lambda: (
            pilot.app.screen.query_one('#unified-search-new-work-item-menu', PopupMenu).has_focus
        ),
        timeout=3.0,
    )


async def select_create_work_item_menu_entry(pilot, *, from_template: bool = False) -> None:
    await open_create_work_item_menu(pilot)
    menu = pilot.app.screen.query_one('#unified-search-new-work-item-menu', PopupMenu)
    if from_template:
        await pilot.press('down')
        await wait_until(lambda: menu.highlighted_index == 1, timeout=3.0)
    await pilot.press('enter')
    await wait_until(lambda: not menu.expanded, timeout=3.0)


async def open_missing_templates_notification_from_menu(pilot) -> None:
    await select_create_work_item_menu_entry(pilot, from_template=True)
    await wait_until(lambda: pilot.app._notifications, timeout=3.0)


async def open_work_item_template_screen_from_menu(pilot) -> None:
    await select_create_work_item_menu_entry(pilot, from_template=True)
    await wait_until(
        lambda: isinstance(pilot.app.screen, WorkItemTemplatePickerScreen), timeout=3.0
    )
    await wait_for_worker_idle(pilot)


async def select_template_in_screen(pilot) -> None:
    await open_work_item_template_screen_from_menu(pilot)
    await wait_until(
        lambda: (
            isinstance(pilot.app.screen, WorkItemTemplatePickerScreen)
            and pilot.app.screen.templates_loaded
        ),
        timeout=3.0,
    )
    await pilot.press('enter')
    await pilot.pause()
    await pilot.press('down')
    await pilot.pause()
    await pilot.press('enter')
    await wait_until(
        lambda: (
            isinstance(pilot.app.screen, WorkItemTemplatePickerScreen)
            and not pilot.app.screen.use_button.disabled
        ),
        timeout=3.0,
    )
    await pilot.pause()


async def select_template_and_use_from_screen(pilot) -> None:
    await select_template_in_screen(pilot)
    await pilot.press('tab')
    await pilot.pause()
    await pilot.press('enter')
    await wait_until(lambda: isinstance(pilot.app.screen, AddWorkItemScreen), timeout=3.0)
    await wait_for_worker_idle(pilot)
    await wait_until(
        lambda: (
            isinstance(pilot.app.screen, AddWorkItemScreen)
            and pilot.app.screen.summary_field.value == TEMPLATE_SUMMARY
        ),
        timeout=3.0,
    )
    await pilot.pause()


async def trigger_search_and_get_results_list(pilot) -> WorkItemSearchResultsScroll:
    await pilot.press('ctrl+j')
    await pilot.app.workers.wait_for_complete()
    return pilot.app.screen.query_one(WorkItemSearchResultsScroll)


async def load_all_work_items(pilot) -> None:
    await wait_for_mount(pilot)
    search_results_list = await trigger_search_and_get_results_list(pilot)
    await wait_until(
        lambda: (
            search_results_list.work_item_search_results is not None
            and len(search_results_list.work_item_search_results.work_items) >= 8
        ),
        timeout=3.0,
    )
    await pilot.pause()


async def create_work_item_from_selected_template_and_search(pilot) -> None:
    await load_all_work_items(pilot)
    await select_template_in_screen(pilot)
    await pilot.press('tab', 'tab')
    await pilot.pause()
    await pilot.press('enter')
    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: not isinstance(pilot.app.screen, WorkItemTemplatePickerScreen), timeout=3.0
    )

    search_results_list = await trigger_search_and_get_results_list(pilot)
    await wait_until(
        lambda: (
            search_results_list.work_item_search_results is not None
            and len(search_results_list.work_item_search_results.work_items) >= 9
            and any(
                work_item.key == 'ENG-9' and work_item.summary == TEMPLATE_SUMMARY
                for work_item in search_results_list.work_item_search_results.work_items
            )
        ),
        timeout=3.0,
    )
    await pilot.pause()


def mock_template_created_work_item_search(mock_jira_search_with_results: dict) -> None:
    created_work_item = json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-8.json').read_text())
    created_work_item['id'] = '10003'
    created_work_item['key'] = 'ENG-9'
    created_work_item['self'] = 'https://example.atlassian.acme.net/rest/api/3/issue/10003'
    created_work_item['fields']['summary'] = TEMPLATE_SUMMARY

    all_work_items = [created_work_item, *mock_jira_search_with_results['issues']]

    def search_handler(request):
        body = json.loads(request.content)
        jql = str(body.get('jql', '')).strip().lower()
        if 'key = eng-9' in jql or 'key=eng-9' in jql:
            issues = [created_work_item]
        else:
            issues = all_work_items
        return Response(
            200,
            json={
                'issues': issues,
                'isLast': True,
                'maxResults': max(50, len(issues)),
                'startAt': 0,
                'total': len(issues),
            },
        )

    def count_handler(request):
        body = json.loads(request.content)
        jql = str(body.get('jql', '')).strip().lower()
        count = 1 if 'key = eng-9' in jql or 'key=eng-9' in jql else len(all_work_items)
        return Response(200, json={'count': count})

    respx.post('https://example.atlassian.acme.net/rest/api/3/issue').mock(
        return_value=Response(
            201,
            json={
                'id': '10003',
                'key': 'ENG-9',
                'self': 'https://example.atlassian.acme.net/rest/api/3/issue/10003',
            },
        )
    )
    respx.get(
        url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-9(?:\?.*)?$'
    ).mock(return_value=Response(200, json=created_work_item))
    respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(
        side_effect=search_handler
    )
    respx.post('https://example.atlassian.acme.net/rest/api/3/search/approximate-count').mock(
        side_effect=count_handler
    )


class TestWorkItemTemplate:
    def test_create_work_item_menu_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        _ = mock_jira_api_sync
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_create_work_item_menu)

    def test_create_work_item_from_template_without_templates(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_sync,
        mock_user_info,
        monkeypatch,
        tmp_path,
    ):
        _ = mock_jira_api_sync
        config_home = tmp_path / 'xdg-config'
        monkeypatch.setattr('gojeera.internal.store.files.xdg_config_home', lambda: config_home)
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_missing_templates_notification_from_menu,
        )

    def test_create_work_item_menu_entry_opens_template_screen(
        self,
        snap_compare,
        mock_jira_api_sync,
        mock_configuration,
        mock_user_info,
        tmp_path,
        monkeypatch,
    ):
        _ = mock_jira_api_sync
        assert_template_snapshot(
            snap_compare=snap_compare,
            mock_configuration=mock_configuration,
            mock_user_info=mock_user_info,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            run_before=open_work_item_template_screen_from_menu,
        )

    def test_template_use_template_opens_create_work_item_screen(
        self,
        snap_compare,
        mock_jira_api_with_create_work_item,
        mock_configuration,
        tmp_path,
        mock_user_info,
        monkeypatch,
    ):
        _ = mock_jira_api_with_create_work_item
        assert_template_snapshot(
            snap_compare,
            mock_configuration,
            mock_user_info,
            monkeypatch,
            tmp_path,
            run_before=select_template_and_use_from_screen,
        )

    def test_template_selected_template_state(
        self,
        snap_compare,
        mock_jira_api_sync,
        mock_configuration,
        monkeypatch,
        mock_user_info,
        tmp_path,
    ):
        _ = mock_jira_api_sync
        assert_template_snapshot(
            snap_compare,
            mock_configuration=mock_configuration,
            mock_user_info=mock_user_info,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            run_before=select_template_in_screen,
        )

    def test_template_create_work_item_loads_created_work_item_in_search(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_jira_search_with_results,
        mock_user_info,
        monkeypatch,
        tmp_path,
    ):
        _ = mock_jira_api_with_search_results
        app, _templates_dir = build_app_with_templates(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            mock_configuration=mock_configuration,
            mock_user_info=mock_user_info,
        )
        mock_template_created_work_item_search(mock_jira_search_with_results)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=create_work_item_from_selected_template_and_search,
        )

    def test_template_screen_skips_invalid_templates_with_notification(
        self,
        snap_compare,
        mock_jira_api_sync,
        mock_configuration,
        tmp_path,
        mock_user_info,
        monkeypatch,
    ):
        _ = mock_jira_api_sync
        app, templates_dir = build_app_with_templates(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            mock_configuration=mock_configuration,
            mock_user_info=mock_user_info,
        )
        (templates_dir / 'invalid.yaml').write_text('[unclosed', encoding='utf-8')

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_work_item_template_screen_from_menu,
        )
