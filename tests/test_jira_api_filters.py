import pytest

from tests.jira_api_test_utils import build_api_with_mocked_client


@pytest.mark.asyncio
async def test_fetch_user_filters_fetches_all_personal_pages():
    api, make_request = build_api_with_mocked_client(
        [
            {
                'startAt': 0,
                'maxResults': 2,
                'isLast': False,
                'values': [
                    {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': False},
                    {'id': '2', 'name': 'Mine 2', 'jql': 'project = SUP', 'favourite': True},
                ],
            },
            {
                'startAt': 2,
                'maxResults': 2,
                'isLast': True,
                'values': [
                    {'id': '3', 'name': 'Mine 3', 'jql': 'project = OPS', 'favourite': False},
                ],
            },
        ]
    )

    filters = await api.fetch_user_filters(account_id='user-1', max_results=2)

    assert filters == [
        {'label': 'Mine 1', 'expression': 'project = ENG', 'source': 'remote', 'starred': False},
        {'label': 'Mine 2', 'expression': 'project = SUP', 'source': 'remote', 'starred': True},
        {'label': 'Mine 3', 'expression': 'project = OPS', 'source': 'remote', 'starred': False},
    ]
    assert make_request.await_count == 2
    assert make_request.await_args_list[0].kwargs['params'] == {
        'maxResults': 2,
        'expand': 'jql,favourite',
        'accountId': 'user-1',
        'startAt': 0,
    }
    assert make_request.await_args_list[1].kwargs['params'] == {
        'maxResults': 2,
        'expand': 'jql,favourite',
        'accountId': 'user-1',
        'startAt': 2,
    }


@pytest.mark.asyncio
async def test_fetch_user_filters_fetches_all_shared_pages_and_deduplicates():
    api, make_request = build_api_with_mocked_client(
        [
            {
                'startAt': 0,
                'maxResults': 2,
                'isLast': True,
                'values': [
                    {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': True},
                ],
            },
            {
                'startAt': 0,
                'maxResults': 2,
                'isLast': False,
                'values': [
                    {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': True},
                    {'id': '2', 'name': 'Team 1', 'jql': 'project = SUP', 'favourite': True},
                ],
            },
            {
                'startAt': 2,
                'maxResults': 2,
                'isLast': True,
                'values': [
                    {'id': '3', 'name': 'Team 2', 'jql': 'project = OPS', 'favourite': False},
                ],
            },
        ]
    )

    filters = await api.fetch_user_filters(
        account_id='user-1',
        include_shared=True,
        starred_only=True,
        max_results=2,
    )

    assert filters == [
        {'label': 'Mine 1', 'expression': 'project = ENG', 'source': 'remote', 'starred': True},
        {'label': 'Team 1', 'expression': 'project = SUP', 'source': 'remote', 'starred': True},
    ]
    assert make_request.await_count == 3
    assert make_request.await_args_list[1].kwargs['params'] == {
        'maxResults': 2,
        'expand': 'jql,favourite',
        'startAt': 0,
    }
    assert make_request.await_args_list[2].kwargs['params'] == {
        'maxResults': 2,
        'expand': 'jql,favourite',
        'startAt': 2,
    }


@pytest.mark.asyncio
async def test_get_all_fields_paginated_fetches_all_pages():
    api, make_request = build_api_with_mocked_client(
        [
            {
                'startAt': 0,
                'maxResults': 2,
                'isLast': False,
                'values': [
                    {'id': 'custom-1', 'description': 'First'},
                    {'id': 'custom-2', 'description': 'Second'},
                ],
            },
            {
                'startAt': 2,
                'maxResults': 2,
                'isLast': True,
                'values': [
                    {'id': 'custom-3', 'description': 'Third'},
                ],
            },
        ]
    )

    fields = await api.get_all_fields_paginated(max_results=2, query='Story Points')

    assert fields == [
        {'id': 'custom-1', 'description': 'First'},
        {'id': 'custom-2', 'description': 'Second'},
        {'id': 'custom-3', 'description': 'Third'},
    ]
    assert make_request.await_count == 2
    assert make_request.await_args_list[0].kwargs['params'] == {
        'query': 'Story Points',
        'startAt': 0,
        'maxResults': 2,
    }
    assert make_request.await_args_list[1].kwargs['params'] == {
        'query': 'Story Points',
        'startAt': 2,
        'maxResults': 2,
    }
