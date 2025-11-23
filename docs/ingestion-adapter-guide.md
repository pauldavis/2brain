# Ingestion Adapter Guide

Use this guide when adding or updating a source adapter (ChatGPT, Claude, Google, etc.). The goal is to keep source-specific parsing small and rely on the shared pipeline for ordering, checksums, and persistence.

## Source adapter responsibilities
1) Parse the export into:
   - `ParsedDocument` fields: `external_id`, `title`, `summary`, `created_at`, `updated_at`, `raw_metadata`, `source_path`, `raw_payload`, `source_system`.
   - `SegmentInput` list: each segment should include `node_id`, `parent_node_id` (if nesting), `source_role`, `segment_type`, `content_markdown`, `plaintext`, `content_json`, `started_at`/`ended_at` (if available), `raw_reference`, and any `blocks`/`assets`/`annotations`.
2) Do **not** worry about `sequence` or `content_checksum`—the shared pipeline will set them.
3) Provide ingest metadata when calling the pipeline (batch ID, ingested_by, ingest_source, ingest_version) if available.

## Shared pipeline (ingest/pipeline.py)
Call `ingest_document(conn, parsed_doc, segments, ingest_meta...)`. It will:
- Assign monotonic, 1-based sequences (per parent if requested).
- Normalize markdown and compute `content_checksum` for each segment.
- Compute `document_versions.checksum` from the raw payload.
- Persist documents/versions/segments via `persist_document`.

## Constraints to respect
- `sequence` must be > 0 and unique per `(document_version_id, parent_segment_id)` (NULL parent for roots).
- `document_versions` are deduped by `(document_id, checksum)`.
- `document_segments` optional `content_checksum` is unique per document_version when provided.

## Timestamps and ordering
- Viewer ordering comes from `document_segments.sequence`; timestamps shown are `started_at` / `ended_at` as ingested.
- Provide source timestamps if present; otherwise leave NULL and the pipeline will not synthesize them.

## Ingest metadata fields (document_versions)
- `ingest_batch_id`: run identifier (UUID).
- `ingested_by`: operator or service.
- `ingest_source`: logical source (chatgpt, claude, google, …).
- `ingest_version`: app/code version used for ingest.

## Checksums
- `document_versions.checksum` is computed from `raw_payload` (sorted JSON) for dedupe.
- `document_segments.content_checksum` is SHA-256 of normalized markdown for diagnostics/dedupe.

## QA queries (run manually or behind an env flag)
See `docs/database-and-ingestion-reference.md` for SQL to detect duplicate sequences, duplicate content checksums, or empty content. Running these after ingest helps catch bad inputs early.
