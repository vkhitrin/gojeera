ALTER TABLE projects ADD COLUMN project_type_key TEXT;

-- Invalidate cache
DELETE FROM projects;
DELETE FROM sync_log WHERE cache_type = 'projects';
