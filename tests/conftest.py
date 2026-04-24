import asyncio
import copy
import inspect
import json
from pathlib import Path

from httpx import Response
from pydantic import SecretStr
import pytest
import pytest_textual_snapshot
import respx
from rich.console import Console
from syrupy import SnapshotAssertion
from textual.app import App
from textual.pilot import Pilot
from textual.widgets import Input, TextArea

from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION, ApplicationConfiguration, JiraConfig

pytest_textual_snapshot.SVGImageExtension.file_extension = 'svg'


@pytest.fixture(autouse=True)
def disable_input_cursor_blink(monkeypatch):
    """Disable Textual input cursor rendering to stabilize snapshots."""

    original_on_mount = Input._on_mount
    original_restart_blink = Input._restart_blink
    original_text_area_on_mount = TextArea._on_mount
    original_text_area_restart_blink = TextArea._restart_blink

    def patched_on_mount(self, event):
        original_on_mount(self, event)
        self.cursor_blink = False
        self._pause_blink(visible=False)

    def patched_restart_blink(self):
        if not self.cursor_blink:
            self._pause_blink(visible=False)
            return
        original_restart_blink(self)

    def patched_text_area_on_mount(self, event):
        original_text_area_on_mount(self, event)
        self.cursor_blink = False
        self._pause_blink(visible=False)

    def patched_text_area_restart_blink(self):
        if not self.cursor_blink:
            self._pause_blink(visible=False)
            return
        original_text_area_restart_blink(self)

    monkeypatch.setattr(Input, '_on_mount', patched_on_mount)
    monkeypatch.setattr(Input, '_restart_blink', patched_restart_blink)
    monkeypatch.setattr(TextArea, '_on_mount', patched_text_area_on_mount)
    monkeypatch.setattr(TextArea, '_restart_blink', patched_text_area_restart_blink)


def _snapshot_loading_in_progress(app: App) -> bool:
    screen = app.screen

    if screen.__class__.__name__ == 'MainScreen':
        if bool(getattr(screen, '_active_work_item_load_key', None)):
            return True
        if bool(getattr(getattr(screen, 'unified_search_bar', None), 'search_in_progress', False)):
            return True
        if bool(getattr(getattr(screen, 'search_results_container', None), 'is_loading', False)):
            return True
        if bool(
            getattr(
                getattr(screen, 'search_results_list', None), 'is_pending_initial_render', False
            )
        ):
            return True
        return False

    for node in screen.walk_children(with_self=True):
        if not bool(getattr(node, 'display', True)) or not bool(getattr(node, 'visible', True)):
            continue
        for attribute_name in ('is_loading', 'search_in_progress', '_is_loading'):
            if bool(getattr(node, attribute_name, False)):
                return True
    return False


async def wait_for_snapshot_stability(
    pilot: Pilot, *, timeout: float = 5.0, interval: float = 0.05
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout

    while True:
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()

        if not _snapshot_loading_in_progress(pilot.app):
            await asyncio.sleep(interval)
            await pilot.wait_for_scheduled_animations()
            await pilot.pause()
            if not _snapshot_loading_in_progress(pilot.app):
                return

        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError('Timed out waiting for snapshot state to settle')

        await asyncio.sleep(interval)


@pytest.fixture
def snap_compare(snapshot: SnapshotAssertion, request: pytest.FixtureRequest):
    """Compare snapshots after globally settling async UI state."""
    snapshot = snapshot.use_extension(pytest_textual_snapshot.SVGImageExtension)

    def compare(
        app: str | Path | App,
        press=(),
        terminal_size: tuple[int, int] = (80, 24),
        run_before=None,
    ) -> bool:
        from textual._doc import take_svg_screenshot
        from textual._import_app import import_app

        node = request.node

        if isinstance(app, App):
            app_instance = app
            app_path = ''
        else:
            path = Path(app)
            if path.is_absolute():
                app_path = str(path.resolve())
                app_instance = import_app(app_path)
            else:
                resolved = (node.path.parent / app).resolve()
                app_path = str(resolved)
                app_instance = import_app(app_path)

        async def run_before_settled(pilot: Pilot) -> None:
            if run_before is not None:
                result = run_before(pilot)
                if inspect.isawaitable(result):
                    await result
            await wait_for_snapshot_stability(pilot)

        actual_screenshot = take_svg_screenshot(
            app=app_instance,
            press=press,
            terminal_size=terminal_size,
            run_before=run_before_settled,
        )
        console = Console(legacy_windows=False, force_terminal=True)
        pseudo_app = pytest_textual_snapshot.PseudoApp(
            pytest_textual_snapshot.PseudoConsole(console.legacy_windows, console.size)
        )

        result = snapshot == actual_screenshot

        custom_execution_index = (
            snapshot._execution_name_index.get(snapshot._custom_index)
            if snapshot._custom_index
            else None
        )
        execution_index = (
            custom_execution_index
            if isinstance(custom_execution_index, int)
            else snapshot.num_executions - 1
        )
        assertion_result = snapshot.executions.get(execution_index)
        snapshot_exists = (
            execution_index in snapshot.executions
            and assertion_result
            and assertion_result.final_data is not None
        )

        expected_svg_text = str(snapshot)
        full_path, line_number, name = node.reportinfo()
        data = (
            result,
            expected_svg_text,
            actual_screenshot,
            pseudo_app,
            full_path,
            line_number,
            name,
            inspect.getdoc(node.function) or '',
            app_path,
            snapshot_exists,
        )
        data_path = pytest_textual_snapshot.node_to_report_path(request.node)
        data_path.write_bytes(pytest_textual_snapshot.pickle.dumps(data))

        return result

    return compare


# NOTE: (vkhitrin) Clear the global application cache after each test
#       to prevent cross-test contamination.
@pytest.fixture(autouse=True)
def clear_global_cache():
    yield
    cache = get_cache()
    cache.clear()


@pytest.fixture(autouse=True)
def mock_configuration():
    jira_config = JiraConfig(
        api_email_override='testuser@example.com',
        api_token=SecretStr('test-token'),
        api_base_url_override='https://example.atlassian.acme.net',
    )

    config = ApplicationConfiguration(
        jira=jira_config,
        enable_sprint_selection=True,
        show_work_item_web_links=True,
        ignore_users_without_email=True,
        jql_filters=None,
        jql_filter_label_for_work_items_search=None,
        search_results_per_page=20,
        search_results_truncate_work_item_summary=None,
        log_file=None,
        log_level='WARNING',
        confirm_before_quit=True,
        theme=None,
        enable_advanced_full_text_search=True,
        search_on_startup=False,
        enable_updating_additional_fields=False,
        update_additional_fields_ignore_ids=None,
        enable_creating_additional_fields=False,
        create_additional_fields_ignore_ids=None,
    )

    token = CONFIGURATION.set(config)

    yield config

    CONFIGURATION.reset(token)


@pytest.fixture
def mock_configuration_with_sprints():
    """Configuration with sprint selection enabled for sprint-related tests."""
    jira_config = JiraConfig(
        api_email_override='testuser@example.com',
        api_token=SecretStr('test-token'),
        api_base_url_override='https://example.atlassian.acme.net',
    )

    config = ApplicationConfiguration(
        jira=jira_config,
        enable_sprint_selection=True,
        show_work_item_web_links=True,
        ignore_users_without_email=True,
        jql_filters=None,
        jql_filter_label_for_work_items_search=None,
        search_results_per_page=20,
        search_results_truncate_work_item_summary=None,
        log_file=None,
        log_level='WARNING',
        confirm_before_quit=True,
        theme=None,
        enable_advanced_full_text_search=True,
        search_on_startup=False,
        enable_updating_additional_fields=False,
        update_additional_fields_ignore_ids=None,
        enable_creating_additional_fields=False,
        create_additional_fields_ignore_ids=None,
    )

    token = CONFIGURATION.set(config)

    yield config

    CONFIGURATION.reset(token)


def load_fixture(filename: str):
    fixture_path = Path(__file__).parent / 'fixtures' / filename
    with fixture_path.open() as f:
        return json.load(f)


def load_issue_fixtures(directory: str):
    fixtures_dir = Path(__file__).parent / 'fixtures' / directory
    issues = []
    project_order = {'ENG': 0, 'SUP': 1}

    def sort_key(fixture_path: Path) -> tuple[int, int]:
        project_key, issue_number = fixture_path.stem.split('-', 1)
        return (project_order.get(project_key, 99), -int(issue_number))

    for fixture_path in sorted(fixtures_dir.glob('*.json'), key=sort_key):
        with fixture_path.open() as f:
            issues.append(json.load(f))
    return {'issues': issues}


# Helper functions for common mock patterns
def mock_jql_validation():
    payload = load_fixture('jira_jql_validation_valid.json')
    respx.post('https://example.atlassian.acme.net/rest/api/3/jql/parse').mock(
        return_value=Response(200, json=payload)
    )


def mock_server_info(mock_jira_server_info):
    respx.get('https://example.atlassian.acme.net/rest/api/3/serverInfo').mock(
        return_value=Response(200, json=mock_jira_server_info)
    )


def mock_myself(mock_jira_myself):
    respx.get('https://example.atlassian.acme.net/rest/api/3/myself').mock(
        return_value=Response(200, json=mock_jira_myself)
    )


def mock_search_empty(mock_jira_search_empty):
    respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(
        return_value=Response(200, json=mock_jira_search_empty)
    )


def mock_search_empty_results():
    payload = load_fixture('jira_search_empty.json')
    respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(
        return_value=Response(200, json=payload)
    )


def get_search_results_payload(mock_payload: dict) -> dict:
    return mock_payload.get('_search_page', mock_payload)


def mock_search_with_results(mock_jira_search_with_results):
    respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(
        return_value=Response(200, json=get_search_results_payload(mock_jira_search_with_results))
    )


def mock_approximate_count_empty():
    payload = load_fixture('jira_approximate_count_empty.json')
    respx.post('https://example.atlassian.acme.net/rest/api/3/search/approximate-count').mock(
        return_value=Response(200, json=payload)
    )


def mock_approximate_count(count):
    respx.post('https://example.atlassian.acme.net/rest/api/3/search/approximate-count').mock(
        return_value=Response(200, json=build_count_results(count))
    )


def mock_projects_search(mock_jira_projects):
    respx.get('https://example.atlassian.acme.net/rest/api/3/project/search').mock(
        return_value=Response(200, json=mock_jira_projects)
    )


def mock_issue_types(mock_jira_issue_types):
    respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
        return_value=Response(200, json=mock_jira_issue_types)
    )


