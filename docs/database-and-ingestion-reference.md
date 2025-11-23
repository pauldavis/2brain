# Database and Ingestion Reference

This project ingests conversational exports (ChatGPT, Claude, Google, etc.) into Postgres and exposes them for search. Below is a condensed reference covering schema expectations, ingestion requirements, and QA checks.

## Core tables (high level)

- `documents`: logical doc, keyed by `(source_system, external_id)`. Stores title/summary/metadata and lifecycle timestamps.
- `document_versions`: immutable payload per ingest run; keyed by `(document_id, checksum)`. Tracks source_path, checksum of raw payload, ingest metadata (`ingest_batch_id`, `ingested_by`, `ingest_source`, `ingest_version`), and timestamps.
- `document_segments`: content slices (messages, metadata, attachments), linked to a `document_version`. Important fields:
  - `sequence`: 1-based order within the document version (roots) or within a parent segment (children). Must be unique per `(document_version_id, parent_segment_id)`.
  - `content_markdown` / `content_plaintext` / `content_json`
  - `started_at` / `ended_at`: timestamps from source payloads when present.
  - `content_checksum`: optional digest for dedupe/debugging within a document version.
  - `quality_score`, `is_noise`
- `segment_blocks`, `segment_assets`, `segment_annotations`, `keywords` / `document_keywords`: supporting structures for blocks, attachments, annotations, and tagging.

## Constraints that matter for ingestion

- `documents`: `UNIQUE (source_system, external_id)`
- `document_versions`: `UNIQUE (document_id, checksum)`
- `document_segments`:
  - `CHECK (sequence > 0)`
  - `UNIQUE (document_version_id, sequence)` when `parent_segment_id IS NULL`
  - `UNIQUE (document_version_id, parent_segment_id, sequence)` when `parent_segment_id IS NOT NULL`
  - `UNIQUE (document_version_id, content_checksum)` when `content_checksum IS NOT NULL` (debug/dedupe aid)

## Ingestion requirements / recommendations

- Always assign a **monotonic `sequence`** per document version for root segments (and per parent for child segments). This drives ordering in the viewer and search cards.
- Populate `started_at` / `ended_at` when available from the source export; leave `NULL` otherwise.
- Compute a **segment checksum** (e.g., SHA-256 of normalized markdown) and set `document_segments.content_checksum` to enable dedupe and diagnostics.
- Set `document_versions.ingest_batch_id`, `ingested_by`, `ingest_source`, and `ingest_version` to trace runs and code versions.
- Respect existing `checksum` on `document_versions` to avoid re-ingesting the same payload.
- Keep `sequence` > 0; the DB enforces this via `CHECK`.

## Suggested QA checks (ad hoc, or gated by an env flag at startup)

Run these against a database to catch common issues:

```sql
-- 1) Detect duplicate sequences per document_version (roots only)
SELECT document_version_id, sequence, COUNT(*) AS cnt
FROM document_segments
WHERE parent_segment_id IS NULL
GROUP BY document_version_id, sequence
HAVING COUNT(*) > 1
ORDER BY cnt DESC;

-- 2) Detect duplicate sequences for child segments (if used)
SELECT document_version_id, parent_segment_id, sequence, COUNT(*) AS cnt
FROM document_segments
WHERE parent_segment_id IS NOT NULL
GROUP BY document_version_id, parent_segment_id, sequence
HAVING COUNT(*) > 1
ORDER BY cnt DESC;

-- 3) Detect content duplicates within the same version (requires checksum populated)
SELECT document_version_id, content_checksum, COUNT(*) AS cnt
FROM document_segments
WHERE content_checksum IS NOT NULL
GROUP BY document_version_id, content_checksum
HAVING COUNT(*) > 1;

-- 4) Find segments with empty content (possible ingest noise)
SELECT id, document_version_id
FROM document_segments
WHERE COALESCE(NULLIF(content_markdown, ''), '') = '';
```

You can optionally wire these into app startup behind an env flag (e.g., `QA_CHECKS_ON_STARTUP=true`) and log warnings when violations are found.

## Ordering and timestamps in the viewer

- Segment numbers shown in the UI come from `document_segments.sequence`.
- Timestamps shown in the UI come from `document_segments.started_at` / `ended_at` (they are not synthesized).
- If sequences are wrong, the UI ordering will be wrong; keep the sequence unique and monotonic at ingest time.

## Notes on checksums

- `document_versions.checksum` dedupes entire payloads.
- `document_segments.content_checksum` is optional but recommended; use a stable digest (e.g., SHA-256 of normalized markdown). A partial unique index prevents identical content within the same document version when the checksum is set.
