from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import psycopg

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


from ingest.db import PersistResult, persist_document
from ingest.models import SegmentAssetInput, SegmentBlockInput, SegmentInput


class ChatGPTAssetResolver:
    def __init__(self, export_dir: Path) -> None:
        self.export_dir = export_dir
        self._cache: Dict[str, Optional[Path]] = {}

    def resolve(self, pointer: str) -> Optional[Path]:
        if pointer in self._cache:
            return self._cache[pointer]
        token = pointer.split("://", 1)[1] if "://" in pointer else pointer
        matches = sorted(
            [
                path
                for path in self.export_dir.iterdir()
                if path.is_file() and path.name.startswith(token)
            ],
            key=lambda p: (0 if "sanitized" in p.name else 1, len(p.name)),
        )
        resolved = matches[0] if matches else None
        self._cache[pointer] = resolved
        return resolved


def load_conversations(export_dir: Path) -> List[dict]:
    conversations_path = export_dir / "conversations.json"
    if not conversations_path.exists():
        raise FileNotFoundError(f"No conversations.json found under {export_dir}")
    with conversations_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def to_datetime(epoch: Optional[float]) -> Optional[datetime]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def collect_segments(conversation: dict, resolver: ChatGPTAssetResolver) -> List[SegmentInput]:
    mapping: Dict[str, dict] = conversation["mapping"]
    roots = [node_id for node_id, node in mapping.items() if node.get("parent") is None]
    sequence_state: Dict[Optional[str], int] = {}
    segments: List[SegmentInput] = []

    def nearest_parent_with_message(node_id: Optional[str]) -> Optional[str]:
        current = node_id
        while current:
            node = mapping[current]
            if node.get("message"):
                return current
            current = node.get("parent")
        return None

    def next_sequence(parent_node_id: Optional[str]) -> int:
        sequence_state[parent_node_id] = sequence_state.get(parent_node_id, 0) + 1
        return sequence_state[parent_node_id]

    def visit(node_id: str) -> None:
        node = mapping[node_id]
        message = node.get("message")
        segment_parent_node_id = nearest_parent_with_message(node.get("parent"))
        if message:
            sequence = next_sequence(segment_parent_node_id)
            segment = build_segment(
                node_id=node_id,
                parent_node_id=segment_parent_node_id,
                sequence=sequence,
                message=message,
                resolver=resolver,
            )
            segments.append(segment)
        for child_id in node.get("children") or []:
            visit(child_id)

    for root in roots:
        visit(root)
    return segments


def build_segment(
    node_id: str,
    parent_node_id: Optional[str],
    sequence: int,
    message: dict,
    resolver: ChatGPTAssetResolver,
) -> SegmentInput:
    content = message.get("content") or {}
    parts = content.get("parts") or []
    markdown_parts: List[str] = []
    plaintext_parts: List[str] = []
    blocks: List[SegmentBlockInput] = []
    assets: List[SegmentAssetInput] = []

    for part in parts:
        if isinstance(part, str):
            markdown_parts.append(part)
            plaintext_parts.append(part)
            blocks.append(
                SegmentBlockInput(
                    block_type="markdown",
                    body=part,
                )
            )
            continue
        if not isinstance(part, dict):
            continue

        content_type = part.get("content_type") or "unknown_asset"
        pointer = part.get("asset_pointer") or ""
        markdown_parts.append(f"![{content_type}]({pointer})")
        plaintext_parts.append(f"[{content_type}]")

        resolved_path = resolver.resolve(pointer) if pointer else None
        asset_type = "image" if "image" in content_type else "file"
        local_path = str(resolved_path) if resolved_path else None
        mime_type = None
        if resolved_path:
            mime_type, _ = mimetypes.guess_type(resolved_path.name)
        assets.append(
            SegmentAssetInput(
                asset_type=asset_type,
                source_reference=pointer,
                file_name=resolved_path.name if resolved_path else None,
                mime_type=mime_type,
                size_bytes=part.get("size_bytes"),
                local_path=local_path,
            )
        )

    markdown = "\n\n".join(markdown_parts).strip()
    plaintext = " ".join(plaintext_parts).strip()

    return SegmentInput(
        node_id=node_id,
        parent_node_id=parent_node_id,
        sequence=sequence,
        source_role=message["author"]["role"],
        segment_type="message",
        content_markdown=markdown,
        plaintext=plaintext or markdown,
        content_json=content or None,
        started_at=to_datetime(message.get("create_time")),
        ended_at=to_datetime(message.get("update_time")),
        raw_reference=node_id,
        blocks=blocks,
        assets=assets,
    )