def mock_statuses(mock_jira_statuses):
    respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
        return_value=Response(200, json=mock_jira_statuses)
    )


def mock_configuration_endpoint(mock_jira_configuration):
    respx.get('https://example.atlassian.acme.net/rest/api/3/configuration').mock(
        return_value=Response(200, json=mock_jira_configuration)
    )


def mock_assignable_users(mock_jira_users):
    respx.get(
        'https://example.atlassian.acme.net/rest/api/3/user/assignable/multiProjectSearch'
    ).mock(return_value=Response(200, json=mock_jira_users))


def mock_assignable_users_single_project(mock_jira_users):
    respx.get('https://example.atlassian.acme.net/rest/api/3/user/assignable/search').mock(
        return_value=Response(200, json=mock_jira_users)
    )


def get_project_by_key(mock_jira_projects, project_key):
    for project in mock_jira_projects.get('values', []):
        if project.get('key') == project_key:
            return project
    return mock_jira_projects['values'][0]


def get_issue_types_for_project(
    project_key, mock_jira_issue_types, mock_jira_support_issue_types=None
):
    if project_key == 'SUP' and mock_jira_support_issue_types is not None:
        return mock_jira_support_issue_types
    return mock_jira_issue_types


def get_statuses_for_project(project_key, mock_jira_statuses, mock_jira_support_statuses=None):
    if project_key == 'SUP' and mock_jira_support_statuses is not None:
        return mock_jira_support_statuses
    return mock_jira_statuses


def mock_project_endpoint(
    project_key,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_support_issue_types=None,
):
    project = get_project_by_key(mock_jira_projects, project_key)
    issue_types = get_issue_types_for_project(
        project_key, mock_jira_issue_types, mock_jira_support_issue_types
    )
    respx.get(f'https://example.atlassian.acme.net/rest/api/3/project/{project_key}').mock(
        return_value=Response(200, json=build_project_detail(project, issue_types))
    )


def mock_project_statuses(
    project_key,
    mock_jira_statuses,
    mock_jira_issue_types,
    mock_jira_support_statuses=None,
    mock_jira_support_issue_types=None,
):
    statuses = get_statuses_for_project(project_key, mock_jira_statuses, mock_jira_support_statuses)
    issue_types = get_issue_types_for_project(
        project_key, mock_jira_issue_types, mock_jira_support_issue_types
    )
    respx.get(f'https://example.atlassian.acme.net/rest/api/3/project/{project_key}/statuses').mock(
        return_value=Response(
            200,
            json=[
                {
                    'id': issue_type['id'],
                    'name': issue_type['name'],
                    'self': issue_type['self'],
                    'subtask': issue_type['subtask'],
                    'statuses': statuses,
                }
                for issue_type in issue_types
            ],
        )
    )


def mock_fields_endpoints(mock_jira_fields, mock_jira_fields_search):
    respx.get('https://example.atlassian.acme.net/rest/api/3/field').mock(
        return_value=Response(200, json=mock_jira_fields)
    )
    respx.get('https://example.atlassian.acme.net/rest/api/3/field/search').mock(
        return_value=Response(200, json=mock_jira_fields_search)
    )


def mock_support_project_createmeta(mock_jira_support_issue_types, mock_support_createmeta_fields):
    for issue_type in mock_jira_support_issue_types:
        issue_type_id = issue_type['id']
        respx.get(
            url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/createmeta/SUP/issuetypes/{issue_type_id}.*'
        ).mock(return_value=Response(200, json=mock_support_createmeta_fields))


def mock_support_issue_transitions(mock_support_transitions_data):
    respx.get(
        url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/SUP-[^/]+/transitions'
    ).mock(return_value=Response(200, json=mock_support_transitions_data))


def mock_engineering_project_createmeta(mock_engineering_createmeta_fields):
    def handler(request):
        payload = copy.deepcopy(mock_engineering_createmeta_fields)
        issue_type_id = request.url.path.rstrip('/').split('/')[-1]

        if issue_type_id == '10002':
            for field in payload.get('fields', []):
                if field.get('fieldId') == 'priority':
                    field['required'] = False
                    break

        return Response(200, json=payload)

    respx.get(
        url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/createmeta/(ENG|10446)/issuetypes/[^/?]+.*'
    ).mock(side_effect=handler)


def mock_empty_comments(work_item_key: str):
    respx.get(f'https://example.atlassian.acme.net/rest/api/3/issue/{work_item_key}/comment').mock(
        return_value=Response(200, json=build_comments_page(work_item_key, []))
    )


def build_search_results_page(issues: list[dict], next_page_token: str | None = None) -> dict:
    return {
        'issues': issues,
        'nextPageToken': next_page_token,
        'isLast': next_page_token is None,
    }


def build_count_results(count: int) -> dict:
    return {'count': count}


def build_comments_page(work_item_key: str, comments: list[dict]) -> dict:
    return {
        'comments': comments,
        'self': f'https://example.atlassian.acme.net/rest/api/3/issue/{work_item_key}/comment',
        'maxResults': len(comments),
        'total': len(comments),
        'startAt': 0,
    }


def build_worklogs_page(worklogs: list[dict]) -> dict:
    return {
        'maxResults': len(worklogs),
        'startAt': 0,
        'total': len(worklogs),
        'worklogs': worklogs,
    }


def build_transitions_payload(transitions: list[dict]) -> dict:
    return {
        'expand': 'transitions',
        'transitions': transitions,
    }


def build_created_issue(issue_id: str, issue_key: str) -> dict:
    return {
        'id': issue_id,
        'key': issue_key,
        'self': f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_id}',
    }


def build_remote_issue_link_identifies(work_item_key: str, link_id: str) -> dict:
    return {
        'id': link_id,
        'self': f'https://example.atlassian.acme.net/rest/api/3/issue/{work_item_key}/remotelink/{link_id}',
    }


def build_project_detail(project: dict, issue_types: list[dict]) -> dict:
    return {
        **copy.deepcopy(project),
        'issueTypes': copy.deepcopy(issue_types),
    }


