from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import psycopg

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from ingest.db import PersistResult, persist_document
from ingest.models import SegmentAssetInput, SegmentBlockInput, SegmentInput


def load_conversations(export_dir: Path) -> List[dict]:
    conversations_path = export_dir / "conversations.json"
    if not conversations_path.exists():
        raise FileNotFoundError(f"No conversations.json found under {export_dir}")
    with conversations_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def normalize_sender(sender: str) -> str:
    if sender == "assistant":
        return "assistant"
    if sender == "human":
        return "user"
    return "other"


def determine_asset_type(file_name: str | None) -> str:
    if not file_name:
        return "file"
    extension = Path(file_name).suffix.lower()
    if extension in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic", ".bmp"}:
        return "image"
    return "file"


def build_segment(message: dict, sequence: int) -> SegmentInput:
    blocks: List[SegmentBlockInput] = []
    assets: List[SegmentAssetInput] = []
    markdown_parts: List[str] = []
    plaintext_parts: List[str] = []

    for block in message.get("content", []):
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            markdown_parts.append(text)
            plaintext_parts.append(text)
            blocks.append(
                SegmentBlockInput(
                    block_type="markdown",
                    body=text,
                    raw_data=block,
                )
            )
        elif block_type == "thinking":
            text = block.get("thinking", "")
            markdown_parts.append(text)
            plaintext_parts.append(text)
            blocks.append(
                SegmentBlockInput(
                    block_type="markdown",
                    body=text,
                    raw_data=block,
                )
            )
        elif block_type == "voice_note":
            text = block.get("text") or f"[voice note: {block.get('title', 'untitled')}]"
            markdown_parts.append(text)
            plaintext_parts.append(text)
            blocks.append(
                SegmentBlockInput(
                    block_type="markdown",
                    body=text,
                    raw_data=block,
                )
            )
        elif block_type == "tool_use":
            body = json.dumps(block.get("input"), indent=2) if block.get("input") else "{}"
            markdown = f"Tool call: {block.get('name')}\n\n```json\n{body}\n```"
            markdown_parts.append(markdown)
            plaintext_parts.append(f"[tool call {block.get('name')}]")
            blocks.append(
                SegmentBlockInput(
                    block_type="tool_call",
                    body=markdown,
                    raw_data=block,
                )
            )
        elif block_type == "tool_result":
            if block.get("content"):
                result_texts = []
                for entry in block["content"]:
                    if entry.get("type") == "text":
                        result_texts.append(entry.get("text", ""))
                text = "\n".join(result_texts)
            else:
                text = ""
            markdown_parts.append(text)
            plaintext_parts.append(text)
            blocks.append(
                SegmentBlockInput(
                    block_type="tool_result",
                    body=text or "[tool result]",
                    raw_data=block,
                )
            )
        elif block_type == "token_budget":
            placeholder = "[token budget]"
            markdown_parts.append(placeholder)
            plaintext_parts.append(placeholder)
            blocks.append(
                SegmentBlockInput(
                    block_type="markdown",
                    body=json.dumps(block, indent=2),
                    raw_data=block,
                )
            )
        else:
            text = json.dumps(block, indent=2)
            markdown_parts.append(text)
            plaintext_parts.append(text)
            blocks.append(
                SegmentBlockInput(
                    block_type="markdown",
                    body=text,
                    raw_data=block,
                )
            )

    for attachment in message.get("attachments") or []:
        file_name = attachment.get("file_name")
        asset_type = determine_asset_type(file_name)
        mime_type, _ = mimetypes.guess_type(file_name or "")
        assets.append(
            SegmentAssetInput(
                asset_type=asset_type,
                source_reference=json.dumps(attachment),
                file_name=file_name,
                mime_type=mime_type,
                size_bytes=attachment.get("file_size"),
                local_path=None,
            )
        )
    for file_entry in message.get("files") or []:
        file_name = file_entry.get("file_name")
        asset_type = determine_asset_type(file_name)
        mime_type, _ = mimetypes.guess_type(file_name or "")
        assets.append(
            SegmentAssetInput(
                asset_type=asset_type,
                source_reference=json.dumps(file_entry),
                file_name=file_name,
                mime_type=mime_type,
                size_bytes=file_entry.get("file_size"),
                local_path=None,
            )
        )

    if not markdown_parts:
        fallback = message.get("text") or ""
        markdown_parts.append(fallback)
        plaintext_parts.append(fallback)

    content_markdown = "\n\n".join(part for part in markdown_parts if part)
    plaintext = " ".join(part for part in plaintext_parts if part) or content_markdown

    return SegmentInput(
        node_id=message["uuid"],
        parent_node_id=None,
        sequence=sequence,
        source_role=normalize_sender(message.get("sender", "human")),
        segment_type="message",
        content_markdown=content_markdown,
        plaintext=plaintext,
        content_json=message,
        started_at=parse_timestamp(message.get("created_at")),
        ended_at=parse_timestamp(message.get("updated_at")),
        raw_reference=message["uuid"],
        blocks=blocks,
        assets=assets,
    )


def collect_segments(conversation: dict) -> List[SegmentInput]:
    segments: List[SegmentInput] = []
    for index, message in enumerate(conversation.get("chat_messages") or [], start=1):
        segments.append(build_segment(message, sequence=index))
    return segments


def ingest_conversation(conn: psycopg.Connection, conversation: dict, export_dir: Path) -> PersistResult:
    segments = collect_segments(conversation)
    created_at = parse_timestamp(conversation.get("created_at")) or datetime.now(tz=timezone.utc)
    updated_at = parse_timestamp(conversation.get("updated_at")) or created_at

    raw_metadata = {"account": conversation.get("account")}
    source_path = str(export_dir / "conversations.json") + f"#{conversation['uuid']}"
    checksum_input = json.dumps(conversation, sort_keys=True).encode("utf-8")
    checksum = hashlib.sha256(checksum_input).digest()

    return persist_document(
        conn,
        source_system="claude",
        external_id=conversation["uuid"],
        title=conversation.get("name") or "Untitled conversation",
        summary=conversation.get("summary"),
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
    parser = argparse.ArgumentParser(description="Ingest Claude exports into the Tiger database.")
    parser.add_argument(
        "export_path",
        nargs="?",
        type=Path,
        help="Path to the unzipped Claude export directory (containing conversations.json).",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Path to the unzipped Claude export directory (overrides positional argument).",
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
            name = conversation.get("name") or conversation.get("uuid") or "conversation"
            _print_progress(stats, name)

    print("\r" + " " * 120 + "\r", end="")
    print(
        f"Ingested {ingested} conversation(s) from {export_dir} | "
        f"new: {stats['new']} updated: {stats['updated']} unchanged: {stats['unchanged']}"
    )


if __name__ == "__main__":
    run_cli()
