CREATE TABLE IF NOT EXISTS startup_metadata (
    profile_key TEXT NOT NULL,
    cache_type TEXT NOT NULL CHECK (
        cache_type IN ('server_info', 'global_settings')
    ),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (profile_key, cache_type)
);

CREATE TABLE IF NOT EXISTS projects_with_releases (
    profile_key TEXT NOT NULL,
    project_key TEXT NOT NULL,
    PRIMARY KEY (profile_key, project_key)
);