def get_issue_by_key(issues: list[dict], issue_key: str) -> dict:
    return copy.deepcopy(next(issue for issue in issues if issue['key'] == issue_key))


def build_issue_response(issue: dict, field_ids: list[str] | None = None) -> dict:
    payload = {
        'id': issue['id'],
        'key': issue['key'],
        'self': issue['self'],
        'fields': copy.deepcopy(issue.get('fields', {})),
    }
    if field_ids is not None:
        payload['fields'] = {
            field_id: value
            for field_id, value in payload['fields'].items()
            if field_id in set(field_ids)
        }
    return payload


def mock_empty_transitions(work_item_key: str):
    respx.get(
        f'https://example.atlassian.acme.net/rest/api/3/issue/{work_item_key}/transitions'
    ).mock(return_value=Response(200, json=build_transitions_payload([])))


def mock_agile_boards(mock_jira_engineering_agile_boards, project_key='ENG'):
    respx.get(
        'https://example.atlassian.acme.net/rest/agile/1.0/board',
        params={'projectKeyOrId': project_key, 'startAt': 0, 'maxResults': 50},
    ).mock(return_value=Response(200, json=mock_jira_engineering_agile_boards))


def mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=1):
    respx.get(
        f'https://example.atlassian.acme.net/rest/agile/1.0/board/{board_id}/sprint',
        params={'state': 'active,future', 'startAt': 0, 'maxResults': 50},
    ).mock(return_value=Response(200, json=mock_jira_engineering_agile_sprints))


def mock_agile_endpoints_for_example_project(
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
):
    mock_agile_boards(mock_jira_engineering_agile_boards, project_key='ENG')
    mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=1)
    mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=2)
    # Fallback matchers for requests with reordered or extra query params.
    respx.get(url__regex=r'https://example\.atlassian\.acme\.net/rest/agile/1\.0/board\?.*').mock(
        return_value=Response(200, json=mock_jira_engineering_agile_boards)
    )
    respx.get(
        url__regex=r'https://example\.atlassian\.acme\.net/rest/agile/1\.0/board/1/sprint\?.*'
    ).mock(return_value=Response(200, json=mock_jira_engineering_agile_sprints))
    respx.get(
        url__regex=r'https://example\.atlassian\.acme\.net/rest/agile/1\.0/board/2/sprint\?.*'
    ).mock(return_value=Response(200, json=mock_jira_engineering_agile_sprints))


def setup_common_mocks(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_jira_support_issue_types=None,
    mock_jira_support_statuses=None,
    mock_support_transitions_data=None,
    mock_support_createmeta_fields=None,
):
    mock_server_info(mock_jira_server_info)
    mock_myself(mock_jira_myself)
    mock_projects_search(mock_jira_projects)
    mock_issue_types(mock_jira_issue_types)
    mock_statuses(mock_jira_statuses)
    for project in mock_jira_projects.get('values', []):
        project_key = project.get('key')
        if not project_key:
            continue
        if project_key == 'SUP' and (
            mock_jira_support_issue_types is None or mock_jira_support_statuses is None
        ):
            continue
        mock_project_endpoint(
            project_key,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_support_issue_types,
        )
        mock_project_statuses(
            project_key,
            mock_jira_statuses,
            mock_jira_issue_types,
            mock_jira_support_statuses,
            mock_jira_support_issue_types,
        )
    if mock_jira_support_issue_types is not None and mock_support_createmeta_fields is not None:
        mock_support_project_createmeta(
            mock_jira_support_issue_types,
            mock_support_createmeta_fields,
        )
    if mock_support_transitions_data is not None:
        mock_support_issue_transitions(mock_support_transitions_data)
    mock_jql_validation()


@pytest.fixture
def work_item_adf_description(mock_jira_search_with_results):
    work_item = next(
        issue for issue in mock_jira_search_with_results['issues'] if issue['key'] == 'ENG-2'
    )
    return work_item['fields']['description']


@pytest.fixture
def work_item_markdown_description():
    """Comprehensive markdown description for testing Markdown to ADF conversion.

    This fixture contains the same content as work_item_adf_description,
    but in Markdown format (the inverse of the ADF fixture).
    """
    return """# GitHub Flavored Markdown (GFM) All-in-One Test

## 1. Alerts (Admonitions)

> [!NOTE]
> **Note:** Highlights information that users should take into account, even when skimming.

> [!TIP]
> **Tip:** Optional information to help a user be more successful.

> [!IMPORTANT]
> **Important:** Crucial information necessary for users to succeed.

> [!WARNING]
> **Warning:** Critical content demanding immediate user attention due to potential risks.

> [!CAUTION]
> **Caution:** Negative potential consequences of an action.

---

## 2. Text Formatting

**Bold Text** *Italic Text* ***Bold and Italic*** ~~Strikethrough~~ **Bold and ~~Strikethrough~~** `Inline Code`

---

## 3. Lists

### Checkboxes (Task List)

- [x] Completed task
- [ ] Incomplete task
- [ ] [Links in tasks works too](https://github.com)

### Nested Lists

1. First item
    - Unordered sub-item
    - Another sub-item
2. Second item
    1. Ordered sub-item A
    2. Ordered sub-item B

---

## 4. Code Blocks

### Syntax Highlighting (JavaScript)

```javascript
const greet = (name) => {
  console.log(`Hello, ${name}!`);
}
greet("GitHub");
```

### Syntax Highlighting (diff)

```diff
- const userStatus = "offline";
+ const userStatus = "online";
! const userStatus = "away"; // (Orange/Warning in some renderers)
# This is a comment/metadata line
```

## 5. Table

| Left Align | Center Align | Right Align |
|------------|--------------|-------------|
| Item 1     | Value        | $100        |
| Item 2     | Value        | $50         |
| Item 3     | Value        | $10         |

# Atlassian Document Format Test

## 1. User Mentions

@Test User /jira/people/123456:abcd1234-1234-1234-1234-abcdef123456

## 2. Date

[date]2026-01-28

## 3. Emojis

😀 🚀

## 4. Status

[status:n]TEST

## 5. Decisions

[decision:d]Test

---
"""


@pytest.fixture
def mock_jira_server_info():
    return load_fixture('jira_server_info.json')


@pytest.fixture
def mock_jira_myself():
    return load_fixture('jira_myself.json')


@pytest.fixture
def mock_jira_search_empty():
    return load_fixture('jira_search_empty.json')


@pytest.fixture
def mock_jira_work_items():
    return load_issue_fixtures('jira_work_items')


@pytest.fixture
def mock_jira_search_with_results(mock_jira_work_items):
    return {
        'issues': mock_jira_work_items['issues'],
        '_search_page': load_fixture('jira_search_with_results.json'),
    }


@pytest.fixture
def mock_jira_parent_candidates(mock_jira_work_items):
    eng_2 = next(issue for issue in mock_jira_work_items['issues'] if issue['key'] == 'ENG-2')
    return {
        'issues': [eng_2],
        '_search_page': load_fixture('jira_parent_candidates.json'),
    }


@pytest.fixture
def mock_jira_projects():
    return load_fixture('jira_projects.json')


@pytest.fixture
def mock_jira_issue_types():
    return load_fixture('jira_engineering_issue_types.json')


@pytest.fixture
def mock_jira_support_issue_types():
    return load_fixture('jira_support_issue_types.json')


@pytest.fixture
def mock_jira_statuses():
    return load_fixture('jira_engineering_statuses.json')


@pytest.fixture
def mock_jira_support_statuses():
    return load_fixture('jira_support_statuses.json')


@pytest.fixture
def mock_jira_users():
    return load_fixture('jira_users.json')


@pytest.fixture
def mock_jira_work_item_link_types():
    return load_fixture('jira_work_item_link_types.json')


@pytest.fixture
def mock_jira_configuration():
    return load_fixture('jira_configuration.json')


@pytest.fixture
def mock_jira_engineering_agile_boards():
    return load_fixture('jira_engineering_agile_boards.json')


@pytest.fixture
def mock_jira_engineering_agile_sprints():
    return load_fixture('jira_engineering_agile_sprints.json')


# Helper fixtures for common mock patterns
@pytest.fixture
def mock_transitions_data():
    return load_fixture('jira_engineering_transitions.json')


