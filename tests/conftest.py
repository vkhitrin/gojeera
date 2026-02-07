import copy
import json
from pathlib import Path

from httpx import Response
from pydantic import SecretStr
import pytest
import respx

from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION, ApplicationConfiguration, JiraConfig


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
        api_username='testuser@example.com',
        api_token=SecretStr('test-token'),
        api_base_url='https://example.atlassian.net',
    )

    config = ApplicationConfiguration(
        jira=jira_config,
        custom_field_id_sprint=None,
        show_work_item_web_links=True,
        ignore_users_without_email=True,
        fetch_attachments_on_delete=True,
        fetch_comments_on_delete=True,
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
        enable_images_support=True,
        obfuscate_personal_info=False,
    )

    token = CONFIGURATION.set(config)

    yield config

    CONFIGURATION.reset(token)


def load_fixture(filename: str):
    fixture_path = Path(__file__).parent / 'fixtures' / filename
    with fixture_path.open() as f:
        return json.load(f)


# Helper functions for common mock patterns
def mock_server_info(mock_jira_server_info):
    respx.get('https://example.atlassian.net/rest/api/3/serverInfo').mock(
        return_value=Response(200, json=mock_jira_server_info)
    )


def mock_myself(mock_jira_myself):
    respx.get('https://example.atlassian.net/rest/api/3/myself').mock(
        return_value=Response(200, json=mock_jira_myself)
    )


def mock_search_empty(mock_jira_search_empty):
    respx.post('https://example.atlassian.net/rest/api/3/search/jql').mock(
        return_value=Response(200, json=mock_jira_search_empty)
    )


def mock_search_with_results(mock_jira_search_with_results):
    respx.post('https://example.atlassian.net/rest/api/3/search/jql').mock(
        return_value=Response(200, json=mock_jira_search_with_results)
    )


def mock_approximate_count_empty():
    respx.post('https://example.atlassian.net/rest/api/3/search/approximate-count').mock(
        return_value=Response(200, json={'count': 0})
    )


def mock_approximate_count(count):
    respx.post('https://example.atlassian.net/rest/api/3/search/approximate-count').mock(
        return_value=Response(200, json={'count': count})
    )


def mock_projects_search(mock_jira_projects):
    respx.get('https://example.atlassian.net/rest/api/3/project/search').mock(
        return_value=Response(200, json=mock_jira_projects)
    )


def mock_issue_types(mock_jira_issue_types):
    respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
        return_value=Response(200, json=mock_jira_issue_types)
    )


def mock_statuses(mock_jira_statuses):
    respx.get('https://example.atlassian.net/rest/api/3/status').mock(
        return_value=Response(200, json=mock_jira_statuses)
    )


def mock_jql_validation():
    respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
        return_value=Response(200, json={'valid': True, 'errors': []})
    )


def mock_configuration_endpoint(mock_jira_configuration):
    respx.get('https://example.atlassian.net/rest/api/3/configuration').mock(
        return_value=Response(200, json=mock_jira_configuration)
    )


def mock_assignable_users(mock_jira_users):
    respx.get('https://example.atlassian.net/rest/api/3/user/assignable/multiProjectSearch').mock(
        return_value=Response(200, json=mock_jira_users)
    )


def mock_assignable_users_single_project(mock_jira_users):
    respx.get('https://example.atlassian.net/rest/api/3/user/assignable/search').mock(
        return_value=Response(200, json=mock_jira_users)
    )


def mock_project_endpoint(project_key, mock_jira_projects, mock_jira_issue_types):
    respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
        return_value=Response(
            200,
            json={
                **mock_jira_projects['values'][0],
                'issueTypes': mock_jira_issue_types,
            },
        )
    )


def mock_project_statuses(project_key, mock_jira_statuses):
    respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}/statuses').mock(
        return_value=Response(
            200,
            json=[
                {
                    'id': '10001',
                    'name': 'Task',
                    'subtask': False,
                    'statuses': mock_jira_statuses,
                },
                {
                    'id': '10002',
                    'name': 'Sub-task',
                    'subtask': True,
                    'statuses': mock_jira_statuses,
                },
            ],
        )
    )


def mock_project_example_with_inline_issue_types(mock_jira_project_example_with_issue_types):
    respx.get('https://example.atlassian.net/rest/api/3/project/EXAMPLE').mock(
        return_value=Response(200, json=mock_jira_project_example_with_issue_types)
    )


def mock_project_example_with_fixture_issue_types(mock_jira_issue_types):
    respx.get('https://example.atlassian.net/rest/api/3/project/EXAMPLE').mock(
        return_value=Response(
            200,
            json={
                'id': '10446',
                'key': 'EXAMPLE',
                'name': 'Test Project',
                'issueTypes': mock_jira_issue_types,
            },
        )
    )


def setup_common_mocks(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_statuses,
):
    mock_server_info(mock_jira_server_info)
    mock_myself(mock_jira_myself)
    mock_projects_search(mock_jira_projects)
    mock_issue_types(mock_jira_issue_types)
    mock_statuses(mock_jira_statuses)
    mock_jql_validation()


@pytest.fixture
def mock_work_item_example_1234():
    return load_fixture('work_item_example_1234.json')


@pytest.fixture
def work_item_adf_description(mock_work_item_example_1234):
    return mock_work_item_example_1234['fields']['description']


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
def mock_jira_search_with_results():
    return load_fixture('jira_search_with_results.json')


@pytest.fixture
def mock_jira_projects():
    return load_fixture('jira_projects.json')


@pytest.fixture
def mock_jira_issue_types():
    return load_fixture('jira_issue_types.json')


@pytest.fixture
def mock_jira_statuses():
    return load_fixture('jira_statuses.json')


