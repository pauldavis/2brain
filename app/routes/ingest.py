from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from app.auth import get_current_user
from app.db import connection
from app.services.vectorizer import backfill_loop

# Assuming these are available in the pythonpath
from ingest.chatgpt import ingest_conversation as ingest_chatgpt
from ingest.claude import ingest_conversation as ingest_claude

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _detect_and_ingest(
    temp_dir: Path, source_type: Literal["auto", "claude", "chatgpt"]
) -> None:
    """
    Background task to process the extracted directory.
    """
    conversations_file = temp_dir / "conversations.json"
    if not conversations_file.exists():
        logger.error(f"No conversations.json found in {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return

    try:
        with open(conversations_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logger.error("conversations.json is not a list")
            return

        if not data:
            logger.warning("Empty conversations list")
            return

        # Detection logic
        detected_type = source_type
        if source_type == "auto":
            first = data[0]
            if "chat_messages" in first:
                detected_type = "claude"
            elif "mapping" in first:
                detected_type = "chatgpt"
            else:
                logger.error("Could not auto-detect export format")
                return

        logger.info(f"Ingesting {len(data)} conversations as {detected_type}")

        # Ingest
        with connection() as conn:
            for i, conv in enumerate(data):
                try:
                    if detected_type == "claude":
                        ingest_claude(conn, conv, temp_dir)
                    elif detected_type == "chatgpt":
                        ingest_chatgpt(conn, conv, temp_dir)

                    # Commit per conversation to match CLI behavior
                    conn.commit()
                except Exception as e:
                    logger.error(f"Failed to ingest conversation {i}: {e}")
                    conn.rollback()

        logger.info("Ingestion complete")

        # Trigger vectorization
        logger.info("Starting vector backfill...")
        count = backfill_loop()
        logger.info(f"Vector backfill complete: {count} segments processed.")

    except Exception as e:
        logger.exception(f"Critical error during ingestion: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/upload")
async def upload_export(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source: Literal["auto", "claude", "chatgpt"] = "auto",
    user=Depends(get_current_user),
) -> dict[str, str]:
    """
    Upload a ZIP export from Claude or ChatGPT.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")

    # Create a temp directory
    temp_dir = Path(tempfile.mkdtemp(prefix="2brain_ingest_"))
    zip_path = temp_dir / "upload.zip"

    try:
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Extract
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        # Remove zip to save space
        os.remove(zip_path)

        # Enqueue background task
        background_tasks.add_task(_detect_and_ingest, temp_dir, source)

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "accepted", "message": "Ingestion started in background"}