@pytest.fixture
def mock_support_transitions_data():
    return load_fixture('jira_support_transitions.json')


@pytest.fixture
def mock_project_issue_types():
    return load_fixture('jira_engineering_project_issue_types.json')


@pytest.fixture
def mock_support_createmeta_fields():
    return load_fixture('jira_support_createmeta_fields.json')


@pytest.fixture
def mock_engineering_createmeta_fields():
    return load_fixture('jira_engineering_createmeta_fields.json')


@pytest.fixture
def mock_jira_worklog_empty():
    return load_fixture('jira_worklog_empty.json')


@pytest.fixture
def mock_jira_priorities():
    return load_fixture('jira_priorities.json')


@pytest.fixture
def mock_jira_new_attachment():
    return load_fixture('jira_new_attachment.json')


@pytest.fixture
def staged_upload_file(tmp_path: Path) -> Path:
    file_path = tmp_path / 'clipboard-upload.png'
    file_path.write_bytes(b'png')
    return file_path


@pytest.fixture
def mock_attachment_upload(mock_jira_new_attachment):
    def _mock(work_item_key: str, filename: str = 'clipboard-upload.png'):
        attachment = copy.deepcopy(mock_jira_new_attachment)
        attachment['filename'] = filename
        attachment['mimeType'] = 'image/png'
        attachment['size'] = 3
        return respx.post(
            f'https://example.atlassian.acme.net/rest/api/3/issue/{work_item_key}/attachments'
        ).mock(return_value=Response(200, json=[attachment]))

    return _mock


@pytest.fixture
def mock_jira_new_worklog():
    return load_fixture('jira_new_worklog.json')


@pytest.fixture
def mock_jira_initial_comment():
    return load_fixture('jira_initial_comment.json')


@pytest.fixture
def mock_jira_new_comment():
    return load_fixture('jira_new_comment.json')


@pytest.fixture
def mock_jira_engineering_transitions():
    return load_fixture('jira_engineering_transitions.json')


@pytest.fixture
def mock_jira_fields():
    return load_fixture('jira_fields.json')


@pytest.fixture
def mock_jira_fields_search():
    return load_fixture('jira_fields_search.json')


@pytest.fixture
async def mock_jira_api_sync(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_empty,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_support_issue_types,
    mock_jira_statuses,
    mock_jira_support_statuses,
    mock_support_transitions_data,
    mock_jira_configuration,
    mock_support_createmeta_fields,
    mock_jira_users,
):
    async with respx.mock:
        setup_common_mocks(
            mock_jira_server_info,
            mock_jira_myself,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_statuses,
            mock_jira_support_issue_types,
            mock_jira_support_statuses,
            mock_support_transitions_data,
            mock_support_createmeta_fields,
        )
        mock_search_empty(mock_jira_search_empty)
        mock_approximate_count_empty()
        mock_configuration_endpoint(mock_jira_configuration)

        project_key = mock_jira_projects['values'][0]['key']
        mock_project_endpoint(
            project_key,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_support_issue_types,
        )
        mock_assignable_users(mock_jira_users)
        mock_project_statuses(
            project_key,
            mock_jira_statuses,
            mock_jira_issue_types,
            mock_jira_support_statuses,
            mock_jira_support_issue_types,
        )

        yield


@pytest.fixture
async def mock_jira_api_with_attachment_upload(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_issue_types,
    mock_jira_support_issue_types,
    mock_jira_statuses,
    mock_jira_support_statuses,
    mock_transitions_data,
    mock_project_issue_types,
    mock_engineering_createmeta_fields,
    mock_support_transitions_data,
    mock_support_createmeta_fields,
    mock_jira_new_attachment,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
):
    async with respx.mock:
        setup_common_mocks(
            mock_jira_server_info,
            mock_jira_myself,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_statuses,
            mock_jira_support_issue_types,
            mock_jira_support_statuses,
            mock_support_transitions_data,
            mock_support_createmeta_fields,
        )
        mock_search_with_results(mock_jira_search_with_results)
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                if issue_key == 'ENG-3':
                    initial_work_item = copy.deepcopy(issue)
                    updated_work_item = copy.deepcopy(issue)

                    new_attachment = mock_jira_new_attachment

                    updated_work_item['fields']['attachment'].append(new_attachment)

                    # Mock POST /issue/ENG-3/attachments
                    respx.post(
                        'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/attachments'
                    ).mock(return_value=Response(200, json=[new_attachment]))

                    # Mock GET /issue/ENG-3 with side_effect for state changes
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                    ).mock(
                        side_effect=[
                            Response(200, json=initial_work_item),  # Before upload: 1 attachment
                            Response(200, json=updated_work_item),  # After upload: 2 attachments
                        ]
                    )
                else:
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                    ).mock(return_value=Response(200, json=issue))
                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}/remotelink.*'
                ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        mock_project_endpoint(project_key, mock_jira_projects, mock_project_issue_types)

        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_issue_link_deletion(
    mock_jira_server_info,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_project_issue_types,
    mock_engineering_createmeta_fields,
    mock_jira_priorities,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
):
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_search_with_results(mock_jira_search_with_results)
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Mock projects endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/project').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock users endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/users').mock(
            return_value=Response(200, json=mock_jira_users)
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        # Mock DELETE issue link endpoint (returns 204 No Content)
        respx.delete('https://example.atlassian.acme.net/rest/api/3/issueLink/10001').mock(
            return_value=Response(204)
        )

        initial_work_item = copy.deepcopy(
            next(
                issue
                for issue in mock_jira_search_with_results['issues']
                if issue['key'] == 'ENG-3'
            )
        )
        updated_work_item = copy.deepcopy(initial_work_item)

        updated_work_item['fields']['issuelinks'] = [
            link for link in updated_work_item['fields']['issuelinks'] if link['id'] != '10001'
        ]

        # Mock GET /issue/ENG-3 with side_effect for state changes
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-3(?:\?|$)'
        ).mock(
            side_effect=[
                Response(200, json=initial_work_item),  # Initial state: 2 links
                Response(200, json=updated_work_item),  # After deletion: 1 link
            ]
        )

        # Mock GET work item endpoint for ENG-2 (related work item)
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-2(?:\?|$)'
        ).mock(
            return_value=Response(
                200,
                json=next(
                    issue
                    for issue in mock_jira_search_with_results['issues']
                    if issue['key'] == 'ENG-2'
                ),
            )
        )

        # Mock other required endpoints
        remote_links_19539 = initial_work_item.get('fields', {}).get('remotelink', [])
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/remotelink').mock(
            return_value=Response(200, json=remote_links_19539)
        )

        mock_empty_comments('ENG-3')

        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/worklog').mock(
            return_value=Response(200, json=build_worklogs_page([]))
        )

        # Mock transitions endpoint for ENG-3
        mock_empty_transitions('ENG-3')

        # Extract remote links for ENG-2
        remote_links_19540 = (
            next(
                issue
                for issue in mock_jira_search_with_results['issues']
                if issue['key'] == 'ENG-2'
            )
            .get('fields', {})
            .get('remotelink', [])
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-2/remotelink').mock(
            return_value=Response(200, json=remote_links_19540)
        )

        mock_empty_comments('ENG-2')

        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-2').mock(
            return_value=Response(
                200,
                json=next(
                    issue
                    for issue in mock_jira_search_with_results['issues']
                    if issue['key'] == 'ENG-2'
                ),
            )
        )

        # Mock priority endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/priority').mock(
            return_value=Response(200, json=mock_jira_priorities)
        )

        # Mock issue types endpoint for project
        respx.get('https://example.atlassian.acme.net/rest/api/3/project/ENG/statuses').mock(
            return_value=Response(
                200,
                json=[
                    {
                        'id': '10001',
                        'name': 'Task',
                        'self': 'https://example.atlassian.acme.net/rest/api/3/issuetype/10001',
                        'subtask': False,
                        'statuses': [],
                    },
                    {
                        'id': '10002',
                        'name': 'Sub-task',
                        'self': 'https://example.atlassian.acme.net/rest/api/3/issuetype/10002',
                        'subtask': True,
                        'statuses': [],
                    },
                ],
            )
        )

        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/issuetype/project?projectId=10000'
        ).mock(
            return_value=Response(
                200,
                json=mock_project_issue_types,
            )
        )

        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        yield


