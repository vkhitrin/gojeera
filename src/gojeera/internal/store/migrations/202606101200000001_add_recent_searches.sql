CREATE TABLE IF NOT EXISTS recent_searches (
    profile_key TEXT NOT NULL,
    jql TEXT NOT NULL,
    source_mode TEXT CHECK (source_mode IN ('basic', 'text', 'jql')),
    searched_at REAL NOT NULL,
    PRIMARY KEY (profile_key, jql)
);

CREATE INDEX IF NOT EXISTS idx_recent_searches_profile_searched_at
ON recent_searches (profile_key, searched_at DESC);