def ingest_conversation(
    conn: psycopg.Connection,
    conversation: dict,
    export_dir: Path,
) -> PersistResult:
    resolver = ChatGPTAssetResolver(export_dir)
    segments = collect_segments(conversation, resolver)

    created_at = to_datetime(conversation.get("create_time")) or datetime.now(tz=timezone.utc)
    updated_at = to_datetime(conversation.get("update_time")) or created_at

    metadata_keys = [
        "default_model_slug",
        "conversation_origin",
        "plugin_ids",
        "gizmo_id",
        "gizmo_type",
        "is_archived",
        "is_starred",
        "voice",
        "disabled_tool_ids",
        "memory_scope",
        "context_scopes",
    ]
    raw_metadata = {key: conversation.get(key) for key in metadata_keys if conversation.get(key) is not None}

    source_path = str(export_dir / "conversations.json") + f"#{conversation['id']}"
    checksum_input = json.dumps(conversation, sort_keys=True).encode("utf-8")
    checksum = hashlib.sha256(checksum_input).digest()

    return persist_document(
        conn,
        source_system="chatgpt",
        external_id=conversation["conversation_id"],
        title=conversation.get("title") or "Untitled conversation",
        summary=None,
        created_at=created_at,
        updated_at=updated_at,
        raw_metadata=raw_metadata,
        source_path=source_path,
        checksum=checksum,
        raw_payload=conversation,
        segments=segments,
    )


def _print_progress(stats: Dict[str, int], current: str) -> None:
    message = (
        f"new: {stats['new']} | updated: {stats['updated']} | "
        f"unchanged: {stats['unchanged']} | {current}"
    )
    print(f"\r{message}\x1b[K", end="", flush=True)


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Ingest ChatGPT exports into the Tiger database.")
    parser.add_argument(
        "export_path",
        nargs="?",
        type=Path,
        help="Path to the unzipped ChatGPT export directory (containing conversations.json).",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Path to the unzipped ChatGPT export directory (overrides positional argument).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of conversations to ingest.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional path to a .env file to load before connecting.",
    )
    args = parser.parse_args()

    if load_dotenv and args.env_file:
        load_dotenv(args.env_file)
    elif load_dotenv:
        load_dotenv()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL environment variable is required.")

    export_dir = args.export or args.export_path
    if export_dir is None:
        parser.error("Provide the export directory as a positional argument or via --export.")
    export_dir = export_dir.expanduser().resolve()
    conversations = load_conversations(export_dir)
    if args.limit is not None:
        conversations = conversations[: args.limit]

    stats = {"new": 0, "updated": 0, "unchanged": 0}
    with psycopg.connect(dsn) as conn:
        ingested = 0
        for conversation in conversations:
            try:
                result = ingest_conversation(conn, conversation, export_dir)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            if not result.version_created:
                stats["unchanged"] += 1
            elif result.document_created:
                stats["new"] += 1
            else:
                stats["updated"] += 1

            ingested += 1
            name = conversation.get("title") or conversation.get("id") or "conversation"
            _print_progress(stats, name)

    print("\r" + " " * 120 + "\r", end="")
    print(
        f"Ingested {ingested} conversation(s) from {export_dir} | "
        f"new: {stats['new']} updated: {stats['updated']} unchanged: {stats['unchanged']}"
    )


if __name__ == "__main__":
    run_cli()