@pytest.fixture
async def mock_jira_api_with_attachment_deletion(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_transitions_data,
    mock_project_issue_types,
    mock_engineering_createmeta_fields,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock DELETE attachment endpoint
        respx.delete('https://example.atlassian.acme.net/rest/api/3/attachment/66811').mock(
            return_value=Response(204)
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                if issue_key == 'ENG-3':
                    issue_with_attachment = copy.deepcopy(issue)

                    issue_without_attachment = copy.deepcopy(issue)
                    issue_without_attachment['fields']['attachment'] = []

                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?|$).*'
                    ).mock(
                        side_effect=[
                            Response(200, json=issue_with_attachment),
                            Response(200, json=issue_without_attachment),
                        ]
                    )
                else:
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                    ).mock(return_value=Response(200, json=issue))

                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}/remotelink.*'
                ).mock(return_value=Response(200, json=remote_links))

                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        mock_project_endpoint(project_key, mock_jira_projects, mock_project_issue_types)

        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_web_link_deletion(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_transitions_data,
    mock_project_issue_types,
    mock_engineering_createmeta_fields,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock DELETE remote link endpoint
        respx.delete(
            'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/remotelink/10050'
        ).mock(return_value=Response(204))

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                ).mock(return_value=Response(200, json=issue))

                if issue_key == 'ENG-3':
                    import copy

                    remote_links = issue.get('fields', {}).get('remotelink', [])

                    # Initial state: 6 remote links
                    initial_remote_links = copy.deepcopy(remote_links)

                    # Updated state: 5 remote links (remove the first one with ID 10050)
                    updated_remote_links = copy.deepcopy(remote_links)
                    updated_remote_links = [
                        link for link in updated_remote_links if link['id'] != 10050
                    ]

                    # Mock remotelink endpoint with side_effect for state changes
                    respx.get(
                        f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                    ).mock(
                        side_effect=[
                            Response(200, json=initial_remote_links),
                            Response(200, json=updated_remote_links),
                        ]
                    )
                else:
                    # Mock remote links endpoint for other work items
                    remote_links = issue.get('fields', {}).get('remotelink', [])
                    respx.get(
                        f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                    ).mock(return_value=Response(200, json=remote_links))

                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        mock_project_endpoint(project_key, mock_jira_projects, mock_project_issue_types)

        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_comment_deletion(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_transitions_data,
    mock_project_issue_types,
    mock_engineering_createmeta_fields,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock DELETE comment endpoint
        respx.delete(
            'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/comment/231668'
        ).mock(return_value=Response(204))

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                ).mock(return_value=Response(200, json=issue))

                if issue_key == 'ENG-3':
                    comments_data = issue.get('fields', {}).get('comment', {})
                    comments_list = comments_data.get('comments', [])

                    # Updated state: 0 comments (after deletion)
                    updated_comments = []

                    # Mock GET comments endpoint with side_effect for state changes.
                    # The widget fetches comments on initial load, then refetches after deletion.
                    respx.get(
                        f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/comment'
                    ).mock(
                        side_effect=[
                            Response(200, json=build_comments_page(issue_key, comments_list)),
                            Response(200, json=build_comments_page(issue_key, updated_comments)),
                            Response(200, json=build_comments_page(issue_key, updated_comments)),
                        ]
                    )
                else:
                    # Mock comments endpoint for other work items
                    comments_data = issue.get('fields', {}).get('comment', {})
                    comments_list = comments_data.get('comments', [])
                    respx.get(
                        f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/comment'
                    ).mock(
                        return_value=Response(
                            200, json=build_comments_page(issue_key, comments_list)
                        )
                    )

                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))

                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.acme.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json=build_project_detail(
                    mock_jira_projects['values'][0], mock_project_issue_types
                ),
            )
        )

        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_worklog_deletion(
    mock_jira_worklog,
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_transitions_data,
    mock_project_issue_types,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock DELETE worklog endpoint
        respx.delete(
            'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/worklog/10001'
        ).mock(return_value=Response(204))

        # Initial state has 2 worklogs (from fixture)
        initial_worklogs = copy.deepcopy(mock_jira_worklog)

        # Updated state: 1 worklog (remove the first one with ID 10001)
        updated_worklogs = copy.deepcopy(mock_jira_worklog)
        updated_worklogs['worklogs'] = [
            w for w in updated_worklogs['worklogs'] if w['id'] != '10001'
        ]
        updated_worklogs['total'] = len(updated_worklogs['worklogs'])

        # Mock GET worklogs endpoint with side_effect for multiple calls
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/worklog').mock(
            side_effect=[
                Response(200, json=initial_worklogs),
                Response(200, json=updated_worklogs),
            ]
        )

        # Mock all issues in the search results with basic data
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue['key']
            respx.get(
                url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
            ).mock(return_value=Response(200, json=issue))

            # Mock transitions endpoint for each issue
            respx.get(
                f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
            ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.acme.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json=build_project_detail(
                    mock_jira_projects['values'][0], mock_project_issue_types
                ),
            )
        )

        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=[])
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_worklog_creation(
    mock_jira_worklog,
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_project_issue_types,
    mock_jira_new_worklog,
    mock_engineering_createmeta_fields,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Create updated worklog response with new worklog
        # Initial state has 2 worklogs (from fixture)
        initial_worklogs = mock_jira_worklog.copy()

        new_worklog = mock_jira_new_worklog

        updated_worklogs = {
            'maxResults': 20,
            'startAt': 0,
            'total': 3,
            'worklogs': initial_worklogs['worklogs'] + [new_worklog],
        }

        # Mock GET worklogs endpoint with side_effect for multiple calls
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/worklog').mock(
            side_effect=[
                Response(200, json=initial_worklogs),
                Response(200, json=updated_worklogs),
            ]
        )

        # Mock POST worklog endpoint
        respx.post('https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/worklog').mock(
            return_value=Response(201, json=new_worklog)
        )

        # Mock all issues in the search results with basic data
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue['key']
            respx.get(
                url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
            ).mock(return_value=Response(200, json=issue))

            # Mock transitions endpoint for each issue
            if issue_key != 'ENG-3':
                transitions_data = build_transitions_payload(
                    [
                        {
                            'id': '11',
                            'name': 'To Do',
                            'to': {
                                'id': '10000',
                                'name': 'To Do',
                                'description': 'Work that needs to be done',
                                'statusCategory': {
                                    'key': 'new',
                                    'colorName': 'blue-gray',
                                },
                            },
                        },
                        {
                            'id': '21',
                            'name': 'In Progress',
                            'to': {
                                'id': '10001',
                                'name': 'In Progress',
                                'description': 'Work is being actively worked on',
                                'statusCategory': {
                                    'key': 'indeterminate',
                                    'colorName': 'yellow',
                                },
                            },
                        },
                        {
                            'id': '31',
                            'name': 'Done',
                            'to': {
                                'id': '10002',
                                'name': 'Done',
                                'description': 'Work has been completed',
                                'statusCategory': {'key': 'done', 'colorName': 'green'},
                            },
                        },
                    ]
                )
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        mock_projects_search(mock_jira_projects)
        mock_project_endpoint('ENG', mock_jira_projects, mock_project_issue_types)
        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_search_results(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_parent_candidates,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_engineering_transitions,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
    mock_jira_fields,
    mock_jira_fields_search,
    mock_project_issue_types,
    mock_engineering_createmeta_fields,
):
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)
        mock_fields_endpoints(mock_jira_fields, mock_jira_fields_search)

        # Mock Agile API endpoints for sprints (needed since sprint setup runs unconditionally
        # when enable_sprint_selection=True)
        mock_agile_boards(mock_jira_engineering_agile_boards, project_key='ENG')
        mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=1)
        mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=2)

        subtasks_by_parent: dict[str, list[dict]] = {}
        for issue in mock_jira_search_with_results['issues']:
            parent_key = (issue.get('fields', {}).get('parent') or {}).get('key')
            if parent_key:
                subtasks_by_parent.setdefault(parent_key, []).append(issue)

        # Custom handler for JQL search to return subtasks when querying by parent
        def search_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')

            if jql.startswith('parent='):
                parent_key = jql.removeprefix('parent=').strip()
                subtasks_for_jql = subtasks_by_parent.get(parent_key, [])
                return Response(200, json=build_search_results_page(subtasks_for_jql))

            if 'issuetype in (10000)' in jql and 'key != ENG-3' in jql:
                return Response(200, json=get_search_results_payload(mock_jira_parent_candidates))

            # Return main search results for other queries
            return Response(200, json=get_search_results_payload(mock_jira_search_with_results))

        # Mock search endpoint with custom handler
        respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(
            side_effect=search_handler
        )

        # Mock approximate count with custom handler
        def count_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')
            if jql.startswith('parent='):
                parent_key = jql.removeprefix('parent=').strip()
                subtasks_for_jql = subtasks_by_parent.get(parent_key, [])
                return Response(200, json=build_count_results(len(subtasks_for_jql)))
            return Response(
                200, json=build_count_results(len(mock_jira_search_with_results.get('issues', [])))
            )

        respx.post('https://example.atlassian.acme.net/rest/api/3/search/approximate-count').mock(
            side_effect=count_handler
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                ).mock(return_value=Response(200, json=issue))
                comments = issue.get('fields', {}).get('comment', {}).get('comments', [])
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}/comment.*'
                ).mock(return_value=Response(200, json=build_comments_page(issue_key, comments)))
                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint with available transitions
                transitions_data = mock_jira_engineering_transitions
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        eng_2 = get_issue_by_key(mock_jira_search_with_results['issues'], 'ENG-2')
        eng_9 = copy.deepcopy(eng_2)
        eng_9['id'] = '94279'
        eng_9['key'] = 'ENG-9'
        eng_9['self'] = 'https://example.atlassian.acme.net/rest/api/3/issue/94279'
        eng_9['fields']['summary'] = 'Second parent epic for parent picker tests'
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-9(?:\?.*)?$'
        ).mock(return_value=Response(200, json=eng_9))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint with issue types (for creating subtasks)
        project_key = mock_jira_projects['values'][0]['key']
        mock_project_endpoint(project_key, mock_jira_projects, mock_project_issue_types)

        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=[])
        )

        # Mock assignable users endpoint (returns users for work item assignable queries)
        respx.get('https://example.atlassian.acme.net/rest/api/3/user/assignable/search').mock(
            return_value=Response(200, json=mock_jira_users)
        )

        # Mock user assignable multi project search endpoint (for creating subtasks)
        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint (for creating subtasks - issue type 10002)
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
def mock_user_info(mock_jira_myself):
    from gojeera.models import JiraMyselfInfo

    return JiraMyselfInfo(
        account_type=mock_jira_myself['accountType'],
        account_id=mock_jira_myself['accountId'],
        active=mock_jira_myself['active'],
        display_name=mock_jira_myself['displayName'],
        email=mock_jira_myself.get('emailAddress'),
    )


