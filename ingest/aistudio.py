from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import psycopg

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

from ingest.db import PersistResult, persist_document
from ingest.models import SegmentAssetInput, SegmentInput


ATTACHMENT_KEYS = {
    "driveDocument": "file",
    "driveImage": "image",
    "driveVideo": "file",
    "driveAudio": "file",
}


@dataclass
class ConversationFile:
    path: Path
    payload: dict


def timezone_from_timestamp(ts: Optional[float]) -> datetime:
    if ts is None:
        return datetime.now(tz=timezone.utc)
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def discover_conversations(root: Path) -> List[ConversationFile]:
    conversations: List[ConversationFile] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if "chunkedPrompt" not in data or "runSettings" not in data:
            continue
        conversations.append(ConversationFile(path=path, payload=data))
    return conversations


def normalize_external_id(root: Path, file_path: Path) -> str:
    try:
        relative = file_path.relative_to(root)
    except ValueError:
        relative = file_path
    return str(relative).replace("\\", "/")


def slugify(text: str) -> str:
    sanitized = [ch if ch.isalnum() else "-" for ch in text]
    slug = "".join(sanitized).strip("-")
    return slug or "conversation"


def normalize_role(role: str | None) -> str:
    if not role:
        return "other"
    lowered = role.lower()
    if lowered in {"user", "system", "assistant", "tool"}:
        return lowered
    if lowered == "model":
        return "assistant"
    return "other"


def build_segments(conversation: dict, conversation_id: str) -> List[SegmentInput]:
    segments: List[SegmentInput] = []
    chunks = conversation.get("chunkedPrompt", {}).get("chunks", [])
    for index, chunk in enumerate(chunks, start=1):
        role = normalize_role(chunk.get("role"))
        attachments: List[SegmentAssetInput] = []
        attachment_placeholders: List[str] = []
        for key, asset_type in ATTACHMENT_KEYS.items():
            if key not in chunk:
                continue
            entry = chunk[key] or {}
            drive_id = entry.get("id") or "unknown"
            source_reference = f"{key}:{drive_id}"
            attachments.append(
                SegmentAssetInput(
                    asset_type=asset_type,
                    source_reference=source_reference,
                    file_name=None,
                    mime_type=None,
                    size_bytes=None,
                    local_path=None,
                )
            )
            attachment_placeholders.append(f"[{asset_type.upper()} attachment: {drive_id}]")

        text_content: Optional[str] = chunk.get("text")
        if text_content:
            content_markdown = text_content
        elif attachment_placeholders:
            content_markdown = "\n".join(attachment_placeholders)
        else:
            content_markdown = ""

        plaintext = content_markdown
        segment_type = "message"
        if chunk.get("isThought"):
            segment_type = "metadata"
        if attachments and not text_content:
            segment_type = "attachment"

        segments.append(
            SegmentInput(
                node_id=f"{conversation_id}-{index}",
                parent_node_id=None,
                sequence=index,
                source_role=role,
                segment_type=segment_type,
                content_markdown=content_markdown,
                plaintext=plaintext,
                content_json=chunk,
                started_at=None,
                ended_at=None,
                raw_reference=str(index),
                blocks=[],
                assets=attachments,
                is_noise=chunk.get("isThought", False),
            )
        )
    return segments


def ingest_conversation(
    conn: psycopg.Connection,
    conversation: ConversationFile,
    root: Path,
) -> PersistResult:
    path = conversation.path
    payload = conversation.payload
    stats = path.stat()
    timestamps = timezone_from_timestamp(stats.st_mtime)
    title = path.name
    external_id = normalize_external_id(root, path)
    conversation_id = slugify(external_id)
    segments = build_segments(payload, conversation_id)

    raw_metadata: Dict[str, object] = {
        "export_path": external_id,
        "runSettings": payload.get("runSettings"),
        "systemInstruction": payload.get("systemInstruction"),
        "pendingInputs": payload.get("chunkedPrompt", {}).get("pendingInputs"),
        "source_system": "aistudio",
    }

    checksum_input = json.dumps(payload, sort_keys=True).encode("utf-8")
    checksum = hashlib.sha256(checksum_input).digest()

    return persist_document(
        conn,
        source_system="other",
        external_id=external_id,
        title=title,
        summary=None,
        created_at=timestamps,
        updated_at=timestamps,
        raw_metadata=raw_metadata,
        source_path=str(path),
        checksum=checksum,
        raw_payload=payload,
        segments=segments,
    )


def _print_progress(stats: Dict[str, int], current: Path) -> None:
    message = (
        f"new: {stats['new']} | updated: {stats['updated']} | "
        f"unchanged: {stats['unchanged']} | {current.name}"
    )
    print(f"\r{message}\x1b[K", end="", flush=True)


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Ingest Google AI Studio exports into the Tiger database.")
    parser.add_argument(
        "export_path",
        nargs="?",
        type=Path,
        help="Path to the AI Studio export directory.",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Path to the AI Studio export directory (overrides positional argument).",
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
    if not export_dir.exists() or not export_dir.is_dir():
        raise FileNotFoundError(f"Export directory {export_dir} was not found or is not a directory.")

    conversations = discover_conversations(export_dir)
    if args.limit is not None:
        conversations = conversations[: args.limit]

    stats = {"new": 0, "updated": 0, "unchanged": 0}
    with psycopg.connect(dsn) as conn:
        ingested = 0
        for conv in conversations:
            try:
                result = ingest_conversation(conn, conv, export_dir)
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
            _print_progress(stats, conv.path)

    print("\r" + " " * 120 + "\r", end="")
    print(
        f"Ingested {ingested} conversation(s) from {export_dir} | "
        f"new: {stats['new']} updated: {stats['updated']} unchanged: {stats['unchanged']}"
    )


if __name__ == "__main__":
    run_cli()
