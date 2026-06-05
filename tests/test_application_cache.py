from pathlib import Path

import pytest

from gojeera.internal.models import jira as jira_models
from gojeera.internal.store.cache import ApplicationCache

ENGINEERING_PROJECT = jira_models.JiraProject(
    id='10000',
    key='ENG',
    name='Engineering',
    project_type_key='software',
)


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / 'atlassian.db'


@pytest.fixture
def cache(cache_path: Path):
    instance = ApplicationCache(cache_path)
    instance.set_profile('test-profile')
    try:
        yield instance
    finally:
        instance.close()


def test_scoped_cache_entry_expires_after_ttl(cache: ApplicationCache, monkeypatch):
    import gojeera.internal.store.cache as cache_module

    current_time = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: current_time)

    user = jira_models.JiraUser(account_id='eng-1', active=True, display_name='Eng User')
    cache.set_project_users('ENG', [user], ttl_seconds=60)

    assert cache.get_project_users('ENG') == [user]

    current_time = 1061.0

    assert cache.get_project_users('ENG') is None
    assert cache.get_project_users('ENG', allow_stale=True) == [user]


def test_clear_removes_profile_data_and_sync_metadata(cache: ApplicationCache):
    cache.set_projects([jira_models.JiraProject(id='10000', key='ENG', name='Engineering')])
    cache.set_project_users(
        'ENG', [jira_models.JiraUser(account_id='user-1', active=True, display_name='User One')]
    )
    cache.set_project_work_item_types('ENG', [jira_models.WorkItemType(id='1', name='Bug')])
    cache.set_project_statuses(
        'ENG', {'1': {'work_item_type_name': 'Bug', 'work_item_type_statuses': []}}
    )
    cache.set_boards_for_project('ENG', [{'id': 1, 'name': 'ENG Scrum', 'type': 'scrum'}])
    cache.set_sprints_for_project(
        'ENG', [jira_models.JiraSprint(id=1, name='Sprint 1', state='active', boardId=1)]
    )

    assert cache.needs_refresh('projects') is False
    assert cache.needs_refresh('project_users', 'ENG') is False

    cache.clear()

    assert cache.get_projects(allow_stale=True) is None
    assert cache.get_project_users('ENG', allow_stale=True) is None
    assert cache.get_project_work_item_types('ENG', allow_stale=True) is None
    assert cache.get_project_statuses('ENG', allow_stale=True) is None
    assert cache.get_boards_for_project('ENG', allow_stale=True) is None
    assert cache.get_sprints_for_project('ENG', allow_stale=True) is None

    sync_count = cache._connection.execute(
        'SELECT COUNT(*) FROM sync_log WHERE profile_key = ?', (cache.profile_key,)
    ).fetchone()[0]
    assert sync_count == 0


def test_multiple_project_scopes_do_not_overlap(cache: ApplicationCache):
    cache.set_boards_for_project('ENG', [{'id': 1, 'name': 'Shared Board', 'type': 'scrum'}])
    cache.set_boards_for_project('OPS', [{'id': 1, 'name': 'Shared Board', 'type': 'scrum'}])
    cache.set_project_users(
        'ENG', [jira_models.JiraUser(account_id='eng-user', active=True, display_name='Eng User')]
    )
    cache.set_project_users(
        'OPS', [jira_models.JiraUser(account_id='ops-user', active=True, display_name='Ops User')]
    )
    cache.set_project_work_item_types('ENG', [jira_models.WorkItemType(id='1', name='Bug')])
    cache.set_project_work_item_types('OPS', [jira_models.WorkItemType(id='2', name='Task')])
    cache.set_project_statuses(
        'ENG',
        {
            '1': {
                'work_item_type_name': 'Bug',
                'work_item_type_statuses': [jira_models.WorkItemStatus(id='10', name='Open')],
            }
        },
    )
    cache.set_project_statuses(
        'OPS',
        {
            '2': {
                'work_item_type_name': 'Task',
                'work_item_type_statuses': [jira_models.WorkItemStatus(id='20', name='Done')],
            }
        },
    )

    assert [board.id for board in cache.get_boards_for_project('ENG') or []] == [1]
    assert [board.id for board in cache.get_boards_for_project('OPS') or []] == [1]
    assert [user.account_id for user in cache.get_project_users('ENG') or []] == ['eng-user']
    assert [user.account_id for user in cache.get_project_users('OPS') or []] == ['ops-user']
    assert [item.name for item in cache.get_project_work_item_types('ENG') or []] == ['Bug']
    assert [item.name for item in cache.get_project_work_item_types('OPS') or []] == ['Task']
    assert list((cache.get_project_statuses('ENG') or {}).keys()) == ['1']
    assert list((cache.get_project_statuses('OPS') or {}).keys()) == ['2']


def test_cache_persists_across_instances(cache_path: Path):
    first = ApplicationCache(cache_path)
    first.set_profile('test-profile')
    first.set_projects([ENGINEERING_PROJECT])
    first.set_work_item_types([jira_models.WorkItemType(id='1', name='Bug')])
    first.close()

    second = ApplicationCache(cache_path)
    second.set_profile('test-profile')
    try:
        assert second.get_projects() == [ENGINEERING_PROJECT]
        assert second.get_work_item_types() == [jira_models.WorkItemType(id='1', name='Bug')]
    finally:
        second.close()


def test_migrations_are_idempotent(cache_path: Path):
    first = ApplicationCache(cache_path)
    first.close()

    second = ApplicationCache(cache_path)
    try:
        migration_rows = second._connection.execute(
            'SELECT id, COUNT(*) FROM schema_migrations GROUP BY id'
        ).fetchall()
        assert migration_rows
        assert all(count == 1 for _, count in migration_rows)
    finally:
        second.close()


def test_prune_expired_removes_only_expired_scopes(cache: ApplicationCache, monkeypatch):
    import gojeera.internal.store.cache as cache_module

    current_time = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: current_time)

    cache.set_project_users(
        'ENG',
        [jira_models.JiraUser(account_id='eng-user', active=True, display_name='Eng User')],
        ttl_seconds=60,
    )
    cache.set_project_users(
        'OPS',
        [jira_models.JiraUser(account_id='ops-user', active=True, display_name='Ops User')],
        ttl_seconds=120,
    )

    current_time = 1061.0
    cache.prune_expired()

    assert cache.get_project_users('ENG', allow_stale=True) is None
    assert [user.account_id for user in cache.get_project_users('OPS') or []] == ['ops-user']
    assert (
        cache._connection.execute(
            "SELECT COUNT(*) FROM sync_log WHERE profile_key = ? AND scope = 'ENG'",
            (cache.profile_key,),
        ).fetchone()[0]
        == 0
    )
    assert (
        cache._connection.execute(
            "SELECT COUNT(*) FROM sync_log WHERE profile_key = ? AND scope = 'OPS'",
            (cache.profile_key,),
        ).fetchone()[0]
        == 1
    )


def test_global_users_cache_type_is_not_supported(cache: ApplicationCache):
    with pytest.raises(ValueError, match='Unsupported cache type: users'):
        cache.needs_refresh('users')