@pytest.fixture
def mock_jira_worklog():
    fixture_path = Path(__file__).parent / 'fixtures' / 'jira_worklog_response.json'
    with fixture_path.open() as f:
        payload = json.load(f)

    worklogs = payload['worklogs']
    if len(worklogs) >= 5:
        payload['total'] = len(worklogs)
        payload['maxResults'] = max(payload.get('maxResults', 0), len(worklogs))
        return payload

    extra_entries = [
        (
            '10003',
            '2026-02-07T14:00:00.000+0000',
            '2026-02-07T17:00:00.000+0000',
            '3h',
            10800,
            'New worklog entry for testing.',
        ),
        (
            '10004',
            '2026-02-08T09:30:00.000+0000',
            '2026-02-08T10:15:00.000+0000',
            '45m',
            2700,
            'Reviewed follow-up changes and verified edge cases.',
        ),
        (
            '10005',
            '2026-02-09T11:00:00.000+0000',
            '2026-02-09T12:30:00.000+0000',
            '1h 30m',
            5400,
            'Documented the rollout steps and updated notes.',
        ),
    ]

    template = copy.deepcopy(worklogs[-1])
    for worklog_id, started, updated, time_spent, seconds, text in extra_entries:
        cloned = copy.deepcopy(template)
        cloned['id'] = worklog_id
        cloned['self'] = (
            f'https://example.atlassian.acme.net/rest/api/3/issue/94264/worklog/{worklog_id}'
        )
        cloned['started'] = started
        cloned['created'] = updated
        cloned['updated'] = updated
        cloned['timeSpent'] = time_spent
        cloned['timeSpentSeconds'] = seconds
        cloned['comment']['content'][0]['content'][0]['text'] = text
        worklogs.append(cloned)

    payload['total'] = len(worklogs)
    payload['maxResults'] = max(payload.get('maxResults', 0), len(worklogs))
    return payload


@pytest.fixture
async def mock_jira_api_with_new_work_item(
    mock_jira_server_info,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_engineering_createmeta_fields,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_users,
):
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)
        mock_projects_search(mock_jira_projects)
        mock_project_endpoint('ENG', mock_jira_projects, mock_jira_issue_types)

        # Mock users assignable to project (correct endpoint)
        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint (for specific project and issue type)
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock issue types
        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock search endpoint (empty results for initial state)
        mock_search_empty_results()

        # Mock search for ENG-8 (newly created work item)
        # Use the full work item fixture so follow-up edit flows have editmeta available.
        created_work_item = load_fixture('jira_work_items/ENG-8.json')
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-8(?:\?.*)?$'
        ).mock(
            return_value=Response(
                200,
                json=created_work_item,
            )
        )

        # Mock approximate count endpoint
        mock_approximate_count_empty()

        # Mock POST /issue endpoint (create work item)
        respx.post('https://example.atlassian.acme.net/rest/api/3/issue').mock(
            return_value=Response(
                201,
                json=build_created_issue('10000', 'ENG-8'),
            )
        )

        yield


"""Fixture for clone work item tests - to be added to conftest.py"""

# Add this fixture to conftest.py after mock_jira_api_with_new_work_item


@pytest.fixture
async def mock_jira_api_with_clone_work_item(
    mock_jira_server_info,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_support_issue_types,
    mock_jira_statuses,
    mock_jira_support_statuses,
    mock_support_transitions_data,
    mock_support_createmeta_fields,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_users,
):
    async with respx.mock:
        setup_common_mocks(
            mock_jira_server_info,
            mock_jira_myself,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_statuses,
            mock_jira_support_issue_types,
            mock_jira_support_statuses,
            mock_support_transitions_data,
            mock_support_createmeta_fields,
        )
        mock_assignable_users(mock_jira_users)
        mock_project_endpoint('ENG', mock_jira_projects, mock_jira_issue_types)

        original_work_item = copy.deepcopy(
            next(
                issue
                for issue in mock_jira_search_with_results['issues']
                if issue['key'] == 'ENG-3'
            )
        )
        cloned_work_item = copy.deepcopy(
            next(
                issue
                for issue in mock_jira_search_with_results['issues']
                if issue['key'] == 'ENG-8'
            )
        )

        original_work_item['fields']['description'] = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'paragraph',
                    'content': [{'type': 'text', 'text': 'Original description'}],
                }
            ],
        }
        cloned_work_item['fields']['summary'] = (
            'CLONE - Update documentation for merge approval process'
        )
        cloned_work_item['fields']['description'] = original_work_item['fields']['description']

        # Mock GET for original work item ENG-3 (for clone operation)
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-3.*'
        ).mock(return_value=Response(200, json=original_work_item))

        cloned_work_item['key'] = 'ENG-9'
        cloned_work_item['self'] = 'https://example.atlassian.acme.net/rest/api/3/issue/10002'

        # Mock search for ENG-9 (cloned work item with correct summary)
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-9.*'
        ).mock(return_value=Response(200, json=cloned_work_item))

        def clone_search_handler(request):
            body = json.loads(request.content)
            jql = str(body.get('jql', '')).strip().lower()

            if 'key = eng-9' in jql or 'key=eng-9' in jql:
                return Response(200, json=build_search_results_page([cloned_work_item]))

            return Response(200, json=load_fixture('jira_search_empty.json'))

        respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(
            side_effect=clone_search_handler
        )

        def clone_count_handler(request):
            body = json.loads(request.content)
            jql = str(body.get('jql', '')).strip().lower()
            if 'key = eng-9' in jql or 'key=eng-9' in jql:
                return Response(200, json=build_count_results(1))
            return Response(200, json=build_count_results(0))

        respx.post('https://example.atlassian.acme.net/rest/api/3/search/approximate-count').mock(
            side_effect=clone_count_handler
        )

        # Mock POST /issue endpoint (create cloned work item)
        respx.post('https://example.atlassian.acme.net/rest/api/3/issue').mock(
            return_value=Response(
                201,
                json=build_created_issue('10002', 'ENG-9'),
            )
        )

        yield


