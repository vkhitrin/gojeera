ALTER TABLE projects ADD COLUMN graphql_ari TEXT;

CREATE TABLE IF NOT EXISTS project_features (
    profile_key TEXT NOT NULL,
    project_key TEXT NOT NULL,
    feature TEXT NOT NULL,
    state TEXT NOT NULL,
    toggle_locked INTEGER NOT NULL DEFAULT 0 CHECK (toggle_locked IN (0, 1)),
    localised_name TEXT,
    localised_description TEXT,
    image_uri TEXT,
    prerequisites_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (profile_key, project_key, feature)
);
