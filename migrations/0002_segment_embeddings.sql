BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE document_segments
    ADD COLUMN quality_score REAL,
    ADD COLUMN is_noise BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN embedding vector(1536),
    ADD COLUMN embedding_model TEXT,
    ADD COLUMN embedding_tokens INTEGER,
    ADD COLUMN embedding_updated_at TIMESTAMPTZ,
    ADD COLUMN embedding_status TEXT NOT NULL DEFAULT 'pending';

CREATE OR REPLACE FUNCTION set_document_segment_embedding_state()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.embedding IS NOT NULL THEN
        NEW.embedding_status := 'ready';
        IF NEW.embedding_updated_at IS NULL THEN
            NEW.embedding_updated_at := NOW();
        END IF;
    ELSE
        NEW.embedding_status := 'pending';
        NEW.embedding_updated_at := NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS document_segments_embedding_state ON document_segments;
CREATE TRIGGER document_segments_embedding_state
    BEFORE INSERT OR UPDATE OF embedding ON document_segments
    FOR EACH ROW
    EXECUTE FUNCTION set_document_segment_embedding_state();

COMMIT;
