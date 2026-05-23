from importlib import resources

from gojeera.internal.store import migrations
from gojeera.internal.store.cache import ApplicationCache, MIGRATION_SUFFIX


def test_sqlite_cache_migrations_apply_successfully(tmp_path):
    cache = ApplicationCache(tmp_path / 'atlassian.db')
    try:
        connection = cache._connection

        applied_migrations = {
            row[0] for row in connection.execute('SELECT id FROM schema_migrations').fetchall()
        }
        expected_migrations = {
            migration.name.removesuffix(MIGRATION_SUFFIX)
            for migration in resources.files(migrations).iterdir()
            if migration.name.endswith(MIGRATION_SUFFIX)
        }
        assert applied_migrations == expected_migrations

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            'schema_migrations',
            'sync_log',
            'projects',
            'users',
            'project_users',
            'work_item_types',
            'work_item_status',
            'boards',
            'sprints',
            'remote_filters',
            'fields',
        } <= tables

        users_columns = {
            row[1] for row in connection.execute('PRAGMA table_info(users)').fetchall()
        }
        assert 'project_key' not in users_columns
        assert {'profile_key', 'account_id', 'display_name', 'email', 'active'} <= users_columns

        project_users_columns = {
            row[1] for row in connection.execute('PRAGMA table_info(project_users)').fetchall()
        }
        assert {'profile_key', 'project_key', 'account_id'} <= project_users_columns
    finally:
        cache.close()