@pytest.fixture
async def mock_jira_api_with_related_work_item_link(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_issue_types,
    mock_jira_engineering_transitions,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
    mock_engineering_createmeta_fields,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock Agile API endpoints used by sprint picker workers
        mock_agile_boards(mock_jira_engineering_agile_boards, project_key='ENG')
        mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=1)
        mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=2)
        # Fallback matchers for agile requests where query params differ in order/shape
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/agile/1\.0/board\?.*'
        ).mock(return_value=Response(200, json=mock_jira_engineering_agile_boards))
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/agile/1\.0/board/1/sprint\?.*'
        ).mock(return_value=Response(200, json=mock_jira_engineering_agile_sprints))
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/agile/1\.0/board/2/sprint\?.*'
        ).mock(return_value=Response(200, json=mock_jira_engineering_agile_sprints))

        # Mock GET work item endpoint with updated issuelinks field for ENG-3
        # This MUST be registered BEFORE the general loop below to take priority
        # The application uses 'issuelinks' as the field name in the query
        eng_3_with_new_link = get_issue_by_key(mock_jira_search_with_results['issues'], 'ENG-3')
        eng_8_issue = get_issue_by_key(mock_jira_search_with_results['issues'], 'ENG-8')
        blocks_type = copy.deepcopy(mock_jira_work_item_link_types['issueLinkTypes'][0])
        eng_3_with_new_link['fields']['issuelinks'].append(
            {
                'id': '10003',
                'type': blocks_type,
                'outwardIssue': {
                    'id': eng_8_issue['id'],
                    'key': eng_8_issue['key'],
                    'self': eng_8_issue['self'],
                    'fields': {
                        'summary': copy.deepcopy(eng_8_issue['fields']['summary']),
                        'status': copy.deepcopy(eng_8_issue['fields']['status']),
                        'priority': copy.deepcopy(eng_8_issue['fields']['priority']),
                        'issuetype': copy.deepcopy(eng_8_issue['fields']['issuetype']),
                        'assignee': copy.deepcopy(eng_8_issue['fields']['assignee']),
                    },
                },
                'self': 'https://example.atlassian.acme.net/rest/api/3/issueLink/10003',
            }
        )
        respx.get(
            url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-3.*issuelinks'
        ).mock(
            return_value=Response(
                200,
                json=build_issue_response(eng_3_with_new_link, ['issuelinks']),
            )
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                ).mock(return_value=Response(200, json=issue))
                # Mock remote links endpoint
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint
                transitions_data = mock_jira_engineering_transitions
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        # Mock projects, issue types, and statuses
        mock_projects_search(mock_jira_projects)

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.acme.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json=build_project_detail(
                    mock_jira_projects['values'][0],
                    [
                        issue_type
                        for issue_type in mock_jira_issue_types
                        if issue_type['id'] in {'10008', '10002'}
                    ],
                ),
            )
        )

        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock user assignable multi project search endpoint
        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        # Mock work item link creation endpoint
        # This endpoint returns nothing (201 Created with empty body)
        respx.post('https://example.atlassian.acme.net/rest/api/3/issueLink').mock(
            return_value=Response(201)
        )

        # Mock the newly linked work item details (used by follow-up refresh flows)
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-8').mock(
            return_value=Response(
                200,
                json=build_issue_response(eng_8_issue),
            )
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-8/remotelink').mock(
            return_value=Response(200, json=[])
        )

        yield


@pytest.fixture
async def mock_jira_api_with_web_link_creation(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_issue_types,
    mock_jira_work_item_link_types,
    mock_jira_engineering_transitions,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
    mock_engineering_createmeta_fields,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock GET remote links endpoint for ENG-3
        # Use side_effect to return different values on first and subsequent calls:
        # - First call (initial load): 6 links (from fixture)
        # - Second call (after creation): 7 links (6 + 1 new)

        # Get the remote links from the fixture for ENG-3
        example_issue = next(
            (
                issue
                for issue in mock_jira_search_with_results.get('issues', [])
                if issue['key'] == 'ENG-3'
            ),
            None,
        )

        if example_issue:
            import copy

            # Data for initial state (6 links from fixture)
            initial_links = copy.deepcopy(example_issue.get('fields', {}).get('remotelink', []))

            # Find the next available ID for the new link
            existing_ids = [link.get('id', 0) for link in initial_links]
            next_id = max(existing_ids) + 1 if existing_ids else 10056

            # Data for updated state (7 links = 6 from fixture + 1 new)
            updated_links = initial_links + [
                {
                    'id': next_id,
                    'self': f'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/remotelink/{next_id}',
                    'object': {
                        'url': 'https://docs.example.com/api',
                        'title': 'API Documentation',
                    },
                },
            ]

            # Use side_effect to return different responses on subsequent calls
            respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/remotelink').mock(
                side_effect=[
                    Response(200, json=initial_links),
                    Response(200, json=updated_links),
                ]
            )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                # Skip ENG-3 as we've already mocked remotelink above
                if issue_key != 'ENG-3':
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                    ).mock(return_value=Response(200, json=issue))
                    # Mock remote links endpoint
                    remote_links = issue.get('fields', {}).get('remotelink', [])
                    respx.get(
                        f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                    ).mock(return_value=Response(200, json=remote_links))
                else:
                    # For ENG-3, mock the GET issue endpoint
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                    ).mock(return_value=Response(200, json=issue))
                # Mock status transitions endpoint
                transitions_data = mock_jira_engineering_transitions
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        # Mock projects, issue types, and statuses
        mock_projects_search(mock_jira_projects)

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.acme.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json=build_project_detail(
                    mock_jira_projects['values'][0],
                    [
                        issue_type
                        for issue_type in mock_jira_issue_types
                        if issue_type['id'] in {'10008', '10002'}
                    ],
                ),
            )
        )

        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoints
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock user assignable multi project search endpoint
        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        # Mock web link creation endpoint
        respx.post('https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/remotelink').mock(
            return_value=Response(200, json=build_remote_issue_link_identifies('ENG-3', '10051'))
        )

        yield


