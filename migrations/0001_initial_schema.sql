BEGIN;

-- Ensure UUID generation helpers are available.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Enumerations ------------------------------------------------------------

CREATE TYPE document_source_system AS ENUM (
    'chatgpt',
    'claude',
    'other'
);

CREATE TYPE segment_source_role AS ENUM (
    'system',
    'user',
    'assistant',
    'tool',
    'other'
);

CREATE TYPE segment_type AS ENUM (
    'message',
    'message_part',
    'metadata',
    'attachment'
);

CREATE TYPE segment_block_type AS ENUM (
    'markdown',
    'code',
    'citation',
    'tool_call',
    'tool_result'
);

CREATE TYPE segment_asset_type AS ENUM (
    'file',
    'image',
    'link'
);

CREATE TYPE segment_annotation_type AS ENUM (
    'note',
    'semantic_vector',
    'summary'
);

-- Core tables -------------------------------------------------------------

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system document_source_system NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_system, external_id)
);

CREATE TABLE document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_path TEXT NOT NULL,
    checksum BYTEA NOT NULL,
    raw_payload JSONB NOT NULL,
    UNIQUE (document_id, checksum)
);

CREATE TABLE document_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    parent_segment_id UUID REFERENCES document_segments(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    source_role segment_source_role NOT NULL,
    segment_type segment_type NOT NULL,
    content_markdown TEXT NOT NULL,
    content_plaintext TSVECTOR NOT NULL DEFAULT ''::tsvector,
    content_json JSONB,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    raw_reference TEXT
);

CREATE TABLE segment_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES document_segments(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    block_type segment_block_type NOT NULL,
    language TEXT,
    body TEXT NOT NULL,
    raw_data JSONB,
    CONSTRAINT segment_blocks_sequence_unique
        UNIQUE (segment_id, sequence)
);

CREATE TABLE segment_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES document_segments(id) ON DELETE CASCADE,
    asset_type segment_asset_type NOT NULL,
    file_name TEXT,
    mime_type TEXT,
    size_bytes INTEGER,
    local_path TEXT,
    source_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    term TEXT NOT NULL UNIQUE,
    description TEXT,
    parent_keyword_id UUID REFERENCES keywords(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE document_keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    keyword_id UUID NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_keywords_document_keyword_unique UNIQUE (document_id, keyword_id)
);

CREATE TABLE segment_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES document_segments(id) ON DELETE CASCADE,
    annotation_type segment_annotation_type NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes ----------------------------------------------------------------

CREATE INDEX document_versions_document_id_idx
    ON document_versions (document_id);

CREATE INDEX document_segments_document_version_id_idx
    ON document_segments (document_version_id);

CREATE INDEX document_segments_parent_segment_id_idx
    ON document_segments (parent_segment_id);

CREATE UNIQUE INDEX document_segments_sequence_root_idx
    ON document_segments (document_version_id, sequence)
    WHERE parent_segment_id IS NULL;

CREATE UNIQUE INDEX document_segments_sequence_child_idx
    ON document_segments (document_version_id, parent_segment_id, sequence)
    WHERE parent_segment_id IS NOT NULL;

CREATE INDEX document_segments_content_plaintext_idx
    ON document_segments USING GIN (content_plaintext);

CREATE INDEX segment_blocks_segment_id_idx
    ON segment_blocks (segment_id);

CREATE INDEX segment_assets_segment_id_idx
    ON segment_assets (segment_id);

CREATE INDEX document_keywords_document_id_idx
    ON document_keywords (document_id);

CREATE INDEX document_keywords_keyword_id_idx
    ON document_keywords (keyword_id);

CREATE INDEX segment_annotations_segment_id_idx
    ON segment_annotations (segment_id);

COMMIT;
