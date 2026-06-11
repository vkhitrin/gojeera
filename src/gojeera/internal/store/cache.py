from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from importlib import resources
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, TypeVar

from gojeera.internal.models.jira import (
    JiraBoard,
    JiraFilter,
    JiraFilterDict,
    JiraField,
    JiraSprint,
    JiraUser,
    JiraProject,
    WorkItemStatus,
    WorkItemType,
)
from gojeera.internal.store import migrations

CACHE_TTL_PROJECTS = 3600
CACHE_TTL_TYPES = 3600
CACHE_TTL_STATUSES = 3600
CACHE_TTL_PROJECT_USERS = 1800
CACHE_TTL_PROJECT_TYPES = 3600
CACHE_TTL_PROJECT_STATUSES = 3600
CACHE_TTL_REMOTE_FILTERS = 3600
CACHE_TTL_SPRINTS = 3600
MIGRATION_SUFFIX = '.sql'
SQLITE_BUSY_RETRIES = 3
SQLITE_BUSY_RETRY_DELAY_SECONDS = 0.05
T = TypeVar('T')

CACHE_TYPES = {
    'projects',
    'project_users',
    'types',
    'project_types',
    'statuses',
    'project_statuses',
    'remote_filters',
    'sprints',
    'boards',
    'fields',
    'search_history',
    'recent_searches',
    'recently_viewed_work_items',
}
PROFILE_CACHE_TABLES = {
    'projects',
    'users',
    'project_users',
    'work_item_types',
    'work_item_status',
    'boards',
    'sprints',
    'remote_filters',
    'fields',
    'search_history',
    'recent_searches',
    'recently_viewed_work_items',
}


class CacheMigrationError(RuntimeError):
    """Raised when a SQLite cache database migration fails."""


async def run_cache_io(operation: Callable[[], T]) -> T:
    """Run synchronous SQLite cache I/O without blocking the event loop."""
    return await asyncio.to_thread(operation)


