from importlib import resources
import sqlite3

from gojeera.internal.store import migrations
from gojeera.internal.store.cache import ApplicationCache, MIGRATION_SUFFIX, PROFILE_CACHE_TABLES


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
        assert {'schema_migrations', 'sync_log', *PROFILE_CACHE_TABLES} <= tables

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


def test_project_type_key_migration_invalidates_stale_project_cache(tmp_path):
    db_path = tmp_path / 'atlassian.db'
    connection = sqlite3.connect(db_path)
    try:
        initial_migration = resources.files(migrations).joinpath(
            '202605221538050003_initial_atlassian_cache_schema.sql'
        )
        initial_migration_id = initial_migration.name.removesuffix(MIGRATION_SUFFIX)
        connection.executescript(initial_migration.read_text())
        connection.execute(
            'CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at REAL NOT NULL)'
        )
        connection.execute(
            'INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)',
            (initial_migration_id, 1.0),
        )
        connection.execute(
            """
            INSERT INTO projects (profile_key, id, key, name)
            VALUES ('profile-1', '10000', 'SUP', 'Support')
            """
        )
        connection.execute(
            """
            INSERT INTO sync_log (profile_key, cache_type, scope, fetched_at, expires_at)
            VALUES ('profile-1', 'projects', '', 1.0, 9999999999.0)
            """
        )
        connection.commit()
    finally:
        connection.close()

    cache = ApplicationCache(db_path)
    try:
        cache.set_profile('profile-1')
        assert cache.get_projects(allow_stale=True) is None
        assert cache.needs_refresh('projects') is True
    finally:
        cache.close()
