BEGIN;

CREATE TABLE attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name TEXT,
    mime_type TEXT,
    size_bytes INTEGER,
    local_path TEXT,
    source_reference TEXT,
    content BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE segment_assets
    ADD COLUMN attachment_id UUID;

UPDATE segment_assets
SET attachment_id = gen_random_uuid()
WHERE attachment_id IS NULL;

INSERT INTO attachments (id, file_name, mime_type, size_bytes, local_path, source_reference, created_at)
SELECT attachment_id, file_name, mime_type, size_bytes, local_path, source_reference, created_at
FROM segment_assets;

ALTER TABLE segment_assets
    ALTER COLUMN attachment_id SET NOT NULL;

ALTER TABLE segment_assets
    DROP COLUMN file_name,
    DROP COLUMN mime_type,
    DROP COLUMN size_bytes,
    DROP COLUMN local_path,
    DROP COLUMN source_reference;

ALTER TABLE segment_assets
    ADD CONSTRAINT segment_assets_attachment_id_fkey
        FOREIGN KEY (attachment_id) REFERENCES attachments(id) ON DELETE CASCADE;

CREATE INDEX segment_assets_attachment_id_idx
    ON segment_assets (attachment_id);

COMMIT;
