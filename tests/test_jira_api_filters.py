import pytest

from tests.jira_api_test_utils import build_api_with_mocked_client


def paginated_response(start_at: int, values: list[dict], *, is_last: bool) -> dict:
    return {
        'startAt': start_at,
        'maxResults': 2,
        'isLast': is_last,
        'values': values,
    }


def assert_request_params(make_request, index: int, **params) -> None:
    assert make_request.await_args_list[index].kwargs['params'] == params


def expected_filter(label: str, expression: str, *, starred: bool) -> dict:
    return {
        'label': label,
        'expression': expression,
        'source': 'remote',
        'starred': starred,
    }


@pytest.mark.asyncio
async def test_fetch_user_filters_fetches_all_personal_pages():
    api, make_request = build_api_with_mocked_client(
        [
            paginated_response(
                0,
                [
                    {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': False},
                    {'id': '2', 'name': 'Mine 2', 'jql': 'project = SUP', 'favourite': True},
                ],
                is_last=False,
            ),
            paginated_response(
                2,
                [
                    {'id': '3', 'name': 'Mine 3', 'jql': 'project = OPS', 'favourite': False},
                ],
                is_last=True,
            ),
        ]
    )

    filters = await api.fetch_user_filters(account_id='user-1', max_results=2)

    assert filters == [
        expected_filter('Mine 1', 'project = ENG', starred=False),
        expected_filter('Mine 2', 'project = SUP', starred=True),
        expected_filter('Mine 3', 'project = OPS', starred=False),
    ]
    assert make_request.await_count == 2
    assert_request_params(
        make_request,
        0,
        maxResults=2,
        expand='jql,favourite',
        accountId='user-1',
        startAt=0,
    )
    assert_request_params(
        make_request,
        1,
        maxResults=2,
        expand='jql,favourite',
        accountId='user-1',
        startAt=2,
    )


@pytest.mark.asyncio
async def test_fetch_user_filters_fetches_all_shared_pages_and_deduplicates():
    api, make_request = build_api_with_mocked_client(
        [
            paginated_response(
                0,
                [
                    {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': True},
                ],
                is_last=True,
            ),
            paginated_response(
                0,
                [
                    {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': True},
                    {'id': '2', 'name': 'Team 1', 'jql': 'project = SUP', 'favourite': True},
                ],
                is_last=False,
            ),
            paginated_response(
                2,
                [
                    {'id': '3', 'name': 'Team 2', 'jql': 'project = OPS', 'favourite': False},
                ],
                is_last=True,
            ),
        ]
    )

    filters = await api.fetch_user_filters(
        account_id='user-1',
        include_shared=True,
        starred_only=True,
        max_results=2,
    )

    assert filters == [
        expected_filter('Mine 1', 'project = ENG', starred=True),
        expected_filter('Team 1', 'project = SUP', starred=True),
    ]
    assert make_request.await_count == 3
    assert_request_params(make_request, 1, maxResults=2, expand='jql,favourite', startAt=0)
    assert_request_params(make_request, 2, maxResults=2, expand='jql,favourite', startAt=2)


@pytest.mark.asyncio
async def test_get_all_fields_paginated_fetches_all_pages():
    api, make_request = build_api_with_mocked_client(
        [
            paginated_response(
                0,
                [
                    {'id': 'custom-1', 'description': 'First'},
                    {'id': 'custom-2', 'description': 'Second'},
                ],
                is_last=False,
            ),
            paginated_response(
                2,
                [
                    {'id': 'custom-3', 'description': 'Third'},
                ],
                is_last=True,
            ),
        ]
    )

    fields = await api.get_all_fields_paginated(max_results=2, query='Story Points')

    assert fields == [
        {'id': 'custom-1', 'description': 'First'},
        {'id': 'custom-2', 'description': 'Second'},
        {'id': 'custom-3', 'description': 'Third'},
    ]
    assert make_request.await_count == 2
    assert_request_params(make_request, 0, query='Story Points', startAt=0, maxResults=2)
    assert_request_params(make_request, 1, query='Story Points', startAt=2, maxResults=2)
