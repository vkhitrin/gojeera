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


def expected_filter(label: str, expression: str, *, starred: bool, filter_id: str = '1') -> dict:
    return {
        'id': filter_id,
        'label': label,
        'expression': expression,
        'source': 'remote',
        'starred': starred,
    }


def paginated_values(first_values: list[dict], second_values: list[dict]) -> list[dict]:
    return [
        paginated_response(0, first_values, is_last=False),
        paginated_response(2, second_values, is_last=True),
    ]


@pytest.mark.asyncio
async def test_fetch_user_filters_fetches_all_personal_pages():
    api, make_request = build_api_with_mocked_client(
        paginated_values(
            [
                {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': False},
                {'id': '2', 'name': 'Mine 2', 'jql': 'project = SUP', 'favourite': True},
            ],
            [
                {'id': '3', 'name': 'Mine 3', 'jql': 'project = OPS', 'favourite': False},
            ],
        )
    )

    filters = await api.fetch_user_filters(account_id='user-1', max_results=2)

    assert filters == [
        expected_filter('Mine 1', 'project = ENG', starred=False),
        expected_filter('Mine 2', 'project = SUP', starred=True, filter_id='2'),
        expected_filter('Mine 3', 'project = OPS', starred=False, filter_id='3'),
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
        paginated_values(
            [
                {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': True},
                {'id': '2', 'name': 'Team 1', 'jql': 'project = SUP', 'favourite': True},
            ],
            [
                {'id': '2', 'name': 'Team 1', 'jql': 'project = SUP', 'favourite': True},
                {'id': '3', 'name': 'Team 2', 'jql': 'project = OPS', 'favourite': False},
            ],
        )
    )

    filters = await api.fetch_user_filters(
        account_id='user-1',
        include_shared=True,
        max_results=2,
    )

    assert filters == [
        expected_filter('Mine 1', 'project = ENG', starred=True),
        expected_filter('Team 1', 'project = SUP', starred=True, filter_id='2'),
        expected_filter('Team 2', 'project = OPS', starred=False, filter_id='3'),
    ]
    assert make_request.await_count == 2
    assert_request_params(make_request, 0, maxResults=2, expand='jql,favourite', startAt=0)
    assert_request_params(make_request, 1, maxResults=2, expand='jql,favourite', startAt=2)


@pytest.mark.asyncio
async def test_fetch_user_filters_starred_only_uses_favourite_endpoint_even_with_shared_enabled():
    api, make_request = build_api_with_mocked_client(
        [
            {
                'values': [
                    {'id': '1', 'name': 'Mine 1', 'jql': 'project = ENG', 'favourite': True},
                    {'id': '2', 'name': 'Team 1', 'jql': 'project = SUP', 'favourite': True},
                ]
            }
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
        expected_filter('Team 1', 'project = SUP', starred=True, filter_id='2'),
    ]
    assert make_request.await_count == 1
    assert make_request.await_args is not None
    assert make_request.await_args.kwargs['url'] == 'filter/favourite'


@pytest.mark.asyncio
@pytest.mark.parametrize('include_shared', [False, True])
async def test_filter_search_raises_instead_of_returning_partial_results(include_shared):
    api, make_request = build_api_with_mocked_client(
        [
            paginated_response(
                0,
                [{'id': '1', 'name': 'First', 'jql': 'project = ENG'}],
                is_last=False,
            ),
            RuntimeError('page failed'),
        ]
    )

    with pytest.raises(RuntimeError, match='page failed'):
        await api.fetch_user_filters(account_id='user-1', include_shared=include_shared)
    assert make_request.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('starred_only', [False, True])
async def test_fetch_user_filters_propagates_request_failure(starred_only):
    api, _ = build_api_with_mocked_client([RuntimeError('request failed')])

    with pytest.raises(RuntimeError, match='request failed'):
        await api.fetch_user_filters(account_id='user-1', starred_only=starred_only)


@pytest.mark.asyncio
@pytest.mark.parametrize('starred_only', [False, True])
@pytest.mark.parametrize('response', [None, {}, {'values': None}])
async def test_fetch_user_filters_rejects_invalid_response(starred_only, response):
    api, _ = build_api_with_mocked_client([response])

    with pytest.raises(ValueError, match='Invalid .* filters response'):
        await api.fetch_user_filters(account_id='user-1', starred_only=starred_only)


@pytest.mark.asyncio
@pytest.mark.parametrize('starred_only', [False, True])
async def test_fetch_user_filters_accepts_successful_empty_results(starred_only):
    api, _ = build_api_with_mocked_client([{'values': [], 'isLast': True}])
    assert await api.fetch_user_filters(account_id='user-1', starred_only=starred_only) == []


@pytest.mark.asyncio
async def test_favourite_filters_accepts_list_response():
    api, _ = build_api_with_mocked_client(
        [[{'id': '1', 'name': 'First', 'jql': 'project = ENG', 'favourite': True}]]
    )
    assert await api.fetch_user_filters(starred_only=True) == [
        expected_filter('First', 'project = ENG', starred=True)
    ]


@pytest.mark.asyncio
async def test_get_all_fields_paginated_fetches_all_pages():
    api, make_request = build_api_with_mocked_client(
        paginated_values(
            [
                {'id': 'custom-1', 'description': 'First'},
                {'id': 'custom-2', 'description': 'Second'},
            ],
            [
                {'id': 'custom-3', 'description': 'Third'},
            ],
        )
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
