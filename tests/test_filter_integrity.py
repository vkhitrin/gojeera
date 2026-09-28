from importlib import resources
import sqlite3

import pytest

from gojeera.internal.store import migrations
from gojeera.internal.store.cache import ApplicationCache
from tests.jira_api_test_utils import build_api_with_mocked_client


def raw_filter(filter_id: str) -> dict:
    return {'id': filter_id, 'name': 'Team', 'jql': 'project = ENG', 'favourite': filter_id == '1'}


@pytest.mark.parametrize('with_total', [False, True])
async def test_missing_is_last_fetches_all_pages(with_total):
    pages = [
        {'startAt': 0, 'maxResults': 2, 'values': [raw_filter('1'), raw_filter('2')]},
        {'startAt': 2, 'maxResults': 2, 'values': [raw_filter('3')]},
    ]
    if with_total:
        for page in pages:
            page['total'] = 3
    api, request = build_api_with_mocked_client(pages)
    filters = await api.fetch_user_filters(account_id='user', max_results=2)
    assert [item['id'] for item in filters] == ['1', '2', '3']
    assert request.await_count == 2


@pytest.mark.parametrize(
    'overrides',
    [
        {'values': [], 'isLast': False},
        {'total': 10},
        {'startAt': 0},
        {'startAt': -1},
        {'maxResults': 0},
        {'isLast': 'true'},
        {'total': '2'},
        {'values': [raw_filter('1')]},
    ],
)
async def test_inconsistent_pages_never_return_partial_success(overrides):
    last = {'startAt': 1, 'maxResults': 1, 'isLast': True, 'values': [raw_filter('2')]}
    last.update(overrides)
    api, request = build_api_with_mocked_client(
        [{'startAt': 0, 'maxResults': 1, 'isLast': False, 'values': [raw_filter('1')]}, last]
    )
    with pytest.raises(ValueError):
        await api.fetch_user_filters(account_id='user', max_results=1)
    assert request.await_count == 2


@pytest.mark.parametrize('key', ['id', 'name', 'jql'])
@pytest.mark.parametrize('value', [None, '', '   ', 123])
async def test_incomplete_filter_records_are_not_cacheable(key, value):
    incomplete = raw_filter('2')
    incomplete[key] = value
    api, _ = build_api_with_mocked_client(
        [{'isLast': True, 'values': [raw_filter('1'), incomplete]}]
    )
    with pytest.raises(ValueError, match='Incomplete filter response'):
        await api.fetch_user_filters(account_id='user')


async def test_distinct_filter_ids_and_starred_status_survive_cache_roundtrip(application_cache):
    api, _ = build_api_with_mocked_client(
        [{'isLast': True, 'values': [raw_filter('1'), raw_filter('2')]}]
    )
    filters = await api.fetch_user_filters(account_id='user', include_shared=True)
    application_cache.set_remote_filters('user', filters, include_shared=True)
    cached = application_cache.get_remote_filters('user', include_shared=True)
    assert {item.id: item.as_filter_dict() for item in cached} == {
        item['id']: item for item in filters
    }


def test_failed_or_obsolete_cache_write_preserves_rows_and_sync_metadata(application_cache):
    original = {'id': '1', 'label': 'Original', 'expression': 'project = ENG'}
    application_cache.set_remote_filters('user', [original])
    metadata = application_cache._connection.execute('SELECT * FROM sync_log').fetchall()
    application_cache.set_remote_filters('user', [], can_write=lambda: False)
    with pytest.raises(sqlite3.IntegrityError):
        application_cache.set_remote_filters('user', [original, original])
    assert application_cache.get_remote_filters('user')[0].label == 'Original'
    assert application_cache._connection.execute('SELECT * FROM sync_log').fetchall() == metadata


def test_filter_identity_migration_preserves_legacy_rows_and_sync_metadata(tmp_path):
    path = tmp_path / 'legacy.db'
    connection = sqlite3.connect(path)
    initial = resources.files(migrations).joinpath(
        '202605221538050003_initial_atlassian_cache_schema.sql'
    )
    connection.executescript(initial.read_text())
    connection.execute('CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at REAL)')
    connection.execute(
        'INSERT INTO schema_migrations VALUES (?, 1)', (initial.name.removesuffix('.sql'),)
    )
    connection.executemany(
        'INSERT INTO remote_filters VALUES (?, ?, ?, ?, ?, ?)',
        [
            ('default', 'user', 'Old', 'project = OLD', 'remote', 1),
            ('other', 'user', 'Old', 'project = OTHER', 'remote', 0),
        ],
    )
    connection.execute(
        'INSERT INTO sync_log (profile_key, cache_type, scope, fetched_at, expires_at) '
        "VALUES ('default', 'remote_filters', 'user', 1, 9999999999)"
    )
    connection.commit()
    connection.close()

    for _ in range(2):
        cache = ApplicationCache(path)
        try:
            assert cache._connection.execute(
                'SELECT profile_key, label, expression, starred, filter_id '
                'FROM remote_filters ORDER BY profile_key'
            ).fetchall() == [
                ('default', 'Old', 'project = OLD', 1, None),
                ('other', 'Old', 'project = OTHER', 0, None),
            ]
            legacy_filters = cache._get('remote_filters', 'user')
            assert legacy_filters is not None
            assert legacy_filters[0].starred
            assert cache._connection.execute(
                "SELECT fetched_at, expires_at FROM sync_log WHERE cache_type = 'remote_filters'"
            ).fetchall() == [(1, 9999999999)]
        finally:
            cache.close()