class RetryingSQLiteConnection(sqlite3.Connection):
    """SQLite connection that retries transient lock contention."""

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        return self._retry_sqlite_operation(
            lambda: sqlite3.Connection.execute(self, sql, parameters)
        )

    def executemany(self, sql: str, parameters: Any, /) -> sqlite3.Cursor:
        return self._retry_sqlite_operation(
            lambda: sqlite3.Connection.executemany(self, sql, parameters)
        )

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        return self._retry_sqlite_operation(
            lambda: sqlite3.Connection.executescript(self, sql_script)
        )

    @staticmethod
    def _retry_sqlite_operation(operation):
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(SQLITE_BUSY_RETRIES + 1):
            try:
                return operation()
            except sqlite3.OperationalError as error:
                if 'locked' not in str(error).lower() and 'busy' not in str(error).lower():
                    raise
                last_error = error
                if attempt == SQLITE_BUSY_RETRIES:
                    break
                time.sleep(SQLITE_BUSY_RETRY_DELAY_SECONDS * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise RuntimeError('SQLite operation failed without an exception')


class ApplicationCache:
    """Application-level SQLite cache for Jira data."""

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = (
            Path(db_path).expanduser() if db_path is not None else self._default_db_path()
        )
        self._lock = threading.RLock()
        self._connection = self._connect()
        self._profile_key = 'default'
        self._default_ttls = {
            'projects': CACHE_TTL_PROJECTS,
            'types': CACHE_TTL_TYPES,
            'statuses': CACHE_TTL_STATUSES,
            'project_users': CACHE_TTL_PROJECT_USERS,
            'project_types': CACHE_TTL_PROJECT_TYPES,
            'project_statuses': CACHE_TTL_PROJECT_STATUSES,
            'remote_filters': CACHE_TTL_REMOTE_FILTERS,
            'sprints': CACHE_TTL_SPRINTS,
            'boards': CACHE_TTL_SPRINTS,
            'fields': None,
        }
        self._apply_migrations()
        self.prune_expired()

    def _default_db_path(self) -> Path:
        return Path.home() / '.cache' / 'gojeera' / 'atlassian.db'

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            factory=RetryingSQLiteConnection,
            timeout=5.0,
        )
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=5000')
        return connection

    def _apply_migrations(self) -> None:
        with self._lock:
            self._ensure_migrations_table()
            self._connection.commit()
            applied_migrations = self._get_applied_migrations()
            migration_files = sorted(
                migration
                for migration in resources.files(migrations).iterdir()
                if migration.name.endswith(MIGRATION_SUFFIX)
            )
            for migration in migration_files:
                migration_id = migration.name.removesuffix(MIGRATION_SUFFIX)
                if migration_id in applied_migrations:
                    continue
                try:
                    self._connection.executescript(f'BEGIN;\n{migration.read_text()}')
                    self._connection.execute(
                        'INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)',
                        (migration_id, time.time()),
                    )
                    self._connection.execute('COMMIT')
                except sqlite3.Error as error:
                    self._connection.execute('ROLLBACK')
                    raise CacheMigrationError(
                        f'Failed to apply cache database migration {migration.name}'
                    ) from error

    def _ensure_migrations_table(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at REAL NOT NULL
            )
            """
        )

    def _get_applied_migrations(self) -> set[str]:
        rows = self._connection.execute('SELECT id FROM schema_migrations').fetchall()
        return {str(row[0]) for row in rows}

    def set_profile(self, profile_key: str | None) -> None:
        with self._lock:
            self._profile_key = profile_key or 'default'
            self.prune_expired()

    @property
    def profile_key(self) -> str:
        return self._profile_key

    def _get(
        self,
        cache_type: str,
        identifier: str | None = None,
        *,
        allow_stale: bool = False,
    ) -> Any | None:
        self._validate_cache_type(cache_type)
        with self._lock, self._connection:
            if not allow_stale and self._needs_refresh(cache_type, identifier):
                return None
            if cache_type == 'projects':
                return self._get_projects()
            if cache_type == 'project_users':
                return self._get_users(identifier)
            if cache_type in {'types', 'project_types'}:
                return self._get_work_item_types(
                    identifier if cache_type == 'project_types' else None
                )
            if cache_type in {'statuses', 'project_statuses'}:
                return self._get_work_item_statuses(
                    identifier if cache_type == 'project_statuses' else None
                )
            if cache_type == 'sprints':
                return self._get_sprints(identifier)
            if cache_type == 'boards':
                return self._get_boards(identifier)
            if cache_type == 'remote_filters':
                return self._get_remote_filters(identifier)
            if cache_type == 'fields':
                return self._get_fields()
            return None

    def _set(
        self,
        cache_type: str,
        data: Any,
        identifier: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self._validate_cache_type(cache_type)
        ttl_seconds = self._default_ttls.get(cache_type) if ttl_seconds is None else ttl_seconds
        fetched_at = time.time()
        expires_at = None if ttl_seconds is None else fetched_at + ttl_seconds
        with self._lock, self._connection:
            if cache_type == 'projects':
                self._set_projects(data, fetched_at, expires_at)
            elif cache_type == 'project_users':
                self._set_users(data, identifier, fetched_at, expires_at)
            elif cache_type in {'types', 'project_types'}:
                self._set_work_item_types(
                    data,
                    identifier if cache_type == 'project_types' else None,
                    fetched_at,
                    expires_at,
                )
            elif cache_type in {'statuses', 'project_statuses'}:
                self._set_work_item_statuses(
                    data,
                    identifier if cache_type == 'project_statuses' else None,
                    fetched_at,
                    expires_at,
                )
            elif cache_type == 'sprints':
                self._set_sprints(data, identifier, fetched_at, expires_at)
            elif cache_type == 'boards':
                self._set_boards(data, identifier, fetched_at, expires_at)
            elif cache_type == 'remote_filters':
                self._set_remote_filters(data, identifier, fetched_at, expires_at)
            elif cache_type == 'fields':
                self._set_fields(data)
            self._record_sync(cache_type, identifier, fetched_at, expires_at)

    def needs_refresh(self, cache_type: str, identifier: str | None = None) -> bool:
        self._validate_cache_type(cache_type)
        with self._lock:
            return self._needs_refresh(cache_type, identifier)

    def get_projects(self, *, allow_stale: bool = False) -> list[JiraProject] | None:
        return self._get('projects', allow_stale=allow_stale)

    def set_projects(self, projects: list[JiraProject], ttl_seconds: int | None = None) -> None:
        self._set('projects', projects, ttl_seconds=ttl_seconds)

    def get_work_item_types(self, *, allow_stale: bool = False) -> list[WorkItemType] | None:
        return self._get('types', allow_stale=allow_stale)

    def set_work_item_types(
        self, work_item_types: list[WorkItemType], ttl_seconds: int | None = None
    ) -> None:
        self._set('types', work_item_types, ttl_seconds=ttl_seconds)

    def get_statuses(self, *, allow_stale: bool = False) -> list[WorkItemStatus] | None:
        return self._get('statuses', allow_stale=allow_stale)

    def set_statuses(self, statuses: list[WorkItemStatus], ttl_seconds: int | None = None) -> None:
        self._set('statuses', statuses, ttl_seconds=ttl_seconds)

    def get_fields(self, *, allow_stale: bool = False) -> list[JiraField] | None:
        return self._get('fields', allow_stale=allow_stale)

    def set_fields(self, fields: list[JiraField], ttl_seconds: int | None = None) -> None:
        self._set('fields', fields, ttl_seconds=ttl_seconds)

    def get_remote_filters(
        self, account_id: str, *, allow_stale: bool = False
    ) -> list[JiraFilter] | None:
        return self._get('remote_filters', account_id, allow_stale=allow_stale)

    def set_remote_filters(
        self,
        account_id: str,
        filters: Sequence[JiraFilter | JiraFilterDict],
        ttl_seconds: int | None = None,
    ) -> None:
        self._set('remote_filters', filters, account_id, ttl_seconds)

    def get_project_users(
        self, project_key: str, *, allow_stale: bool = False
    ) -> list[JiraUser] | None:
        return self._get('project_users', project_key, allow_stale=allow_stale)

    def set_project_users(
        self, project_key: str, users: list[JiraUser], ttl_seconds: int | None = None
    ) -> None:
        self._set('project_users', users, project_key, ttl_seconds)

    def get_project_work_item_types(
        self, project_key: str, *, allow_stale: bool = False
    ) -> list[WorkItemType] | None:
        return self._get('project_types', project_key, allow_stale=allow_stale)

    def set_project_work_item_types(
        self, project_key: str, work_item_types: list[WorkItemType], ttl_seconds: int | None = None
    ) -> None:
        self._set('project_types', work_item_types, project_key, ttl_seconds)

    def get_project_statuses(self, project_key: str, *, allow_stale: bool = False) -> Any | None:
        return self._get('project_statuses', project_key, allow_stale=allow_stale)

    def set_project_statuses(
        self, project_key: str, statuses: Any, ttl_seconds: int | None = None
    ) -> None:
        self._set('project_statuses', statuses, project_key, ttl_seconds)

    def get_boards_for_project(
        self, project_key: str, *, allow_stale: bool = False
    ) -> list[JiraBoard] | None:
        return self._get('boards', project_key, allow_stale=allow_stale)

    def set_boards_for_project(
        self,
        project_key: str,
        boards: Sequence[JiraBoard | dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        self._set('boards', boards, project_key, ttl_seconds)

    def get_sprints_for_project(
        self, project_key: str, *, allow_stale: bool = False
    ) -> list[JiraSprint] | None:
        return self._get('sprints', project_key, allow_stale=allow_stale)

    def set_sprints_for_project(
        self, project_key: str, sprints: list[Any], ttl_seconds: int | None = None
    ) -> None:
        self._set('sprints', sprints, project_key, ttl_seconds)

    def add_search_history(self, mode: str, query: str) -> None:
        if mode not in {'text', 'jql'}:
            raise ValueError(f'Unsupported search history mode: {mode}')

        normalized_query = query.strip()
        if not normalized_query:
            return

        searched_at = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO search_history (profile_key, mode, query, searched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_key, mode, query) DO UPDATE SET
                    searched_at = excluded.searched_at
                """,
                (self._profile_key, mode, normalized_query, searched_at),
            )
            self._connection.execute(
                """
                DELETE FROM search_history
                WHERE profile_key = ?
                  AND mode = ?
                  AND query NOT IN (
                      SELECT query FROM search_history
                      WHERE profile_key = ? AND mode = ?
                      ORDER BY searched_at DESC
                      LIMIT 10
                  )
                """,
                (self._profile_key, mode, self._profile_key, mode),
            )

    def get_search_history(self, mode: str) -> list[str]:
        if mode not in {'text', 'jql'}:
            raise ValueError(f'Unsupported search history mode: {mode}')

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT query FROM search_history
                WHERE profile_key = ? AND mode = ?
                ORDER BY searched_at DESC
                LIMIT 10
                """,
                (self._profile_key, mode),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def add_recent_search(self, jql: str, source_mode: str | None = None) -> None:
        normalized_jql = jql.strip()
        if not normalized_jql:
            return

        normalized_source_mode = (source_mode or '').strip() or None
        if normalized_source_mode not in {None, 'basic', 'text', 'jql'}:
            raise ValueError(f'Unsupported recent search source mode: {source_mode}')

        searched_at = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO recent_searches (profile_key, jql, source_mode, searched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_key, jql) DO UPDATE SET
                    source_mode = excluded.source_mode,
                    searched_at = excluded.searched_at
                """,
                (self._profile_key, normalized_jql, normalized_source_mode, searched_at),
            )
            self._connection.execute(
                """
                DELETE FROM recent_searches
                WHERE profile_key = ?
                  AND jql NOT IN (
                      SELECT jql FROM recent_searches
                      WHERE profile_key = ?
                      ORDER BY searched_at DESC
                      LIMIT 10
                  )
                """,
                (self._profile_key, self._profile_key),
            )

    def get_recent_searches(self) -> list[dict[str, str | float | None]]:
        rows = self._fetch_recent_profile_rows(
            """
            SELECT jql, source_mode, searched_at
            FROM recent_searches
            WHERE profile_key = ?
            ORDER BY searched_at DESC
            LIMIT 10
            """
        )
        return [
            {
                'jql': str(row[0]),
                'source_mode': row[1],
                'searched_at': float(row[2]),
            }
            for row in rows
        ]

    def add_recently_viewed_work_item(
        self,
        work_item_key: str,
        summary: str | None = None,
        work_item_type: str | None = None,
    ) -> None:
        normalized_key = work_item_key.strip().upper()
        if not normalized_key:
            return

        viewed_at = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO recently_viewed_work_items (
                    profile_key, work_item_key, work_item_type, summary, viewed_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile_key, work_item_key) DO UPDATE SET
                    work_item_type = excluded.work_item_type,
                    summary = excluded.summary,
                    viewed_at = excluded.viewed_at
                """,
                (
                    self._profile_key,
                    normalized_key,
                    (work_item_type or '').strip() or None,
                    (summary or '').strip() or None,
                    viewed_at,
                ),
            )
            self._connection.execute(
                """
                DELETE FROM recently_viewed_work_items
                WHERE profile_key = ?
                  AND work_item_key NOT IN (
                      SELECT work_item_key FROM recently_viewed_work_items
                      WHERE profile_key = ?
                      ORDER BY viewed_at DESC
                      LIMIT 10
                  )
                """,
                (self._profile_key, self._profile_key),
            )

    def get_recently_viewed_work_items(self) -> list[dict[str, str | float | None]]:
        rows = self._fetch_recent_profile_rows(
            """
            SELECT work_item_key, work_item_type, summary, viewed_at
            FROM recently_viewed_work_items
            WHERE profile_key = ?
            ORDER BY viewed_at DESC
            LIMIT 10
            """
        )
        return [
            {
                'key': str(row[0]),
                'work_item_type': row[1],
                'summary': row[2],
                'viewed_at': float(row[3]),
            }
            for row in rows
        ]

    def _fetch_recent_profile_rows(self, query: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(query, (self._profile_key,)).fetchall()

    def invalidate_profile(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                'DELETE FROM sync_log WHERE profile_key = ?', (self._profile_key,)
            )

    def _validate_cache_type(self, cache_type: str) -> None:
        if cache_type not in CACHE_TYPES:
            raise ValueError(f'Unsupported cache type: {cache_type}')

    def _needs_refresh(self, cache_type: str, identifier: str | None = None) -> bool:
        row = self._connection.execute(
            """
            SELECT expires_at FROM sync_log
            WHERE profile_key = ? AND cache_type = ? AND scope = ?
            """,
            (
                self._profile_key,
                self._sync_cache_type(cache_type),
                self._sync_scope(cache_type, identifier),
            ),
        ).fetchone()
        return row is None or (row[0] is not None and time.time() > row[0])

    def record_failure(
        self,
        cache_type: str,
        identifier: str | None = None,
        error_message: str | None = None,
        retry_after_seconds: int = 300,
    ) -> None:
        self._validate_cache_type(cache_type)
        fetched_at = time.time()
        expires_at = fetched_at + retry_after_seconds
        with self._lock, self._connection:
            self._upsert_sync_log(
                cache_type,
                identifier,
                fetched_at,
                expires_at,
                status='failed',
                error_message=error_message,
            )

    def _record_sync(
        self,
        cache_type: str,
        identifier: str | None,
        fetched_at: float,
        expires_at: float | None,
    ) -> None:
        self._upsert_sync_log(
            cache_type,
            identifier,
            fetched_at,
            expires_at,
            status='success',
        )

    def _upsert_sync_log(
        self,
        cache_type: str,
        identifier: str | None,
        fetched_at: float,
        expires_at: float | None,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO sync_log (
                profile_key, cache_type, scope, fetched_at, expires_at, status, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_key, cache_type, scope) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                expires_at = excluded.expires_at,
                status = excluded.status,
                error_message = excluded.error_message
            """,
            (
                self._profile_key,
                self._sync_cache_type(cache_type),
                self._sync_scope(cache_type, identifier),
                fetched_at,
                expires_at,
                status,
                error_message,
            ),
        )

    @staticmethod
    def _db_scope(identifier: str | None = None) -> str:
        return identifier or ''

    @staticmethod
    def _sync_cache_type(cache_type: str) -> str:
        return {
            'project_users': 'project_users',
            'project_types': 'work_item_types',
            'types': 'work_item_types',
            'project_statuses': 'work_item_status',
            'statuses': 'work_item_status',
        }.get(cache_type, cache_type)

    @staticmethod
    def _sync_scope(cache_type: str, identifier: str | None = None) -> str:
        if cache_type in {
            'project_users',
            'project_types',
            'project_statuses',
            'remote_filters',
            'boards',
            'sprints',
        }:
            return identifier or ''
        return ''

    def _get_projects(self) -> list[JiraProject] | None:
        rows = self._connection.execute(
            'SELECT id, key, name, project_type_key FROM projects WHERE profile_key = ?',
            (self._profile_key,),
        ).fetchall()
        return [
            JiraProject(id=str(row[0]), key=str(row[1]), name=str(row[2]), project_type_key=row[3])
            for row in rows
        ] or None

    def _set_projects(
        self, projects: list[JiraProject], fetched_at: float, expires_at: float | None
    ) -> None:
        self._connection.execute('DELETE FROM projects WHERE profile_key = ?', (self._profile_key,))
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO projects (profile_key, id, key, name, project_type_key)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(self._profile_key, p.id, p.key, p.name, p.project_type_key) for p in projects],
        )

    def _get_users(self, project_key: str | None) -> list[JiraUser] | None:
        if project_key is None:
            return None
        rows = self._connection.execute(
            """
            SELECT users.account_id, users.active, users.display_name, users.email
            FROM users
            INNER JOIN project_users
                ON project_users.profile_key = users.profile_key
                AND project_users.account_id = users.account_id
            WHERE project_users.profile_key = ? AND project_users.project_key = ?
            ORDER BY users.display_name
            """,
            (self._profile_key, project_key),
        ).fetchall()
        return [
            JiraUser(account_id=row[0], active=bool(row[1]), display_name=row[2], email=row[3])
            for row in rows
        ] or None

    def _set_users(
        self,
        users: list[JiraUser],
        project_key: str | None,
        fetched_at: float,
        expires_at: float | None,
    ) -> None:
        if project_key is None:
            return
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO users (profile_key, account_id, active, display_name, email)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (self._profile_key, u.account_id, int(u.active), u.display_name, u.email)
                for u in users
            ],
        )
        self._connection.execute(
            'DELETE FROM project_users WHERE profile_key = ? AND project_key = ?',
            (self._profile_key, project_key),
        )
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO project_users (profile_key, project_key, account_id)
            VALUES (?, ?, ?)
            """,
            [(self._profile_key, project_key, u.account_id) for u in users],
        )

    def _get_work_item_types(self, project_key: str | None) -> list[WorkItemType] | None:
        rows = self._connection.execute(
            """
            SELECT id, name, subtask, hierarchy_level, scope_project_id, scope_project_key,
                   scope_project_name
            FROM work_item_types WHERE profile_key = ? AND project_key = ?
            """,
            (self._profile_key, self._db_scope(project_key)),
        ).fetchall()
        result = []
        for row in rows:
            scope_project = (
                JiraProject(id=row[4], key=row[5], name=row[6])
                if row[4] and row[5] and row[6]
                else None
            )
            result.append(
                WorkItemType(
                    id=row[0],
                    name=row[1],
                    subtask=bool(row[2]),
                    hierarchy_level=row[3],
                    scope_project=scope_project,
                )
            )
        return result or None

    def _set_work_item_types(
        self,
        types: list[WorkItemType],
        project_key: str | None,
        fetched_at: float,
        expires_at: float | None,
    ) -> None:
        self._connection.execute(
            'DELETE FROM work_item_types WHERE profile_key = ? AND project_key = ?',
            (self._profile_key, self._db_scope(project_key)),
        )
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO work_item_types
            (profile_key, id, project_key, name, subtask, hierarchy_level, scope_project_id,
             scope_project_key, scope_project_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    self._profile_key,
                    item.id,
                    self._db_scope(project_key),
                    item.name,
                    int(item.subtask),
                    item.hierarchy_level,
                    item.scope_project.id if item.scope_project else None,
                    item.scope_project.key if item.scope_project else None,
                    item.scope_project.name if item.scope_project else None,
                )
                for item in types
            ],
        )

    def _get_work_item_statuses(self, project_key: str | None) -> Any | None:
        rows = self._connection.execute(
            """
            SELECT id, work_item_type_id, work_item_type_name, name, description,
                   status_category_color
            FROM work_item_status WHERE profile_key = ? AND project_key = ?
            """,
            (self._profile_key, self._db_scope(project_key)),
        ).fetchall()
        if not rows:
            return None
        if project_key is None:
            return [
                WorkItemStatus(
                    id=row[0], name=row[3], description=row[4], status_category_color=row[5]
                )
                for row in rows
            ]
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            type_id = row[1] or ''
            grouped.setdefault(
                type_id, {'work_item_type_name': row[2], 'work_item_type_statuses': []}
            )['work_item_type_statuses'].append(
                WorkItemStatus(
                    id=row[0], name=row[3], description=row[4], status_category_color=row[5]
                )
            )
        return grouped

    def _set_work_item_statuses(
        self, statuses: Any, project_key: str | None, fetched_at: float, expires_at: float | None
    ) -> None:
        self._connection.execute(
            'DELETE FROM work_item_status WHERE profile_key = ? AND project_key = ?',
            (self._profile_key, self._db_scope(project_key)),
        )
        records = []
        if project_key is None:
            records = [
                (s.id, '', None, s.name, s.description, s.status_category_color) for s in statuses
            ]
        else:
            for type_id, data in statuses.items():
                for status in data.get('work_item_type_statuses', []):
                    records.append(
                        (
                            status.id,
                            type_id,
                            data.get('work_item_type_name'),
                            status.name,
                            status.description,
                            status.status_category_color,
                        )
                    )
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO work_item_status
            (profile_key, id, project_key, work_item_type_id, work_item_type_name, name,
             description, status_category_color)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    self._profile_key,
                    r[0],
                    self._db_scope(project_key),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                )
                for r in records
            ],
        )

    def _get_sprints(self, project_key: str | None) -> list[Any] | None:
        rows = self._connection.execute(
            """
            SELECT id, name, state, board_id, goal, start_date, end_date, complete_date
            FROM sprints WHERE profile_key = ? AND project_key = ?
            """,
            (self._profile_key, self._db_scope(project_key)),
        ).fetchall()
        if not rows:
            return None
        return [
            JiraSprint(
                id=row[0],
                name=row[1],
                state=row[2],
                boardId=row[3],
                goal=row[4],
                startDate=row[5],
                endDate=row[6],
                completeDate=row[7],
            )
            for row in rows
        ]

    def _set_sprints(
        self,
        sprints: list[Any],
        project_key: str | None,
        fetched_at: float,
        expires_at: float | None,
    ) -> None:
        self._connection.execute(
            'DELETE FROM sprints WHERE profile_key = ? AND project_key = ?',
            (self._profile_key, self._db_scope(project_key)),
        )
        records = []
        for sprint in sprints:
            if isinstance(sprint, dict):
                sprint_id = sprint.get('id')
                name = sprint.get('name')
                state = sprint.get('state')
                board_id = sprint.get('boardId') or 0
                goal = sprint.get('goal')
                start_date = sprint.get('startDate')
                end_date = sprint.get('endDate')
                complete_date = sprint.get('completeDate')
            else:
                sprint_id, name, state, board_id = (
                    sprint.id,
                    sprint.name,
                    sprint.state,
                    sprint.boardId,
                )
                goal, start_date, end_date, complete_date = (
                    sprint.goal,
                    sprint.startDate,
                    sprint.endDate,
                    sprint.completeDate,
                )
            if sprint_id and name and state:
                records.append(
                    (
                        self._profile_key,
                        sprint_id,
                        board_id,
                        self._db_scope(project_key),
                        name,
                        state,
                        goal,
                        start_date,
                        end_date,
                        complete_date,
                    )
                )
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO sprints
            (profile_key, id, board_id, project_key, name, state, goal, start_date, end_date,
             complete_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )

    def _get_boards(self, project_key: str | None) -> list[JiraBoard] | None:
        rows = self._connection.execute(
            """
            SELECT id, name, type
            FROM boards
            WHERE profile_key = ? AND project_key = ?
            ORDER BY name
            """,
            (self._profile_key, self._db_scope(project_key)),
        ).fetchall()
        return [
            JiraBoard(id=row[0], name=row[1], type=row[2], projectKey=project_key) for row in rows
        ] or None

    def _set_boards(
        self,
        boards: Sequence[JiraBoard | dict[str, Any]],
        project_key: str | None,
        fetched_at: float,
        expires_at: float | None,
    ) -> None:
        self._connection.execute(
            'DELETE FROM boards WHERE profile_key = ? AND project_key = ?',
            (self._profile_key, self._db_scope(project_key)),
        )
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO boards
            (profile_key, id, project_key, name, type, supports_sprints)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    self._profile_key,
                    board.id if isinstance(board, JiraBoard) else board.get('id'),
                    self._db_scope(project_key),
                    board.name if isinstance(board, JiraBoard) else board.get('name', ''),
                    board.type if isinstance(board, JiraBoard) else board.get('type'),
                    None,
                )
                for board in boards
                if (board.id if isinstance(board, JiraBoard) else board.get('id')) is not None
            ],
        )

    def _get_remote_filters(self, account_id: str | None) -> list[JiraFilter] | None:
        if account_id is None:
            return None
        rows = self._connection.execute(
            """
            SELECT label, expression, source, starred
            FROM remote_filters
            WHERE profile_key = ? AND account_id = ?
            ORDER BY label
            """,
            (self._profile_key, account_id),
        ).fetchall()
        return [
            JiraFilter(label=row[0], expression=row[1], source=row[2], starred=bool(row[3]))
            for row in rows
        ] or None

    def _set_remote_filters(
        self,
        filters: Sequence[JiraFilter | JiraFilterDict],
        account_id: str | None,
        fetched_at: float,
        expires_at: float | None,
    ) -> None:
        if account_id is None:
            return
        self._connection.execute(
            'DELETE FROM remote_filters WHERE profile_key = ? AND account_id = ?',
            (self._profile_key, account_id),
        )
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO remote_filters
            (profile_key, account_id, label, expression, source, starred)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    self._profile_key,
                    account_id,
                    filter_data.label
                    if isinstance(filter_data, JiraFilter)
                    else filter_data.get('label', ''),
                    filter_data.expression
                    if isinstance(filter_data, JiraFilter)
                    else filter_data.get('expression', ''),
                    filter_data.source
                    if isinstance(filter_data, JiraFilter)
                    else filter_data.get('source', 'remote'),
                    int(
                        filter_data.starred
                        if isinstance(filter_data, JiraFilter)
                        else bool(filter_data.get('starred', False))
                    ),
                )
                for filter_data in filters
                if (
                    filter_data.label
                    if isinstance(filter_data, JiraFilter)
                    else filter_data.get('label')
                )
                and (
                    filter_data.expression
                    if isinstance(filter_data, JiraFilter)
                    else filter_data.get('expression')
                )
            ],
        )

    def _get_fields(self) -> list[JiraField] | None:
        rows = self._connection.execute(
            """
            SELECT id, key, name, description, schema_json
            FROM fields
            WHERE profile_key = ?
            ORDER BY name
            """,
            (self._profile_key,),
        ).fetchall()
        return [
            JiraField(
                id=row[0],
                key=row[1],
                name=row[2],
                description=row[3],
                schema=json.loads(row[4] or '{}'),
            )
            for row in rows
        ] or None

    def _set_fields(self, fields: list[JiraField]) -> None:
        self._connection.execute('DELETE FROM fields WHERE profile_key = ?', (self._profile_key,))
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO fields (profile_key, id, key, name, description, schema_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    self._profile_key,
                    field.id,
                    field.key,
                    field.name,
                    field.description,
                    json.dumps(field.schema or {}, sort_keys=True),
                )
                for field in fields
            ],
        )

    def clear(self) -> None:
        with self._lock, self._connection:
            for table_name in PROFILE_CACHE_TABLES:
                self._connection.execute(
                    f'DELETE FROM {table_name} WHERE profile_key = ?', (self._profile_key,)
                )
            self.invalidate_profile()

    def prune_expired(self) -> None:
        """Remove expired cached data and associated sync metadata for this profile."""
        with self._lock, self._connection:
            expired_rows = self._connection.execute(
                """
                SELECT cache_type, scope FROM sync_log
                WHERE profile_key = ? AND expires_at IS NOT NULL AND expires_at < ?
                """,
                (self._profile_key, time.time()),
            ).fetchall()
            for cache_type, scope in expired_rows:
                self._delete_cache_scope(str(cache_type), str(scope))
            self._connection.executemany(
                """
                DELETE FROM sync_log
                WHERE profile_key = ? AND cache_type = ? AND scope = ?
                """,
                [(self._profile_key, cache_type, scope) for cache_type, scope in expired_rows],
            )
            self._delete_orphaned_users()

    def _delete_cache_scope(self, cache_type: str, scope: str) -> None:
        if cache_type == 'projects':
            self._connection.execute(
                'DELETE FROM projects WHERE profile_key = ?', (self._profile_key,)
            )
        elif cache_type == 'project_users':
            self._connection.execute(
                'DELETE FROM project_users WHERE profile_key = ? AND project_key = ?',
                (self._profile_key, scope),
            )
        elif cache_type == 'work_item_types':
            self._connection.execute(
                'DELETE FROM work_item_types WHERE profile_key = ? AND project_key = ?',
                (self._profile_key, scope),
            )
        elif cache_type == 'work_item_status':
            self._connection.execute(
                'DELETE FROM work_item_status WHERE profile_key = ? AND project_key = ?',
                (self._profile_key, scope),
            )
        elif cache_type == 'boards':
            self._connection.execute(
                'DELETE FROM boards WHERE profile_key = ? AND project_key = ?',
                (self._profile_key, scope),
            )
        elif cache_type == 'sprints':
            self._connection.execute(
                'DELETE FROM sprints WHERE profile_key = ? AND project_key = ?',
                (self._profile_key, scope),
            )
        elif cache_type == 'remote_filters':
            self._connection.execute(
                'DELETE FROM remote_filters WHERE profile_key = ? AND account_id = ?',
                (self._profile_key, scope),
            )
        elif cache_type == 'fields':
            self._connection.execute(
                'DELETE FROM fields WHERE profile_key = ?', (self._profile_key,)
            )

    def _delete_orphaned_users(self) -> None:
        self._connection.execute(
            """
            DELETE FROM users
            WHERE profile_key = ?
              AND NOT EXISTS (
                  SELECT 1 FROM project_users
                  WHERE project_users.profile_key = users.profile_key
                    AND project_users.account_id = users.account_id
              )
            """,
            (self._profile_key,),
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()


_global_cache: ApplicationCache | None = None


def get_cache() -> ApplicationCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = ApplicationCache()
    return _global_cache
