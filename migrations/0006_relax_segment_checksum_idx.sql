BEGIN;

-- Drop the unique constraint/index on per-version content_checksum so duplicate
-- content (e.g., identical non-empty segments) does not block ingestion.
DROP INDEX IF EXISTS document_segments_content_checksum_unique;

-- Keep a non-unique partial index for diagnostics/lookup.
CREATE INDEX IF NOT EXISTS document_segments_content_checksum_idx
    ON document_segments (document_version_id, content_checksum)
    WHERE content_checksum IS NOT NULL;

COMMIT;