@pytest.fixture
def mock_jira_users():
    return load_fixture('jira_users.json')


@pytest.fixture
def mock_jira_work_item_link_types():
    return load_fixture('jira_work_item_link_types.json')


@pytest.fixture
def mock_jira_configuration():
    return load_fixture('jira_configuration.json')


# Helper fixtures for common mock patterns
@pytest.fixture
def mock_transitions_data():
    return load_fixture('jira_transitions.json')


@pytest.fixture
def mock_project_issue_types():
    return load_fixture('jira_project_issue_types.json')


@pytest.fixture
def mock_jira_worklog_empty():
    return load_fixture('jira_worklog_empty.json')


@pytest.fixture
def mock_jira_project_example_with_issue_types():
    return load_fixture('jira_project_example_with_issue_types.json')


@pytest.fixture
def mock_jira_priorities():
    return load_fixture('jira_priorities.json')


@pytest.fixture
def mock_jira_new_attachment():
    return load_fixture('jira_new_attachment.json')


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
def mock_jira_transitions():
    return load_fixture('jira_transitions.json')


@pytest.fixture
async def mock_jira_api(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_empty,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_statuses,
):
    async with respx.mock:
        setup_common_mocks(
            mock_jira_server_info,
            mock_jira_myself,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_statuses,
        )
        mock_search_empty(mock_jira_search_empty)
        mock_approximate_count_empty()

        yield


