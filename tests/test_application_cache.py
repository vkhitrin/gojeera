from pathlib import Path
from unittest.mock import Mock

import pytest

from gojeera.internal.models import jira as jira_models
from gojeera.internal.store.cache import (
    CACHE_TTL_FIELDS,
    CACHE_TTL_GLOBAL_SETTINGS,
    CACHE_TTL_PROJECTS_WITH_RELEASES,
    CACHE_TTL_SERVER_INFO,
    ApplicationCache,
)

ENGINEERING_PROJECT = jira_models.JiraProject(
    id='10000',
    key='ENG',
    name='Engineering',
    project_type_key='software',
)


def _server_info() -> jira_models.JiraServerInfo:
    return jira_models.JiraServerInfo(
        base_url='https://example.atlassian.net',
        version='1',
        build_number=1,
        build_date='2026-08-08',
        server_title='Example Jira',
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


def test_cache_construction_and_profile_selection_defer_pruning(tmp_path, monkeypatch):
    prune_expired = Mock()
    monkeypatch.setattr(ApplicationCache, 'prune_expired', prune_expired)

    instance = ApplicationCache(tmp_path / 'deferred-prune.db')
    try:
        instance.set_profile('profile-1')

        prune_expired.assert_not_called()
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

    current_time = 4661.0
    assert cache.get_project_users('ENG', allow_stale=True) is None


def test_fields_cache_uses_finite_default_ttl(cache: ApplicationCache, monkeypatch):
    import gojeera.internal.store.cache as cache_module

    current_time = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: current_time)
    field = jira_models.JiraField(id='summary', key='summary', name='Summary', schema={})

    cache.set_fields([field])
    current_time += CACHE_TTL_FIELDS + 1

    assert cache.get_fields() is None
    assert cache.get_fields(allow_stale=True) == [field]


def test_startup_metadata_cache_uses_bounded_ttls(cache: ApplicationCache, monkeypatch):
    import gojeera.internal.store.cache as cache_module

    current_time = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: current_time)
    server_info = _server_info()
    global_settings = jira_models.JiraGlobalSettings(
        attachments_enabled=True,
        work_item_linking_enabled=True,
        subtasks_enabled=True,
        unassigned_work_items_allowed=False,
        voting_enabled=True,
        watching_enabled=True,
        time_tracking_enabled=True,
        time_tracking_configuration=jira_models.JiraTimeTrackingConfiguration(
            default_unit='hour',
            time_format='pretty',
            working_days_per_week=5,
            working_hours_per_day=8,
        ),
    )

    cache.set_server_info(server_info)
    cache.set_global_settings(global_settings)

    assert cache.get_server_info() == server_info
    assert cache.get_global_settings() == global_settings

    current_time += CACHE_TTL_GLOBAL_SETTINGS + 1

    assert cache.get_global_settings() is None
    assert cache.get_global_settings(allow_stale=True) is None
    assert cache.get_server_info() == server_info

    current_time = 1000.0 + CACHE_TTL_SERVER_INFO + 1

    assert cache.get_server_info() is None
    assert cache.get_server_info(allow_stale=True) is None


def test_empty_success_is_cached_to_avoid_repeated_requests(cache: ApplicationCache, monkeypatch):
    import gojeera.internal.store.cache as cache_module

    current_time = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: current_time)

    cache.set_sprints_for_project('ENG', [], ttl_seconds=120)

    assert cache.get_sprints_for_project('ENG') == []
    current_time += 121
    assert cache.get_sprints_for_project('ENG') is None
    assert cache.get_sprints_for_project('ENG', allow_stale=True) == []


def test_projects_with_releases_cache_is_profile_scoped_and_stale_while_refreshing(
    cache: ApplicationCache,
    monkeypatch,
):
    import gojeera.internal.store.cache as cache_module

    current_time = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: current_time)
    cache.set_projects_with_releases([ENGINEERING_PROJECT])

    assert cache.get_projects_with_releases() == [ENGINEERING_PROJECT]

    current_time += CACHE_TTL_PROJECTS_WITH_RELEASES + 1

    assert cache.get_projects_with_releases() is None
    assert cache.get_projects_with_releases(allow_stale=True) == [ENGINEERING_PROJECT]

    cache.set_profile('other-profile')
    assert cache.get_projects_with_releases(allow_stale=True) is None

    cache.set_profile('test-profile')
    cache.clear()
    assert cache.get_projects_with_releases(allow_stale=True) is None


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
    cache.set_server_info(_server_info())
    cache.set_projects_with_releases([ENGINEERING_PROJECT])

    assert cache.needs_refresh('projects') is False
    assert cache.needs_refresh('project_users', 'ENG') is False

    cache.clear()

    assert cache.get_projects(allow_stale=True) is None
    assert cache.get_project_users('ENG', allow_stale=True) is None
    assert cache.get_project_work_item_types('ENG', allow_stale=True) is None
    assert cache.get_project_statuses('ENG', allow_stale=True) is None
    assert cache.get_boards_for_project('ENG', allow_stale=True) is None
    assert cache.get_sprints_for_project('ENG', allow_stale=True) is None
    assert cache.get_server_info(allow_stale=True) is None
    assert cache.get_projects_with_releases(allow_stale=True) is None

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


def test_prune_expired_keeps_stale_until_hard_expiration(cache: ApplicationCache, monkeypatch):
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

    assert cache.get_project_users('ENG') is None
    assert [user.account_id for user in cache.get_project_users('ENG', allow_stale=True) or []] == [
        'eng-user'
    ]

    current_time = 4661.0
    cache.prune_expired()

    assert cache.get_project_users('ENG', allow_stale=True) is None
    assert [user.account_id for user in cache.get_project_users('OPS', allow_stale=True) or []] == [
        'ops-user'
    ]
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
