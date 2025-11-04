# ChatGPT Conversation Export Format

The ChatGPT web UI lets a user request an export of their data, which is delivered as a `.zip` archive. The archive typically contains:

| Path | Purpose |
|------|---------|
| `README.txt` | Link to OpenAI privacy docs and instructions. |
| `conversations.json` | All chats as a single JSON array. |
| `conversations/` | *(Optional)* Per-conversation `.json` mirrors of the main file. |
| `account/` | Account metadata (profile, settings). |

The `conversations.json` file is the primary source for documents we plan to ingest.

## conversations.json structure

Top-level value is an array. Each element is one conversation with these fields observed in recent exports (2023–2024):

| Field | Type | Notes |
|-------|------|-------|
| `id` | string (UUID) | Conversation identifier used by the client. |
| `title` | string | User-visible conversation title. |
| `create_time` | number (Unix seconds) | Timestamp when the conversation was started. |
| `update_time` | number (Unix seconds) | Last message timestamp. |
| `mapping` | object | Tree of message nodes keyed by message UUID. |
| `moderation_results` | array | Entries for prompts/responses flagged by OpenAI moderation. |
| `current_node` | string | The node id the UI was focused on last. |
| `plugin_ids` | array | IDs of plugins/tools enabled during the chat session. |
| `conversation_template_id` | string\|null | Present for system templates. |

Additional keys seen in the November 2025 sample include:

- Lifecycle and status flags: `async_status`, `conversation_origin`, `is_archived`, `is_read_only`, `is_starred`, `is_study_mode`, `is_do_not_remember`.
- Model and tool hints: `default_model_slug`, `disabled_tool_ids`, `gizmo_id`, `gizmo_type`, `voice`.
- Safety and memory fields: `blocked_urls`, `safe_urls`, `context_scopes`, `memory_scope`.
- Ownership and bookkeeping: `conversation_id`, `owner`, `sugar_item_id`, `sugar_item_visible`.

Plan to persist the entire object in `documents.raw_metadata` so we can surface newly introduced fields without schema churn.

Each `mapping` entry looks like:

```json
{
  "message-id": {
    "id": "message-id",
    "message": {
      "id": "message-id",
      "author": { "role": "assistant" },
      "content": {
        "content_type": "text",
        "parts": [
          "Text chunk 1",
          "Text chunk 2"
        ]
      },
      "create_time": 1701324175.123,
      "end_turn": true,
      "weight": 1,
      "metadata": {},
      "recipient": "all"
    },
    "parent": "previous-message-id",
    "children": ["child-id-1", "child-id-2"],
    "message_type": "assistant"
  }
}
```

Notes:

- `author.role` can be `system`, `user`, `assistant`, or `tool`.
- `content.content_type` spans a large enum. The 2025 export includes `text`, `code`, `computer_output`, `multimodal_text`, `tether_browsing_display`, `sonic_webpage`, `reasoning_recap`, `thoughts`, and more. Treat the value as open-ended.
- `parts` may mix plain strings and structured objects. For example, `multimodal_text` emits an array containing `image_asset_pointer` objects with `asset_pointer` URIs like `sediment://file_0000…` (the actual binary ships alongside the export) followed by the user’s Markdown text.
- Messages from the UI that upload files still surface under `message.metadata.attachments`, but the export also drops each referenced asset into the top-level folder as `file-<token>-<original-name>` or `file_<hash>-sanitized.<ext>`.
- `parent`/`children` encode the branching tree of follow-up edits. The main happy path corresponds to the chain that leads to `current_node`.
- Code snippets are embedded inside the Markdown strings within `parts`. There is no dedicated AST; we must parse fenced code blocks ourselves.

## Implications for 2brain

1. **Document segmentation**: Each conversation should be broken into ordered turns following the `parent` chain to `current_node`. Alternate branches can be captured as separate segments that reference their parent.
2. **Metadata**: Rich metadata is available for timestamps, roles, plugin/tool usage, and moderation results.
3. **Rendering fidelity**: The UI reproduces Markdown content verbatim; we must parse Markdown with GitHub-flavored extensions (tables, fenced code).
4. **Incremental updates**: Exports are point-in-time snapshots. If we import repeatedly, we must deduplicate by `message.id` or conversation `id`.

### Open questions

- Confirm whether the per-conversation files appear consistently for all users.
- Track emerging `content_type` values and extend renderers as needed (e.g., `app_pairing_content`, `super_widget`, `user_editable_context`).
- Verify how async tool runs (`metadata.async_task_*`) should be represented in our ingestion model.
