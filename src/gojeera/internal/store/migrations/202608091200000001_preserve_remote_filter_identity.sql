CREATE TABLE remote_filters_with_identity (
    profile_key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    entry_key TEXT NOT NULL,
    filter_id TEXT,
    label TEXT NOT NULL,
    expression TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'remote',
    starred INTEGER NOT NULL DEFAULT 0 CHECK (starred IN (0, 1)),
    PRIMARY KEY (profile_key, account_id, entry_key)
);

-- Legacy rows have no Jira ID. Preserve every row and its existing sync metadata.
INSERT INTO remote_filters_with_identity
    (profile_key, account_id, entry_key, filter_id, label, expression, source, starred)
SELECT profile_key, account_id, 'legacy:' || rowid, NULL, label, expression, source, starred
FROM remote_filters;

DROP TABLE remote_filters;
ALTER TABLE remote_filters_with_identity RENAME TO remote_filters;
CREATE INDEX idx_remote_filters_scope_label ON remote_filters (profile_key, account_id, label);
