-- Helper function returning a full DocumentView JSON payload.
-- Run via: psql -f db/api_document_view.sql

CREATE SCHEMA IF NOT EXISTS api;

CREATE OR REPLACE FUNCTION api.document_view_json(p_document_id uuid)
RETURNS jsonb
LANGUAGE sql
AS
$$
WITH latest_version AS (
    SELECT dv.*
    FROM document_versions dv
    WHERE dv.document_id = p_document_id
    ORDER BY dv.ingested_at DESC
    LIMIT 1
),
segments AS (
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', ds.id,
            'parent_segment_id', ds.parent_segment_id,
            'sequence', ds.sequence,
            'source_role', ds.source_role,
            'segment_type', ds.segment_type,
            'content_markdown', ds.content_markdown,
            'content_json', ds.content_json,
            'started_at', ds.started_at,
            'ended_at', ds.ended_at,
            'raw_reference', ds.raw_reference,
            'blocks', COALESCE(blocks.blocks, '[]'::jsonb),
            'assets', COALESCE(assets.assets, '[]'::jsonb),
            'annotations', COALESCE(annotations.annotations, '[]'::jsonb)
        ) ORDER BY ds.parent_segment_id NULLS FIRST, ds.sequence
    ) AS segments
    FROM latest_version lv
    JOIN document_segments ds ON ds.document_version_id = lv.id
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', sb.id,
                'sequence', sb.sequence,
                'block_type', sb.block_type,
                'language', sb.language,
                'body', sb.body,
                'raw_data', sb.raw_data
            ) ORDER BY sb.sequence
        ) AS blocks
        FROM segment_blocks sb
        WHERE sb.segment_id = ds.id
    ) blocks ON TRUE
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', sa.id,
                'asset_type', sa.asset_type,
                'attachment_id', att.id,
                'file_name', att.file_name,
                'mime_type', att.mime_type,
                'size_bytes', att.size_bytes,
                'created_at', sa.created_at,
                'has_content', att.content IS NOT NULL
            ) ORDER BY sa.created_at, sa.id
        ) AS assets
        FROM segment_assets sa
        JOIN attachments att ON att.id = sa.attachment_id
        WHERE sa.segment_id = ds.id
    ) assets ON TRUE
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', an.id,
                'annotation_type', an.annotation_type,
                'payload', an.payload,
                'created_at', an.created_at
            ) ORDER BY an.created_at, an.id
        ) AS annotations
        FROM segment_annotations an
        WHERE an.segment_id = ds.id
    ) annotations ON TRUE
),
keywords AS (
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', k.id,
            'term', k.term,
            'description', k.description,
            'document_keyword_id', dk.id
        ) ORDER BY k.term
    ) AS keywords
    FROM document_keywords dk
    JOIN keywords k ON k.id = dk.keyword_id
    WHERE dk.document_id = p_document_id
)
SELECT jsonb_build_object(
    'document', jsonb_build_object(
        'id', d.id,
        'source_system', d.source_system,
        'external_id', d.external_id,
        'title', d.title,
        'summary', d.summary,
        'created_at', d.created_at,
        'updated_at', d.updated_at,
        'raw_metadata', d.raw_metadata
    ),
    'version', jsonb_build_object(
        'id', lv.id,
        'document_id', d.id,
        'ingested_at', lv.ingested_at,
        'source_path', lv.source_path,
        'checksum', encode(lv.checksum, 'hex')
    ),
    'segments', COALESCE(segments.segments, '[]'::jsonb),
    'keywords', COALESCE(keywords.keywords, '[]'::jsonb)
)
FROM documents d
JOIN latest_version lv ON lv.document_id = d.id
LEFT JOIN segments ON TRUE
LEFT JOIN keywords ON TRUE
WHERE d.id = p_document_id;
$$;