@pytest.fixture
async def mock_jira_api_sync(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_empty,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_jira_configuration,
    mock_jira_users,
):
    async with respx.mock:
        setup_common_mocks(
            mock_jira_server_info,
            mock_jira_myself,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_statuses,
        )
        mock_search_empty(mock_jira_search_empty)
        mock_approximate_count_empty()
        mock_configuration_endpoint(mock_jira_configuration)

        project_key = mock_jira_projects['values'][0]['key']
        mock_project_endpoint(project_key, mock_jira_projects, mock_jira_issue_types)
        mock_assignable_users(mock_jira_users)
        mock_project_statuses(project_key, mock_jira_statuses)

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
    mock_jira_statuses,
    mock_transitions_data,
    mock_project_issue_types,
    mock_jira_new_attachment,
):
    async with respx.mock:
        setup_common_mocks(
            mock_jira_server_info,
            mock_jira_myself,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_statuses,
        )
        mock_search_with_results(mock_jira_search_with_results)
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                if issue_key == 'EXAMPLE-19539':
                    initial_work_item = copy.deepcopy(issue)
                    updated_work_item = copy.deepcopy(issue)

                    new_attachment = mock_jira_new_attachment

                    updated_work_item['fields']['attachment'].append(new_attachment)

                    # Mock POST /issue/EXAMPLE-19539/attachments
                    respx.post(
                        'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/attachments'
                    ).mock(return_value=Response(200, json=[new_attachment]))

                    # Mock GET /issue/EXAMPLE-19539 with side_effect for state changes
                    respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                        side_effect=[
                            Response(200, json=initial_work_item),  # Before upload: 1 attachment
                            Response(200, json=updated_work_item),  # After upload: 2 attachments
                        ]
                    )
                else:
                    respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                        return_value=Response(200, json=issue)
                    )
                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': mock_project_issue_types,
                },
            )
        )

        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
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
    mock_jira_priorities,
):
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_search_with_results(mock_jira_search_with_results)
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock projects endpoint
        respx.get('https://example.atlassian.net/rest/api/3/project').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock users endpoint
        respx.get('https://example.atlassian.net/rest/api/3/users').mock(
            return_value=Response(200, json=mock_jira_users)
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        # Mock DELETE issue link endpoint (returns 204 No Content)
        respx.delete('https://example.atlassian.net/rest/api/3/issueLink/10001').mock(
            return_value=Response(204)
        )

        initial_work_item = copy.deepcopy(mock_jira_search_with_results['issues'][0])
        updated_work_item = copy.deepcopy(mock_jira_search_with_results['issues'][0])

        updated_work_item['fields']['issuelinks'] = [
            link for link in updated_work_item['fields']['issuelinks'] if link['id'] != '10001'
        ]

        # Mock GET /issue/EXAMPLE-19539 with side_effect for state changes
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/EXAMPLE-19539(?:\?|$)'
        ).mock(
            side_effect=[
                Response(200, json=initial_work_item),  # Initial state: 2 links
                Response(200, json=updated_work_item),  # After deletion: 1 link
            ]
        )

        # Mock GET work item endpoint for EXAMPLE-19540 (related work item)
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/EXAMPLE-19540(?:\?|$)'
        ).mock(return_value=Response(200, json=mock_jira_search_with_results['issues'][0]))

        # Mock other required endpoints
        remote_links_19539 = initial_work_item.get('fields', {}).get('remotelink', [])
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/remotelink').mock(
            return_value=Response(200, json=remote_links_19539)
        )

        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/comment').mock(
            return_value=Response(200, json={'comments': [], 'maxResults': 0, 'total': 0})
        )

        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/worklog').mock(
            return_value=Response(200, json={'worklogs': [], 'maxResults': 0, 'total': 0})
        )

        # Mock transitions endpoint for EXAMPLE-19539
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/transitions').mock(
            return_value=Response(200, json={'transitions': []})
        )

        # Extract remote links for EXAMPLE-19540
        remote_links_19540 = (
            mock_jira_search_with_results['issues'][0].get('fields', {}).get('remotelink', [])
        )
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19540/remotelink').mock(
            return_value=Response(200, json=remote_links_19540)
        )

        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19540/comment').mock(
            return_value=Response(200, json={'comments': [], 'maxResults': 0, 'total': 0})
        )

        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19540').mock(
            return_value=Response(200, json=mock_jira_search_with_results['issues'][0])
        )

        # Mock priority endpoint
        respx.get('https://example.atlassian.net/rest/api/3/priority').mock(
            return_value=Response(200, json=mock_jira_priorities)
        )

        # Mock issue types endpoint for project
        respx.get('https://example.atlassian.net/rest/api/3/project/EXAMPLE/statuses').mock(
            return_value=Response(
                200,
                json=[
                    {
                        'id': '10001',
                        'name': 'Task',
                        'subtask': False,
                        'statuses': [],
                    },
                    {
                        'id': '10002',
                        'name': 'Sub-task',
                        'subtask': True,
                        'statuses': [],
                    },
                ],
            )
        )

        respx.get(
            'https://example.atlassian.net/rest/api/3/issuetype/project?projectId=10000'
        ).mock(
            return_value=Response(
                200,
                json={'issueTypes': mock_project_issue_types},
            )
        )

        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

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
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock DELETE attachment endpoint
        respx.delete('https://example.atlassian.net/rest/api/3/attachment/66811').mock(
            return_value=Response(204)
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                if issue_key == 'EXAMPLE-19539':
                    issue_with_attachment = copy.deepcopy(issue)

                    issue_without_attachment = copy.deepcopy(issue)
                    issue_without_attachment['fields']['attachment'] = []

                    respx.get(
                        url__regex=rf'https://example\.atlassian\.net/rest/api/3/issue/{issue_key}.*'
                    ).mock(
                        side_effect=[
                            Response(200, json=issue_with_attachment),
                            Response(200, json=issue_without_attachment),
                        ]
                    )
                else:
                    respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                        return_value=Response(200, json=issue)
                    )

                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))

                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': mock_project_issue_types,
                },
            )
        )

        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
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
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock DELETE remote link endpoint
        respx.delete(
            'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/remotelink/10050'
        ).mock(return_value=Response(204))

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                    return_value=Response(200, json=issue)
                )

                if issue_key == 'EXAMPLE-19539':
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
                        f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
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
                        f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                    ).mock(return_value=Response(200, json=remote_links))

                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': mock_project_issue_types,
                },
            )
        )

        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
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
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock DELETE comment endpoint
        respx.delete(
            'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/comment/231668'
        ).mock(return_value=Response(204))

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                    return_value=Response(200, json=issue)
                )

                if issue_key == 'EXAMPLE-19539':
                    comments_data = issue.get('fields', {}).get('comment', {})
                    comments_list = comments_data.get('comments', [])

                    # Updated state: 0 comments (after deletion)
                    updated_comments = []

                    # Mock GET comments endpoint with side_effect for state changes
                    # NOTE: (vkhitrin)  Initial comments come from the search results JSON, so the first
                    #       call to this endpoint will be AFTER deletion (the internal refetch)
                    respx.get(
                        f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/comment'
                    ).mock(
                        side_effect=[
                            Response(200, json={'comments': updated_comments}),
                            Response(200, json={'comments': updated_comments}),
                        ]
                    )
                else:
                    # Mock comments endpoint for other work items
                    comments_data = issue.get('fields', {}).get('comment', {})
                    comments_list = comments_data.get('comments', [])
                    respx.get(
                        f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/comment'
                    ).mock(return_value=Response(200, json={'comments': comments_list}))

                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))

                # Mock status transitions endpoint
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': mock_project_issue_types,
                },
            )
        )

        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
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
            'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/worklog/10001'
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
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/worklog').mock(
            side_effect=[
                Response(200, json=initial_worklogs),
                Response(200, json=updated_worklogs),
            ]
        )

        # Mock all issues in the search results with basic data
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue['key']
            respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                return_value=Response(200, json=issue)
            )

            # Mock transitions endpoint for each issue
            respx.get(
                f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
            ).mock(return_value=Response(200, json=mock_transitions_data))

        # Mock projects endpoint
        respx.get('https://example.atlassian.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': mock_project_issue_types,
                },
            )
        )

        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=[])
        )

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
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
    mock_jira_project_example_with_issue_types,
    mock_jira_new_worklog,
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
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/worklog').mock(
            side_effect=[
                Response(200, json=initial_worklogs),
                Response(200, json=updated_worklogs),
            ]
        )

        # Mock POST worklog endpoint
        respx.post('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/worklog').mock(
            return_value=Response(201, json=new_worklog)
        )

        # Mock all issues in the search results with basic data
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue['key']
            respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                return_value=Response(200, json=issue)
            )

            # Mock transitions endpoint for each issue
            if issue_key != 'EXAMPLE-19539':
                transitions_data = {
                    'expand': 'transitions',
                    'transitions': [
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
                    ],
                }
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        mock_projects_search(mock_jira_projects)
        mock_project_example_with_inline_issue_types(mock_jira_project_example_with_issue_types)
        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoint
        mock_assignable_users_single_project(mock_jira_users)
        mock_assignable_users(mock_jira_users)

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_search_results(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_transitions,
):
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Extract subtasks from parent issue for JQL search handler
        parent_issue = next(
            (
                issue
                for issue in mock_jira_search_with_results['issues']
                if issue['key'] == 'EXAMPLE-19539'
            ),
            None,
        )

        subtasks_for_jql = []
        if parent_issue:
            parent_subtasks = parent_issue['fields'].get('subtasks', [])
            for subtask_summary in parent_subtasks:
                # Expand the minimal subtask info to full issue format for JQL search response
                full_subtask = {
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
                            'key': 'EXAMPLE-19539',
                            'fields': {'summary': parent_issue['fields']['summary']},
                        },
                    },
                }
                subtasks_for_jql.append(full_subtask)

        # Custom handler for JQL search to return subtasks when querying by parent
        def search_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')

            # Return subtasks for parent search
            if 'parent=EXAMPLE-19539' in jql:
                return Response(
                    200,
                    json={
                        'issues': subtasks_for_jql,
                        'maxResults': len(subtasks_for_jql),
                        'total': len(subtasks_for_jql),
                        'startAt': 0,
                    },
                )

            # Return main search results for other queries
            return Response(200, json=mock_jira_search_with_results)

        # Mock search endpoint with custom handler
        respx.post('https://example.atlassian.net/rest/api/3/search/jql').mock(
            side_effect=search_handler
        )

        # Mock approximate count with custom handler
        def count_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')
            if 'parent=EXAMPLE-19539' in jql:
                return Response(200, json={'count': len(subtasks_for_jql)})
            return Response(
                200, json={'count': len(mock_jira_search_with_results.get('issues', []))}
            )

        respx.post('https://example.atlassian.net/rest/api/3/search/approximate-count').mock(
            side_effect=count_handler
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                    return_value=Response(200, json=issue)
                )
                # Mock remote links endpoint for each work item
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint with available transitions
                transitions_data = mock_jira_transitions
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        # Mock get individual subtasks
        for subtask in subtasks_for_jql:
            subtask_key = subtask.get('key')
            if subtask_key:
                respx.get(f'https://example.atlassian.net/rest/api/3/issue/{subtask_key}').mock(
                    return_value=Response(200, json=subtask)
                )
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{subtask_key}/remotelink'
                ).mock(return_value=Response(200, json=[]))
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{subtask_key}/transitions'
                ).mock(return_value=Response(200, json=mock_jira_transitions))

        # Mock projects, issue types, and statuses
        respx.get('https://example.atlassian.net/rest/api/3/project/search').mock(
            return_value=Response(200, json=mock_jira_projects)
        )

        # Mock get single project endpoint with issue types (for creating subtasks)
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': [
                        {
                            'self': 'https://example.atlassian.net/rest/api/3/issuetype/10001',
                            'id': '10001',
                            'description': 'A task that needs to be done.',
                            'iconUrl': 'https://example.atlassian.net/secure/viewavatar?size=xsmall&avatarId=10318&avatarType=issuetype',
                            'name': 'Task',
                            'subtask': False,
                            'avatarId': 10318,
                            'hierarchyLevel': 0,
                        },
                        {
                            'self': 'https://example.atlassian.net/rest/api/3/issuetype/10002',
                            'id': '10002',
                            'description': 'A small piece of work that is part of a larger task.',
                            'iconUrl': 'https://example.atlassian.net/secure/viewavatar?size=xsmall&avatarId=10316&avatarType=issuetype',
                            'name': 'Sub-task',
                            'subtask': True,
                            'avatarId': 10316,
                            'hierarchyLevel': -1,
                        },
                    ],
                },
            )
        )

        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=[])
        )

        # Mock assignable users endpoint (returns users for work item assignable queries)
        respx.get('https://example.atlassian.net/rest/api/3/user/assignable/search').mock(
            return_value=Response(200, json=mock_jira_users)
        )

        # Mock user assignable multi project search endpoint (for creating subtasks)
        respx.get(
            'https://example.atlassian.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint (for creating subtasks - issue type 10002)
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
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
        return json.load(f)


@pytest.fixture
async def mock_jira_api_with_new_work_item(
    mock_jira_server_info,
    mock_jira_projects,
    mock_jira_issue_types,
    mock_jira_statuses,
    mock_jira_myself,
    mock_jira_users,
):
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)
        mock_projects_search(mock_jira_projects)
        mock_project_example_with_fixture_issue_types(mock_jira_issue_types)

        # Mock users assignable to project (correct endpoint)
        respx.get(
            'https://example.atlassian.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint (for specific project and issue type)
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10004.*'
        ).mock(
            return_value=Response(
                200,
                json={
                    'fields': [
                        {'fieldId': 'project', 'required': True, 'operations': ['set']},
                        {'fieldId': 'issuetype', 'required': True, 'operations': ['set']},
                        {'fieldId': 'summary', 'required': True, 'operations': ['set']},
                        {'fieldId': 'description', 'required': False, 'operations': ['set']},
                        {'fieldId': 'reporter', 'required': False, 'operations': ['set']},
                        {'fieldId': 'assignee', 'required': False, 'operations': ['set']},
                        {
                            'fieldId': 'priority',
                            'name': 'Priority',
                            'required': True,
                            'operations': ['set'],
                            'schema': {'type': 'priority', 'system': 'priority'},
                            'allowedValues': [
                                {'id': '1', 'name': 'Highest'},
                                {'id': '2', 'name': 'High'},
                                {'id': '3', 'name': 'Medium'},
                                {'id': '4', 'name': 'Low'},
                                {'id': '5', 'name': 'Lowest'},
                            ],
                        },
                        {
                            'fieldId': 'labels',
                            'name': 'Labels',
                            'required': False,
                            'operations': ['add', 'set', 'remove'],
                            'schema': {'type': 'array', 'items': 'string', 'system': 'labels'},
                        },
                        {
                            'fieldId': 'duedate',
                            'name': 'Due Date',
                            'required': False,
                            'operations': ['set'],
                            'schema': {'type': 'date', 'system': 'duedate'},
                        },
                    ]
                },
            )
        )

        # Mock statuses
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=mock_jira_statuses)
        )

        # Mock issue types
        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=mock_jira_issue_types)
        )

        # Mock JQL validation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/jql/parse').mock(
            return_value=Response(200, json={'valid': True, 'errors': []})
        )

        # Mock search endpoint (empty results for initial state)
        respx.post('https://example.atlassian.net/rest/api/3/search/jql').mock(
            return_value=Response(200, json={'issues': [], 'total': 0})
        )

        # Mock search for EXAMPLE-2 (newly created work item)
        respx.get(url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/EXAMPLE-2.*').mock(
            return_value=Response(
                200,
                json={
                    'id': '10000',
                    'key': 'EXAMPLE-2',
                    'self': 'https://example.atlassian.net/rest/api/3/issue/10000',
                    'fields': {
                        'summary': 'Test work item summary',
                        'status': {
                            'name': 'To Do',
                            'statusCategory': {'key': 'new', 'colorName': 'blue-gray'},
                        },
                        'priority': {'id': '1', 'name': 'Highest'},
                        'issuetype': {'name': 'Task', 'subtask': False},
                        'project': {'key': 'EXAMPLE', 'name': 'Test Project'},
                    },
                },
            )
        )

        # Mock approximate count endpoint
        respx.post('https://example.atlassian.net/rest/api/3/search/approximate-count').mock(
            return_value=Response(200, json={'count': 0})
        )

        # Mock POST /issue endpoint (create work item)
        respx.post('https://example.atlassian.net/rest/api/3/issue').mock(
            return_value=Response(
                201,
                json={
                    'id': '10000',
                    'key': 'EXAMPLE-2',
                    'self': 'https://example.atlassian.net/rest/api/3/issue/10000',
                },
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
    mock_jira_statuses,
    mock_jira_myself,
    mock_jira_users,
):
    async with respx.mock:
        setup_common_mocks(
            mock_jira_server_info,
            mock_jira_myself,
            mock_jira_projects,
            mock_jira_issue_types,
            mock_jira_statuses,
        )
        mock_assignable_users(mock_jira_users)
        mock_project_example_with_fixture_issue_types(mock_jira_issue_types)

        # Mock search endpoint (empty results for initial state)
        respx.post('https://example.atlassian.net/rest/api/3/search/jql').mock(
            return_value=Response(200, json={'issues': [], 'total': 0})
        )

        # Mock GET for original work item EXAMPLE-1234 (for clone operation)
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/EXAMPLE-1234.*'
        ).mock(
            return_value=Response(
                200,
                json={
                    'id': '10001',
                    'key': 'EXAMPLE-1234',
                    'self': 'https://example.atlassian.net/rest/api/3/issue/10001',
                    'fields': {
                        'summary': 'Original Work Item Summary',
                        'description': {
                            'type': 'doc',
                            'version': 1,
                            'content': [
                                {
                                    'type': 'paragraph',
                                    'content': [{'type': 'text', 'text': 'Original description'}],
                                }
                            ],
                        },
                        'status': {
                            'name': 'In Progress',
                            'statusCategory': {'key': 'indeterminate', 'colorName': 'yellow'},
                        },
                        'priority': {'id': '1', 'name': 'Highest'},
                        'issuetype': {'id': '10004', 'name': 'Task', 'subtask': False},
                        'project': {'id': '10446', 'key': 'EXAMPLE', 'name': 'Test Project'},
                        'reporter': {
                            'accountId': '555000:11111111-1111-1111-1111-111111111111',
                            'displayName': 'Test User',
                        },
                    },
                },
            )
        )

        # Mock search for EXAMPLE-2 (cloned work item with correct summary)
        respx.get(url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/EXAMPLE-2.*').mock(
            return_value=Response(
                200,
                json={
                    'id': '10002',
                    'key': 'EXAMPLE-2',
                    'self': 'https://example.atlassian.net/rest/api/3/issue/10002',
                    'fields': {
                        'summary': 'CLONE - Original Work Item Summary',
                        'description': {
                            'type': 'doc',
                            'version': 1,
                            'content': [
                                {
                                    'type': 'paragraph',
                                    'content': [{'type': 'text', 'text': 'Original description'}],
                                }
                            ],
                        },
                        'status': {
                            'name': 'To Do',
                            'statusCategory': {'key': 'new', 'colorName': 'blue-gray'},
                        },
                        'priority': {'id': '1', 'name': 'Highest'},
                        'issuetype': {'id': '10004', 'name': 'Task', 'subtask': False},
                        'project': {'id': '10446', 'key': 'EXAMPLE', 'name': 'Test Project'},
                        'reporter': {
                            'accountId': '555000:11111111-1111-1111-1111-111111111111',
                            'displayName': 'Test User',
                        },
                    },
                },
            )
        )

        # Mock approximate count endpoint
        respx.post('https://example.atlassian.net/rest/api/3/search/approximate-count').mock(
            return_value=Response(200, json={'count': 0})
        )

        # Mock POST /issue endpoint (create cloned work item)
        respx.post('https://example.atlassian.net/rest/api/3/issue').mock(
            return_value=Response(
                201,
                json={
                    'id': '10002',
                    'key': 'EXAMPLE-2',
                    'self': 'https://example.atlassian.net/rest/api/3/issue/10002',
                },
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
    mock_jira_transitions,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # TODO: (vkhitrin) revisit this comment
        # Mock GET work item endpoint with updated issuelinks field for EXAMPLE-19539
        # This MUST be registered BEFORE the general loop below to take priority
        # The application uses 'work_itemlinks' as the field name in the query
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/EXAMPLE-19539.*work_itemlinks'
        ).mock(
            return_value=Response(
                200,
                json={
                    'id': '94264',
                    'key': 'EXAMPLE-19539',
                    'self': 'https://example.atlassian.net/rest/api/3/issue/94264',
                    'fields': {
                        'issuelinks': [
                            # Existing links from fixture
                            {
                                'id': '10001',
                                'type': {
                                    'id': '10000',
                                    'name': 'Blocks',
                                    'inward': 'is blocked by',
                                    'outward': 'blocks',
                                },
                                'outwardIssue': {
                                    'id': '94265',
                                    'key': 'EXAMPLE-19540',
                                    'self': 'https://example.atlassian.net/rest/api/3/issue/94265',
                                    'fields': {
                                        'summary': 'Deploy code quality changes to staging',
                                        'status': {
                                            'name': 'To Do',
                                            'statusCategory': {
                                                'key': 'new',
                                                'colorName': 'blue-gray',
                                            },
                                        },
                                        'priority': {'id': '10001', 'name': 'High'},
                                        'issuetype': {'name': 'Task'},
                                    },
                                },
                            },
                            {
                                'id': '10002',
                                'type': {
                                    'id': '10001',
                                    'name': 'Relates',
                                    'inward': 'relates to',
                                    'outward': 'relates to',
                                },
                                'inwardIssue': {
                                    'id': '94266',
                                    'key': 'EXAMPLE-19541',
                                    'self': 'https://example.atlassian.net/rest/api/3/issue/94266',
                                    'fields': {
                                        'summary': 'Update documentation for merge approval process',
                                        'status': {
                                            'name': 'Done',
                                            'statusCategory': {'key': 'done', 'colorName': 'green'},
                                        },
                                        'priority': {'id': '10002', 'name': 'Medium'},
                                        'issuetype': {'name': 'Documentation'},
                                    },
                                },
                            },
                            # NEW LINK - the one we just created
                            {
                                'id': '10003',
                                'type': {
                                    'id': '10000',
                                    'name': 'Blocks',
                                    'inward': 'is blocked by',
                                    'outward': 'blocks',
                                },
                                'outwardIssue': {
                                    'id': '99999',
                                    'key': 'EXAMPLE-100',
                                    'self': 'https://example.atlassian.net/rest/api/3/issue/99999',
                                    'fields': {
                                        'summary': 'Test related work item for linking',
                                        'status': {
                                            'name': 'In Progress',
                                            'statusCategory': {
                                                'key': 'indeterminate',
                                                'colorName': 'yellow',
                                            },
                                        },
                                        'priority': {'id': '10002', 'name': 'High'},
                                        'issuetype': {'name': 'Task'},
                                    },
                                },
                            },
                        ]
                    },
                },
            )
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                    return_value=Response(200, json=issue)
                )
                # Mock remote links endpoint
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint
                transitions_data = mock_jira_transitions
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        # Mock projects, issue types, and statuses
        mock_projects_search(mock_jira_projects)

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': [
                        {
                            'self': 'https://example.atlassian.net/rest/api/3/issuetype/10001',
                            'id': '10001',
                            'description': 'A task that needs to be done.',
                            'iconUrl': 'https://example.atlassian.net/secure/viewavatar?size=xsmall&avatarId=10318&avatarType=issuetype',
                            'name': 'Task',
                            'subtask': False,
                            'avatarId': 10318,
                            'hierarchyLevel': 0,
                        },
                        {
                            'self': 'https://example.atlassian.net/rest/api/3/issuetype/10002',
                            'id': '10002',
                            'description': 'A small piece of work that is part of a larger task.',
                            'iconUrl': 'https://example.atlassian.net/secure/viewavatar?size=xsmall&avatarId=10316&avatarType=issuetype',
                            'name': 'Sub-task',
                            'subtask': True,
                            'avatarId': 10316,
                            'hierarchyLevel': -1,
                        },
                    ],
                },
            )
        )

        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoint
        mock_assignable_users(mock_jira_users)

        # Mock user assignable multi project search endpoint
        respx.get(
            'https://example.atlassian.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        # Mock work item link creation endpoint
        # This endpoint returns nothing (201 Created with empty body)
        respx.post('https://example.atlassian.net/rest/api/3/issueLink').mock(
            return_value=Response(201, json={})
        )

        yield


@pytest.fixture
async def mock_jira_api_with_web_link_creation(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_work_item_link_types,
    mock_jira_transitions,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # Mock GET remote links endpoint for EXAMPLE-19539
        # Use side_effect to return different values on first and subsequent calls:
        # - First call (initial load): 6 links (from fixture)
        # - Second call (after creation): 7 links (6 + 1 new)

        # Get the remote links from the fixture for EXAMPLE-19539
        example_issue = next(
            (
                issue
                for issue in mock_jira_search_with_results.get('issues', [])
                if issue['key'] == 'EXAMPLE-19539'
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
                    'self': f'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/remotelink/{next_id}',
                    'object': {
                        'url': 'https://docs.example.com/api',
                        'title': 'API Documentation',
                    },
                },
            ]

            # Use side_effect to return different responses on subsequent calls
            respx.get(
                'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/remotelink'
            ).mock(
                side_effect=[
                    Response(200, json=initial_links),
                    Response(200, json=updated_links),
                ]
            )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                # Skip EXAMPLE-19539 as we've already mocked remotelink above
                if issue_key != 'EXAMPLE-19539':
                    respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                        return_value=Response(200, json=issue)
                    )
                    # Mock remote links endpoint
                    remote_links = issue.get('fields', {}).get('remotelink', [])
                    respx.get(
                        f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                    ).mock(return_value=Response(200, json=remote_links))
                else:
                    # For EXAMPLE-19539, mock the GET issue endpoint
                    respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                        return_value=Response(200, json=issue)
                    )
                # Mock status transitions endpoint
                transitions_data = mock_jira_transitions
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        # Mock projects, issue types, and statuses
        mock_projects_search(mock_jira_projects)

        # Mock get single project endpoint
        project_key = mock_jira_projects['values'][0]['key']
        respx.get(f'https://example.atlassian.net/rest/api/3/project/{project_key}').mock(
            return_value=Response(
                200,
                json={
                    **mock_jira_projects['values'][0],
                    'issueTypes': [
                        {
                            'self': 'https://example.atlassian.net/rest/api/3/issuetype/10001',
                            'id': '10001',
                            'description': 'A task that needs to be done.',
                            'iconUrl': 'https://example.atlassian.net/secure/viewavatar?size=xsmall&avatarId=10318&avatarType=issuetype',
                            'name': 'Task',
                            'subtask': False,
                            'avatarId': 10318,
                            'hierarchyLevel': 0,
                        },
                        {
                            'self': 'https://example.atlassian.net/rest/api/3/issuetype/10002',
                            'id': '10002',
                            'description': 'A small piece of work that is part of a larger task.',
                            'iconUrl': 'https://example.atlassian.net/secure/viewavatar?size=xsmall&avatarId=10316&avatarType=issuetype',
                            'name': 'Sub-task',
                            'subtask': True,
                            'avatarId': 10316,
                            'hierarchyLevel': -1,
                        },
                    ],
                },
            )
        )

        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoint
        mock_assignable_users(mock_jira_users)

        # Mock user assignable multi project search endpoint
        respx.get(
            'https://example.atlassian.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        # Mock web link creation endpoint
        # This endpoint returns nothing (200 OK with empty body)
        respx.post('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/remotelink').mock(
            return_value=Response(200, json={})
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
    mock_jira_project_example_with_issue_types,
    mock_jira_initial_comment,
    mock_jira_new_comment,
):
    async with respx.mock:
        # Mock server info and myself endpoints
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Mock search endpoint with results
        mock_search_with_results(mock_jira_search_with_results)

        # Mock approximate count endpoint
        mock_approximate_count(len(mock_jira_search_with_results.get('issues', [])))

        # TODO: (vkhitrin) revisit this comment.
        # Mock GET comments endpoint for EXAMPLE-19539
        # This mock must be registered BEFORE the general loop
        # Use side_effect to return different values on first and subsequent calls:
        # - First call (initial load): 1 comment (from fixture)
        # - Second call (after creation): 2 comments (1 existing + 1 new)

        # Data for initial state (1 comment from fixture)
        # This must match the actual comment from jira_search_with_results.json for EXAMPLE-19539
        initial_comment = mock_jira_initial_comment

        new_comment = mock_jira_new_comment

        updated_response = {
            'comments': [new_comment, initial_comment],  # Newest first (orderBy=-created)
            'self': 'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/comment',
            'maxResults': 50,
            'total': 2,
            'startAt': 0,
        }

        respx.get(
            'https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/comment',
        ).mock(return_value=Response(200, json=updated_response))

        # Mock POST comment creation endpoint
        respx.post('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-19539/comment').mock(
            return_value=Response(201, json=new_comment)
        )

        # Mock get specific work items for each issue in the search results
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                if issue_key != 'EXAMPLE-19539':
                    respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                        return_value=Response(200, json=issue)
                    )
                    # Mock comments endpoint with paginated structure
                    comments = issue.get('fields', {}).get('comment', {}).get('comments', [])
                    comments_response = {
                        'comments': comments,
                        'self': f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/comment',
                        'maxResults': 50,
                        'total': len(comments),
                        'startAt': 0,
                    }
                    respx.get(
                        url__regex=f'https://example\\.atlassian\\.net/rest/api/3/issue/{issue_key}/comment.*'
                    ).mock(return_value=Response(200, json=comments_response))
                else:
                    respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                        return_value=Response(200, json=issue)
                    )
                    # Mock remote links endpoint for EXAMPLE-19539
                    remote_links = issue.get('fields', {}).get('remotelink', [])
                    respx.get(
                        f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                    ).mock(return_value=Response(200, json=remote_links))
                # Mock status transitions endpoint
                transitions_data = {
                    'transitions': [
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
                }
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=transitions_data))

        # Mock projects endpoint
        mock_projects_search(mock_jira_projects)
        mock_project_example_with_inline_issue_types(mock_jira_project_example_with_issue_types)
        mock_issue_types([])
        mock_statuses([])

        # Mock assignable users endpoint
        mock_assignable_users(mock_jira_users)

        # Mock user assignable multi project search endpoint
        respx.get(
            'https://example.atlassian.net/rest/api/3/user/assignable/multiProjectSearch'
        ).mock(return_value=Response(200, json=mock_jira_users))

        # Mock create metadata endpoint
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield


