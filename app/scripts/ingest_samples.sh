#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL}"
BATCH_ID="${INGEST_BATCH_ID:-$(uuidgen)}"
INGESTED_BY="${INGESTED_BY:-$USER}"
INGEST_VERSION="${INGEST_VERSION:-dev-trial}"

run_chatgpt() {
  local sample_dir="$1"
  python -m ingest.chatgpt "$sample_dir" --limit 2
}

export INGEST_BATCH_ID="$BATCH_ID"
export INGESTED_BY
export INGEST_VERSION
export INGEST_SOURCE=chatgpt

run_chatgpt "docs/samples/chatgpt-ba5563b5c3415eaafdf5ee5ec34a0edbd2e4aea7f576d6f0daec2fae6b38036d-2025-11-04-21-39-10-df903d010ae647a1aa18180d1aaccfbd"
