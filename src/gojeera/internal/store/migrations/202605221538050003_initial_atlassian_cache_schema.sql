CREATE TABLE IF NOT EXISTS sync_log (
    profile_key TEXT NOT NULL,
    cache_type TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    fetched_at REAL NOT NULL,
    expires_at REAL,
    status TEXT NOT NULL DEFAULT 'success' CHECK (
        status IN ('success', 'failed')
    ),
    error_message TEXT,
    PRIMARY KEY (profile_key, cache_type, scope)
);

CREATE INDEX IF NOT EXISTS idx_sync_log_profile_expires
ON sync_log (profile_key, expires_at);

CREATE TABLE IF NOT EXISTS projects (
    profile_key TEXT NOT NULL,
    id TEXT NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (profile_key, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_profile_key
ON projects (profile_key, key);

CREATE TABLE IF NOT EXISTS users (
    profile_key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    display_name TEXT NOT NULL,
    email TEXT,
    PRIMARY KEY (profile_key, account_id)
);

CREATE TABLE IF NOT EXISTS project_users (
    profile_key TEXT NOT NULL,
    project_key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    PRIMARY KEY (profile_key, project_key, account_id),
    FOREIGN KEY (profile_key, account_id)
    REFERENCES users (profile_key, account_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS work_item_types (
    profile_key TEXT NOT NULL,
    id TEXT NOT NULL,
    project_key TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    subtask INTEGER NOT NULL DEFAULT 0 CHECK (subtask IN (0, 1)),
    hierarchy_level INTEGER,
    scope_project_id TEXT,
    scope_project_key TEXT,
    scope_project_name TEXT,
    PRIMARY KEY (profile_key, project_key, id)
);

CREATE TABLE IF NOT EXISTS work_item_status (
    profile_key TEXT NOT NULL,
    id TEXT NOT NULL,
    project_key TEXT NOT NULL DEFAULT '',
    work_item_type_id TEXT NOT NULL DEFAULT '',
    work_item_type_name TEXT,
    name TEXT NOT NULL,
    description TEXT,
    status_category_color TEXT,
    PRIMARY KEY (profile_key, project_key, work_item_type_id, id)
);

CREATE TABLE IF NOT EXISTS boards (
    profile_key TEXT NOT NULL,
    id INTEGER NOT NULL,
    project_key TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    type TEXT,
    supports_sprints INTEGER CHECK (supports_sprints IN (0, 1)),
    PRIMARY KEY (profile_key, project_key, id)
);

CREATE TABLE IF NOT EXISTS sprints (
    profile_key TEXT NOT NULL,
    id INTEGER NOT NULL,
    board_id INTEGER NOT NULL,
    project_key TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    state TEXT NOT NULL,
    goal TEXT,
    start_date TEXT,
    end_date TEXT,
    complete_date TEXT,
    PRIMARY KEY (profile_key, project_key, id)
);

CREATE INDEX IF NOT EXISTS idx_sprints_profile_board
ON sprints (profile_key, board_id);

CREATE TABLE IF NOT EXISTS remote_filters (
    profile_key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    label TEXT NOT NULL,
    expression TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'remote',
    starred INTEGER NOT NULL DEFAULT 0 CHECK (starred IN (0, 1)),
    PRIMARY KEY (profile_key, account_id, label, expression)
);

CREATE TABLE IF NOT EXISTS fields (
    profile_key TEXT NOT NULL,
    id TEXT NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    schema_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (profile_key, id)
);

CREATE INDEX IF NOT EXISTS idx_fields_profile_name
ON fields (profile_key, name);

CREATE TABLE IF NOT EXISTS search_history (
    profile_key TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('text', 'jql')),
    query TEXT NOT NULL,
    searched_at REAL NOT NULL,
    PRIMARY KEY (profile_key, mode, query)
);

CREATE INDEX IF NOT EXISTS idx_search_history_profile_mode_searched_at
ON search_history (profile_key, mode, searched_at DESC);

CREATE TABLE IF NOT EXISTS recently_viewed_work_items (
    profile_key TEXT NOT NULL,
    work_item_key TEXT NOT NULL,
    work_item_type TEXT,
    summary TEXT,
    viewed_at REAL NOT NULL,
    PRIMARY KEY (profile_key, work_item_key)
);
