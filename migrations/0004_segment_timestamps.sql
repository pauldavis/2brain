BEGIN;

-- Add lifecycle timestamps to document_versions so we can track ingestion edits.
ALTER TABLE document_versions
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Add lifecycle timestamps to document_segments for ordering/debugging.
ALTER TABLE document_segments
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

COMMIT;