@pytest.fixture
async def mock_jira_api_with_subtask_creation(
    mock_jira_server_info,
    mock_jira_myself,
    mock_jira_search_with_results,
    mock_jira_projects,
    mock_jira_users,
    mock_jira_project_example_with_issue_types,
    mock_jira_work_item_link_types,
    mock_jira_transitions,
):
    """Mock Jira API for subtask creation testing.

    Simulates creating a new subtask for EXAMPLE-19539 via JQL search.
    Extracts existing subtasks from the parent issue's subtasks field.
    """
    async with respx.mock:
        mock_server_info(mock_jira_server_info)
        mock_myself(mock_jira_myself)

        # Create new subtask that will be returned after creation
        new_subtask = {
            'id': '94272',
            'key': 'EXAMPLE-20000',
            'self': 'https://example.atlassian.net/rest/api/3/issue/94272',
            'fields': {
                'id': '94272',
                'key': 'EXAMPLE-20000',
                'summary': 'Test new subtask',
                'status': {
                    'name': 'To Do',
                    'statusCategory': {
                        'key': 'new',
                        'colorName': 'blue-gray',
                    },
                },
                'priority': {'id': '10002', 'name': 'Medium'},
                'issuetype': {'id': '10002', 'name': 'Sub-task', 'subtask': True},
                'assignee': {
                    'accountId': '555000:11111111-1111-1111-1111-111111111111',
                    'displayName': 'Test User',
                    'emailAddress': 'test@example.com',
                },
                'parent': {
                    'key': 'EXAMPLE-19539',
                    'fields': {
                        'summary': mock_jira_search_with_results['issues'][0]['fields']['summary']
                    },
                },
            },
        }

        # Extract existing subtasks from parent issue (EXAMPLE-19539)
        parent_issue = next(
            (
                issue
                for issue in mock_jira_search_with_results['issues']
                if issue['key'] == 'EXAMPLE-19539'
            ),
            None,
        )
        if not parent_issue:
            raise ValueError('EXAMPLE-19539 not found in mock_jira_search_with_results')

        # Get subtasks from parent issue's subtasks field and expand them to full issue format
        parent_subtasks = parent_issue['fields'].get('subtasks', [])
        initial_subtasks = []
        for subtask_summary in parent_subtasks:
            # Expand the minimal subtask info to full issue format for JQL search response
            full_subtask = {
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
                        'key': 'EXAMPLE-19539',
                        'fields': {'summary': parent_issue['fields']['summary']},
                    },
                },
            }
            initial_subtasks.append(full_subtask)

        # Create search responses with side effect for before/after creation
        initial_subtasks_response = {
            'issues': initial_subtasks,
            'maxResults': len(initial_subtasks),
            'total': len(initial_subtasks),
            'startAt': 0,
        }
        after_create_subtasks_response = {
            'issues': initial_subtasks + [new_subtask],
            'maxResults': len(initial_subtasks) + 1,
            'total': len(initial_subtasks) + 1,
            'startAt': 0,
        }

        # Custom handler to check for parent=EXAMPLE-19539 JQL query
        search_call_count = [0]

        def search_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')

            # Return subtasks for parent search
            if 'parent=EXAMPLE-19539' in jql:
                search_call_count[0] += 1
                if search_call_count[0] == 1:
                    return Response(200, json=initial_subtasks_response)
                else:
                    return Response(200, json=after_create_subtasks_response)

            # Return main search results for other queries
            return Response(200, json=mock_jira_search_with_results)

        # Mock search endpoint with custom handler
        respx.post('https://example.atlassian.net/rest/api/3/search/jql').mock(
            side_effect=search_handler
        )

        # Mock approximate count
        def count_handler(request):
            body = json.loads(request.content)
            jql = body.get('jql', '')
            if 'parent=EXAMPLE-19539' in jql:
                if search_call_count[0] <= 1:
                    return Response(200, json={'count': len(initial_subtasks)})
                else:
                    return Response(200, json={'count': len(initial_subtasks) + 1})
            return Response(
                200, json={'count': len(mock_jira_search_with_results.get('issues', []))}
            )

        respx.post('https://example.atlassian.net/rest/api/3/search/approximate-count').mock(
            side_effect=count_handler
        )

        # Mock POST /issue endpoint (for creating the subtask)
        respx.post('https://example.atlassian.net/rest/api/3/issue').mock(
            return_value=Response(
                201,
                json={
                    'id': '94272',
                    'key': 'EXAMPLE-20000',
                    'self': 'https://example.atlassian.net/rest/api/3/issue/94272',
                },
            )
        )

        # Mock GET for newly created subtask
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-20000').mock(
            return_value=Response(200, json=new_subtask)
        )
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-20000/remotelink').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.net/rest/api/3/issue/EXAMPLE-20000/transitions').mock(
            return_value=Response(200, json=mock_jira_transitions)
        )

        # Mock get specific work items
        for issue in mock_jira_search_with_results.get('issues', []):
            issue_key = issue.get('key')
            if issue_key:
                respx.get(f'https://example.atlassian.net/rest/api/3/issue/{issue_key}').mock(
                    return_value=Response(200, json=issue)
                )
                remote_links = issue.get('fields', {}).get('remotelink', [])
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/remotelink'
                ).mock(return_value=Response(200, json=remote_links))
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{issue_key}/transitions'
                ).mock(return_value=Response(200, json=mock_jira_transitions))

        # Mock get individual subtasks
        for subtask in initial_subtasks:
            subtask_key = subtask.get('key')
            if subtask_key:
                respx.get(f'https://example.atlassian.net/rest/api/3/issue/{subtask_key}').mock(
                    return_value=Response(200, json=subtask)
                )
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{subtask_key}/remotelink'
                ).mock(return_value=Response(200, json=[]))
                respx.get(
                    f'https://example.atlassian.net/rest/api/3/issue/{subtask_key}/transitions'
                ).mock(return_value=Response(200, json=mock_jira_transitions))

        # Mock projects endpoint
        mock_projects_search(mock_jira_projects)
        mock_project_example_with_inline_issue_types(mock_jira_project_example_with_issue_types)

        # Mock issue types and statuses
        respx.get('https://example.atlassian.net/rest/api/3/issuetype').mock(
            return_value=Response(200, json=[])
        )
        respx.get('https://example.atlassian.net/rest/api/3/status').mock(
            return_value=Response(200, json=[])
        )

        # Mock assignable users endpoints
        mock_assignable_users(mock_jira_users)
        mock_assignable_users_single_project(mock_jira_users)

        # Mock create metadata endpoint (for Sub-task type)
        respx.get(
            url__regex=r'https://example\.atlassian\.net/rest/api/3/issue/createmeta/EXAMPLE/issuetypes/10002.*'
        ).mock(return_value=Response(200, json={'fields': {}}))

        # Mock JQL validation endpoint
        mock_jql_validation()

        # Mock work item link types endpoint
        respx.get('https://example.atlassian.net/rest/api/3/issueLinkType').mock(
            return_value=Response(200, json=mock_jira_work_item_link_types)
        )

        yield
