# DocumentView Read Model

The FastAPI service exposes a unified representation of any ingested export
through the **DocumentView** contract. It stitches together the latest
`document_versions` snapshot, its ordered segments, and all nested resources
(blocks, assets, annotations, keywords) so downstream clients do not need to
understand the physical schema.

## Top-level shape

```json
{
  "document": { ... },
  "version": { ... },
  "segments": [ ... ],
  "keywords": [ ... ]
}
```

### `document`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key for `documents`. |
| `source_system` | enum (`chatgpt`, `claude`, `other`) | Specifies the originating exporter. |
| `external_id` | string | Stable identifier from the source system. |
| `title` | string | Human readable title. |
| `summary` | string \| null | Optional short description. |
| `created_at` | timestamptz | Conversation start time. |
| `updated_at` | timestamptz | Conversation last update time. |
| `raw_metadata` | object | Source-specific key/value metadata as stored in `documents.raw_metadata`. |

### `version`

Represents the most recent snapshot for the document.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key for `document_versions`. |
| `document_id` | UUID | Foreign key back to `documents.id`. |
| `ingested_at` | timestamptz | When this snapshot was parsed. |
| `source_path` | string | Export file path or URI (with fragment for the conversation id). |
| `checksum` | string | Hex-encoded SHA-256 of the raw payload. |

### `segments[]`

Ordered list of the content units inside the selected version.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | `document_segments.id`. |
| `parent_segment_id` | UUID \| null | Enables tree navigation (e.g. ChatGPT branches). |
| `sequence` | integer | Ordering within the parent scope. |
| `source_role` | enum (`system`, `user`, `assistant`, `tool`, `other`) | Author of the segment. |
| `segment_type` | enum (`message`, `message_part`, `metadata`, `attachment`) | Segment classification. |
| `content_markdown` | string | Canonical Markdown rendering of the segment. |
| `content_json` | object \| null | Raw structured payload preserved from ingestion. |
| `started_at` | timestamptz \| null | Source-provided timestamp for when the segment started. |
| `ended_at` | timestamptz \| null | Optional end timestamp. |
| `raw_reference` | string \| null | Source-specific identifier (e.g. ChatGPT node id). |
| `blocks` | `SegmentBlock[]` | Fine‑grained blocks extracted from the segment body. |
| `assets` | `SegmentAsset[]` | Attachment references (files, images, links). |
| `annotations` | `SegmentAnnotation[]` | Notes, summaries, or semantic references tied to the segment. |

#### `SegmentBlock`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | `segment_blocks.id`. |
| `sequence` | integer | Ordering inside the parent segment. |
| `block_type` | enum (`markdown`, `code`, `citation`, `tool_call`, `tool_result`) | Block classification. |
| `language` | string \| null | Detected language for code fences. |
| `body` | string | Raw block content. |
| `raw_data` | object \| null | Original payload emitted by the exporter. |

#### `SegmentAsset`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | `segment_assets.id`. |
| `asset_type` | enum (`file`, `image`, `link`) | Attachment type. |
| `file_name` | string \| null | Stored or original filename. |
| `mime_type` | string \| null | Mime type, when available. |
| `size_bytes` | integer \| null | File size from the exporter. |
| `local_path` | string \| null | Ingestion storage path (if downloaded locally). |
| `source_reference` | string | External reference or pointer. |
| `created_at` | timestamptz | When the asset row was created. |

#### `SegmentAnnotation`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | `segment_annotations.id`. |
| `annotation_type` | enum (`note`, `semantic_vector`, `summary`) | Annotation classification. |
| `payload` | object | Annotation payload (free-form JSON). |
| `created_at` | timestamptz | When the annotation was stored. |

### `keywords[]`

Each entry links a document to an item in the controlled vocabulary.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | `keywords.id`. |
| `term` | string | The vocabulary term. |
| `description` | string \| null | Optional description. |
| `document_keyword_id` | UUID | The junction table row (`document_keywords.id`) for auditing. |

## Search and pagination

The FastAPI service uses the same contract in several contexts:

- `GET /documents/{id}` returns the full `DocumentView`.
- `GET /documents` provides lightweight summaries (`id`, `title`, `source_system`, timestamps) with pagination.
- `GET /search` returns matching segments with snippets plus document metadata; consumers can fetch the full `DocumentView` afterwards.

The contract is intentionally additive—new fields can be appended without
breaking existing clients, and nested arrays keep the shape predictable for
export workflows (e.g., streaming all blocks or attachments).
