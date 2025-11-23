BEGIN;

-- Optional ingest identifiers to trace import batches and code versions.
ALTER TABLE document_versions
    ADD COLUMN ingest_batch_id UUID,
    ADD COLUMN ingested_by TEXT,
    ADD COLUMN ingest_source TEXT,
    ADD COLUMN ingest_version TEXT;

COMMENT ON TABLE document_versions IS 'Immutable versions of a document payload; keyed by document_id + checksum.';
COMMENT ON COLUMN document_versions.ingest_batch_id IS 'Optional batch/run identifier for this ingestion.';
COMMENT ON COLUMN document_versions.ingested_by IS 'Human or system user responsible for ingestion (e.g., cli, scheduler).';
COMMENT ON COLUMN document_versions.ingest_source IS 'Logical source of the ingest (e.g., chatgpt export, claude export, google export).';
COMMENT ON COLUMN document_versions.ingest_version IS 'Application/build version used to ingest this payload.';
COMMENT ON COLUMN document_versions.checksum IS 'Binary digest of the raw payload; enforces uniqueness per document.';
COMMENT ON COLUMN document_versions.created_at IS 'Record creation timestamp (added in migration 0004).';
COMMENT ON COLUMN document_versions.updated_at IS 'Record last-updated timestamp (added in migration 0004).';

-- Add comments to documents to clarify lifecycle intent.
COMMENT ON TABLE documents IS 'Logical documents; deduped by (source_system, external_id).';
COMMENT ON COLUMN documents.created_at IS 'Original creation time from the source system (as provided by ingest).';
COMMENT ON COLUMN documents.updated_at IS 'Last updated time from the source system (as provided by ingest).';

-- Per-segment checksum for dedupe/debugging. Nullable to keep backfill flexible.
ALTER TABLE document_segments
    ADD COLUMN content_checksum BYTEA;

COMMENT ON TABLE document_segments IS 'Individual content segments for a document version; ordering is via sequence.';
COMMENT ON COLUMN document_segments.content_checksum IS 'Optional checksum of normalized segment content for dedupe/debugging (e.g., SHA-256 digest).';
COMMENT ON COLUMN document_segments.sequence IS 'Ordinal within a document_version; must be unique per parent_segment_id (NULL for roots).';
COMMENT ON COLUMN document_segments.started_at IS 'Start timestamp from source export when available.';
COMMENT ON COLUMN document_segments.ended_at IS 'End timestamp from source export when available.';
COMMENT ON COLUMN document_segments.created_at IS 'Record creation timestamp (added in migration 0004).';
COMMENT ON COLUMN document_segments.updated_at IS 'Record last-updated timestamp (added in migration 0004).';

-- Partial unique index to prevent identical content within the same document version when checksum is provided.
CREATE UNIQUE INDEX document_segments_content_checksum_unique
    ON document_segments (document_version_id, content_checksum)
    WHERE content_checksum IS NOT NULL;

-- Ensure sequence is positive.
ALTER TABLE document_segments
    ADD CONSTRAINT document_segments_sequence_positive CHECK (sequence > 0);

COMMIT;