@pytest.fixture
async def mock_jira_api_with_comment_creation(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_project_issue_types,
    mock_jira_initial_comment,
    mock_jira_new_comment,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
    mock_engineering_createmeta_fields,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # TODO: (vkhitrin) revisit this comment.
        # Mock GET comments endpoint for ENG-3
        # This mock must be registered BEFORE the general loop
        # Use side_effect to return different values on first and subsequent calls:
        # - First call (initial load): 1 comment (from fixture)
        # - Second call (after creation): 2 comments (1 existing + 1 new)

        # Data for initial state (1 comment from fixture)
        # This must match the actual comment from jira_search_with_results.json for ENG-3
        initial_comment = mock_jira_initial_comment

        new_comment = mock_jira_new_comment

        current_comments = [copy.deepcopy(initial_comment)]

        def get_comments_response(request):
            return Response(
                200,
                json=build_comments_page(
                    'ENG-3',
                    current_comments,
                ),
            )

        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/comment',
        ).mock(side_effect=get_comments_response)

        # Mock POST comment creation endpoint
        def create_comment_response(request):
            created_comment = copy.deepcopy(new_comment)
            payload = json.loads(request.content.decode('utf-8'))
            if body := payload.get('body'):
                created_comment['body'] = body
            current_comments[:] = [created_comment, *current_comments]
            return Response(201, json=created_comment)

        comment_create_route = respx.post(
            'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/comment'
        ).mock(side_effect=create_comment_response)

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                if issue_key != 'ENG-3':
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                    ).mock(return_value=Response(200, json=issue))
                    # Mock comments endpoint with paginated structure
                    comments = issue.get('fields', {}).get('comment', {}).get('comments', [])
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}/comment.*'
                    ).mock(
                        return_value=Response(200, json=build_comments_page(issue_key, comments))
                    )
                else:
                    respx.get(
                        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                    ).mock(return_value=Response(200, json=issue))
                    # Mock remote links endpoint for ENG-3
                    remote_links = issue.get('fields', {}).get('remotelink', [])
                    respx.get(
                        f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                    ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint
                transitions_data = build_transitions_payload(
                    [
                        {
                            'id': '11',
                            'name': 'To Do',
                            'to': {
                                'id': '10000',
                                'name': 'To Do',
                                'description': 'Work waiting to be started',
                                'statusCategory': {'key': 'new', 'colorName': 'blue-gray'},
                            },
                        },
                        {
                            'id': '21',
                            'name': 'In Progress',
                            'to': {
                                'id': '10001',
                                'name': 'In Progress',
                                'description': 'Work is being actively worked on',
                                'statusCategory': {
                                    'key': 'indeterminate',
                                    'colorName': 'yellow',
                                },
                            },
                        },
                        {
                            'id': '31',
                            'name': 'Done',
                            'to': {
                                'id': '10002',
                                'name': 'Done',
                                'description': 'Work has been completed',
                                'statusCategory': {'key': 'done', 'colorName': 'green'},
                            },
                        },
                    ]
                )
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        # Mock projects endpoint
        mock_projects_search(mock_jira_projects)
        mock_project_endpoint('ENG', mock_jira_projects, mock_project_issue_types)
        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoints
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock user assignable multi project search endpoint
        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield {'comment_create_route': comment_create_route}


@pytest.fixture
async def mock_jira_api_with_subtask_creation(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_project_issue_types,
    mock_jira_work_item_link_types,
    mock_jira_engineering_transitions,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
    mock_engineering_createmeta_fields,
):
    """Mock Jira API for subtask creation testing.

    Simulates creating a new subtask for ENG-4 via JQL search.
    Extracts existing subtasks from the parent issue's subtasks field.
    """
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)
        mock_agile_endpoints_for_example_project(
            mock_jira_engineering_agile_boards, mock_jira_engineering_agile_sprints
        )

        # Create new subtask that will be returned after creation
        new_subtask = get_issue_by_key(mock_jira_search_with_results['issues'], 'ENG-6')
        new_subtask['id'] = '94272'
        new_subtask['key'] = 'ENG-7'
        new_subtask['self'] = 'https://example.atlassian.acme.net/rest/api/3/issue/94272'
        new_subtask['fields']['summary'] = 'Test new subtask'

        # Extract existing subtasks from parent issue (ENG-4)
        parent_issue = next(
            (issue for issue in mock_jira_search_with_results['issues'] if issue['key'] == 'ENG-4'),
            None,
        )
        if not parent_issue:
            raise ValueError('ENG-4 not found in mock_jira_search_with_results')

        new_subtask['fields']['parent'] = {
            'key': 'ENG-4',
            'fields': {'summary': parent_issue['fields']['summary']},
        }

        # Get subtasks from parent issue's subtasks field and expand them to full issue format
        parent_subtasks = parent_issue['fields'].get('subtasks', [])
        initial_subtasks = []
        for subtask_summary in parent_subtasks:
            if subtask_summary['key'] == 'ENG-7':
                continue
            # Expand the minimal subtask info to full issue format for JQL search response
            full_subtask = build_issue_response(
                {
                    'id': subtask_summary['id'],
                    'key': subtask_summary['key'],
                    'self': subtask_summary['self'],
                    'fields': {
                        'summary': subtask_summary['fields']['summary'],
                        'status': subtask_summary['fields']['status'],
                        'priority': subtask_summary['fields']['priority'],
                        'issuetype': subtask_summary['fields']['issuetype'],
                        'assignee': subtask_summary['fields'].get('assignee'),
                        'parent': {
                            'key': 'ENG-4',
                            'fields': {'summary': parent_issue['fields']['summary']},
                        },
                    },
                }
            )
            initial_subtasks.append(full_subtask)

        # Create search responses with side effect for before/after creation
        initial_subtasks_response = build_search_results_page(initial_subtasks)
        after_create_subtasks_response = build_search_results_page(initial_subtasks + [new_subtask])

        # Custom handler to check for parent=ENG-4 JQL query
        search_call_count = [0]

        def search_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')

            # Return subtasks for parent search
            if 'parent=ENG-4' in jql:
                search_call_count[0] += 1
                if search_call_count[0] == 1:
                    return Response(200, json=initial_subtasks_response)
                else:
                    return Response(200, json=after_create_subtasks_response)

            # Return main search results for other queries
            return Response(200, json=get_search_results_payload(mock_jira_search_with_results))

        # Mock search endpoint with custom handler
        respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(
            side_effect=search_handler
        )

        # Mock approximate count
        def count_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')
            if 'parent=ENG-4' in jql:
                if search_call_count[0] <= 1:
                    return Response(200, json=build_count_results(len(initial_subtasks)))
                else:
                    return Response(200, json=build_count_results(len(initial_subtasks) + 1))
            return Response(
                200, json=build_count_results(len(mock_jira_search_with_results.get('issues', [])))
            )

        respx.post('https://example.atlassian.acme.net/rest/api/3/search/approximate-count').mock(
            side_effect=count_handler
        )

        # Mock POST /issue endpoint (for creating the subtask)
        respx.post('https://example.atlassian.acme.net/rest/api/3/issue').mock(
            return_value=Response(
                201,
                json=build_created_issue('94272', 'ENG-7'),
            )
        )

        # Mock GET for newly created subtask
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-7').mock(
            return_value=Response(200, json=new_subtask)
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-7/remotelink').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/issue/ENG-7/transitions').mock(
            return_value=Response(200, json=mock_jira_engineering_transitions)
        )

        # Mock get specific work items
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{issue_key}(?:\?.*)?$'
                ).mock(return_value=Response(200, json=issue))
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_jira_engineering_transitions))

        # Mock get individual subtasks
        for subtask in initial_subtasks:
            subtask_key = subtask.get('key')
            if subtask_key:
                respx.get(
                    url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{subtask_key}(?:\?.*)?$'
                ).mock(return_value=Response(200, json=subtask))
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{subtask_key}/remotelink'
                ).mock(return_value=Response(200, json=[]))
                respx.get(
                    f'https://example.atlassian.acme.net/rest/api/3/issue/{subtask_key}/transitions'
                ).mock(return_value=Response(200, json=mock_jira_engineering_transitions))

        # Mock projects endpoint
        mock_projects_search(mock_jira_projects)
        mock_project_endpoint('ENG', mock_jira_projects, mock_project_issue_types)

        # Mock issue types and statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=[])
        )

        # Mock assignable users endpoints
        mock_assignable_users(mock_jira_users)
        mock_assignable_users_single_project(mock_jira_users)

        # Mock create metadata endpoint (for Sub-task type)
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.acme.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_sprints(
    mock_jira_server_info,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_jira_myself,
    mock_jira_users,
    mock_jira_engineering_agile_boards,
    mock_jira_engineering_agile_sprints,
    mock_engineering_createmeta_fields,
):
    """Mock Jira API with sprint selection enabled."""
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)
        mock_projects_search(mock_jira_projects)
        mock_project_endpoint('ENG', mock_jira_projects, mock_jira_issue_types)

        # Mock users assignable to project
        respx.get(
            'https://example.atlassian.acme.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock Agile API endpoints for sprints
        mock_agile_boards(mock_jira_engineering_agile_boards, project_key='ENG')
        # Mock sprints for board 1
        mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=1)
        # Mock sprints for board 2 (same sprints for simplicity)
        mock_agile_sprints(mock_jira_engineering_agile_sprints, board_id=2)

        # Mock create metadata endpoint with sprint field
        mock_engineering_project_createmeta(mock_engineering_createmeta_fields)

        # Mock statuses
        respx.get('https://example.atlassian.acme.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock issue types
        respx.get('https://example.atlassian.acme.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock search endpoint (empty results for initial state)
        mock_search_empty_results()

        # Mock issue creation endpoint
        respx.post('https://example.atlassian.acme.net/rest/api/3/issue').mock(
            return_value=Response(
                201,
                json=build_created_issue('10001', 'ENG-8'),
            )
        )

        yield
