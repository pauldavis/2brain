# Claude Conversation Export Format

Anthropic provides a self-serve export from the Claude web application. The export arrives as a `.zip` archive named `claude-export-YYYYMMDD-HHMMSS.zip` containing:

| Path | Purpose |
|------|---------|
| `manifest.json` | Basic metadata about the export batch (user id, generated_at). |
| `conversations.json` | All chat threads in a single JSON array. |
| `conversations/` | Per-conversation JSON files mirroring the main file (optional). |
| `attachments/` | Uploaded files keyed by UUID (optional, present when attachments exist). |

## conversations.json structure

The top-level value is an array. Each element represents one Claude conversation:

| Field | Type | Notes |
|-------|------|-------|
| `uuid` | string (UUID) | Persistent identifier. |
| `name` | string | User-supplied title (auto-generated if none). |
| `summary` | string | Optional auto-generated blurb (empty string when absent). |
| `created_at` | ISO-8601 string | Creation timestamp. |
| `updated_at` | ISO-8601 string | Last message timestamp. |
| `account` | object | Includes the exporting account UUID. |
| `chat_messages` | array | Chronological list of message objects. |

Earlier exports (pre-2024) exposed `model`, `tags`, `metadata`, and `messages`; the November 2025 sample uses the more compact schema above. We should store the full JSON in `documents.raw_metadata` so either variant can be reconstructed.

Each entry in `chat_messages` has the following observed structure:

```json
{
  "uuid": "message-id",
  "sender": "assistant",
  "text": "Rendered Markdown string (first block).",
  "content": [
    {
      "start_timestamp": "2024-07-18T21:23:35.731874Z",
      "stop_timestamp": "2024-07-18T21:23:35.731874Z",
      "flags": null,
      "type": "text",
      "text": "Same body as `text` (Markdown).",
      "citations": []
    }
  ],
  "attachments": [],
  "files": [],
  "created_at": "2024-07-18T21:23:35.731874Z",
  "updated_at": "2024-07-18T21:23:35.731874Z"
}
```

Notes:

- `sender` replaces the earlier `type` field; observed values include `human`, `assistant`, and `tool` (for tool outputs).
- `content[*].type` supports a richer set than previous reports: `text`, `thinking`, `tool_use`, `tool_result`, `token_budget`, and `voice_note` all appear in the sample. `tool_use` blocks embed JSON payloads describing the call arguments; `tool_result` contains the tool's response string.
- The top-level `text` mirrors the first textual block but may be empty when the response is purely structural (e.g., tool calls).
- `attachments` entries include `file_name`, `file_size`, `file_type`, and an optional `extracted_content` HTML/Markdown string (helpful for ingestion even before file download completes).
- `files` is a lightweight array referencing uploaded assets by filename (no additional metadata). Actual binaries live under `attachments/` in the archive.
- Every message carries `created_at`/`updated_at` timestamps; there is no explicit stop_reason in this export, so we must infer completion by sender/type.

### Other export files

Beyond `conversations.json`, the 2025 sample also includes:

- `memories.json` — account-level memory blob containing structured Markdown.
- `projects.json` — project metadata with embedded `docs[*].content`.
- `users.json` — account profile details.

These files may enrich metadata surfaces or seed future ingestion types.

## Implications for 2brain

1. **Linear ordering**: Unlike ChatGPT’s tree, Claude conversations are strictly chronological. This simplifies segment ordering but requires us to store array indices for reproducibility.
2. **Segment types**: Each entry in `text` can become an individual segment if we want fine-grained indexing (e.g., separating code from prose).
3. **Attachments**: File references should be captured as child records so users can download or preview them.
4. **Metadata parity**: When present, fields like `model`, `tags`, or `stop_reason` provide useful filter facets that we should preserve in our schema.

### Open questions

- Verify whether Claude now includes semantic summaries or continuation references in exports and update the schema accordingly.
- Determine the stability of `attachments` payloads—fields like `extracted_content` may grow.
- Confirm whether Claude exports include deleted/archived conversations with a flag or omit them entirely.
- Investigate whether tool invocation metadata (from `tool_use`/`tool_result`) should be normalized into dedicated segment records.
