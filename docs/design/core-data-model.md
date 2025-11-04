# Core Data Model Proposal

This model targets the initial ingestion of ChatGPT and Claude chat exports while leaving room to accommodate additional document types later. PostgreSQL is the backing store.

## Design goals

1. **Source Fidelity** – Preserve enough information to reconstruct the original view.
2. **Segment-Level Access** – Allow users to copy or export any component individually.
3. **Rich Indexing** – Support metadata filters, free-text search, and future semantic embeddings.
4. **Extensibility** – New document types should slot in without schema rewrites.

## Entity overview

```
documents ─┬─ document_versions ─┬─ document_segments ─┬─ segment_blocks
           │                     │                      └─ segment_assets
           ├─ document_keywords  └─ segment_annotations
           └─ document_embeddings (future)
```

### documents

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | Stable identifier. |
| `source_system` | enum (`chatgpt`, `claude`, …) | Origin of the document. |
| `external_id` | text | ID from the source (e.g., conversation UUID). |
| `title` | text | Friendly title. |
| `summary` | text | System-generated digest (nullable). |
| `created_at` | timestamptz | Conversation start. |
| `updated_at` | timestamptz | Conversation last update. |
| `raw_metadata` | jsonb | House source-specific extras (plugins, tags, etc.). |

Use `(source_system, external_id)` as a unique key to deduplicate imports.

### document_versions

Captures each ingestion event of a document so we can diff snapshots.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK |
| `document_id` | UUID FK |
| `ingested_at` | timestamptz | When we parsed this snapshot. |
| `source_path` | text | Export file path or URI. |
| `checksum` | bytea | Hash of the raw payload to detect duplicates. |
| `raw_payload` | jsonb | Parsed representation of the full export portion. |

### document_segments

Represents the primary, user-facing components (chat turns, paragraphs, etc.).

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK |
| `document_version_id` | UUID FK | Ties to a snapshot. |
| `parent_segment_id` | UUID FK nullable | Enables tree structures (ChatGPT branches). |
| `sequence` | integer | Stable ordering within a parent. |
| `source_role` | enum (`system`, `user`, `assistant`, `tool`, …) |
| `segment_type` | enum (`message`, `message_part`, `metadata`, `attachment`) |
| `content_markdown` | text | Canonical Markdown. |
| `content_plaintext` | tsvector | Populated for full-text search. |
| `content_json` | jsonb | Optional structured payload (e.g., Claude `text` array). |
| `started_at` | timestamptz | Timestamp from the source message. |
| `ended_at` | timestamptz | Optional stop time. |
| `raw_reference` | text | Source-specific node id (e.g., ChatGPT message UUID). |

`content_markdown` stores the rendered representation we feed to the UI. `content_json` retains richer structures (such as Claude code/tool results) for alternate renderers.

### segment_blocks

Fine-grained child blocks (e.g., code fences inside a ChatGPT message or Claude `text` array items).

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK |
| `segment_id` | UUID FK |
| `sequence` | integer | Ordering within the segment. |
| `block_type` | enum (`markdown`, `code`, `citation`, `tool_call`, `tool_result`) |
| `language` | text | Detected language for code fences. |
| `body` | text | Raw block content. |
| `raw_data` | jsonb | Retains original payload from the export. |

Segment blocks enable copy/export of subcomponents like code snippets without re-parsing Markdown every time.

### segment_assets

Attachments referenced by a segment (files or images).

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK |
| `segment_id` | UUID FK |
| `asset_type` | enum (`file`, `image`, `link`) |
| `file_name` | text |
| `mime_type` | text |
| `size_bytes` | integer |
| `local_path` | text | Storage path after ingestion. |
| `source_reference` | text | External download URL or identifier. |

### document_keywords

Supports the controlled vocabulary requirement.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK |
| `document_id` | UUID FK |
| `keyword_id` | UUID FK (`keywords` table) |

`keywords` table holds authoritative terms with optional hierarchies.

### segment_annotations

Free-form notes, tags, or future semantic embedding references.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK |
| `segment_id` | UUID FK |
| `annotation_type` | enum (`note`, `semantic_vector`, `summary`) |
| `payload` | jsonb | Flexible storage (e.g., vector reference, short summary). |

## Parsing strategy (ChatGPT vs Claude)

| Concern | ChatGPT | Claude | Approach |
|---------|---------|--------|----------|
| Base message unit | Tree nodes in `mapping` | Array in `messages` | Flatten to segments ordered by tree traversal (ChatGPT) or array index (Claude). |
| Message content | Markdown with tool metadata in `parts` | Array of rich text blocks | Normalize to `segment_blocks` preserving type and order. |
| Attachments | Appear in message metadata with file IDs | `attachments[]` array with file references | Store as `segment_assets` and download files into managed storage. |
| Branching | Multiple children from edits | Linear | Represent via `parent_segment_id` and sequence ordering per parent. |

## Indexing & search

- Use PostgreSQL `tsvector` columns on `content_plaintext` for text search.
- Augment with a `document_embeddings` table when we integrate vector search (likely via pgvector).
- Metadata filters derive from `documents.raw_metadata`, `segment_type`, `source_role`, etc.

## Next steps

1. Draft parsing adapters for ChatGPT and Claude exports that emit standardized ingestion objects (`Document`, `Segment`, `Block`, `Asset`).
2. Validate the schema against a handful of real exports to ensure coverage of edge cases (attachments, tool calls, multimodal content).
3. Prototype a read-path that renders a conversation from `document_segments` + `segment_blocks` to confirm fidelity.
