# Ingesting ChatGPT exports

These steps populate the Tiger database with the schema introduced in `migrations/0001_initial_schema.sql` using the sample ChatGPT export under `docs/samples/…`.

## 1. Install dependencies

Create (or reuse) a Python 3.11+ environment and install the minimal packages:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install "psycopg[binary]" python-dotenv
```

> ℹ️ If you use `zsh`, quote the extras spec (`"psycopg[binary]"`) so the shell doesn’t treat the brackets as glob patterns.

`psycopg[binary]` ships prebuilt wheels so no local PostgreSQL headers are required.

## 2. Load database credentials

Reuse the `.env` created earlier:

```bash
source .env
```

Ensure `DATABASE_URL` points at the Tiger instance (for password-based auth) or augment it with `sslrootcert`, `sslcert`, and `sslkey` parameters if you rely on a client certificate.

## 3. Run the ChatGPT ingestion script

```bash
python -m ingest.chatgpt docs/samples/chatgpt-ba5563b5c3415eaafdf5ee5ec34a0edbd2e4aea7f576d6f0daec2fae6b38036d-2025-11-04-21-39-10-df903d010ae647a1aa18180d1aaccfbd
```

Pass `--limit N` to ingest only the first `N` conversations while testing, or use `--env-file path/to/.env` if you prefer the script to load credentials for you. If you like explicit flags, the positional path can be replaced with `--export /path/to/export`.

The script upserts `documents`, adds a new snapshot `document_versions`, and emits the normalized `document_segments`, `segment_blocks`, and `segment_assets` rows (image pointers are linked to the files bundled with the export directory).

## 4. Run the Claude ingestion script

```bash
python -m ingest.claude docs/samples/claude-data-2025-11-04-21-37-00-batch-0000
```

As with the ChatGPT script, you can cap processing with `--limit` or supply `--env-file` to point at a specific credentials file. Prefer `--export /path/to/export` if you’d rather use a named flag. Claude exports model segments block-by-block (text, tool calls/results, voice notes, etc.); the script preserves those blocks in `segment_blocks` and captures attachments from the export metadata.

## 5. Verify the data

```bash
psql "$DATABASE_URL" <<'SQL'
\dt
SELECT source_system, COUNT(*) FROM documents GROUP BY 1;
SELECT COUNT(*) FROM document_segments;
SQL
```

You should see counts greater than zero for all core tables after a successful run.

## 6. Run the AI Studio ingestion script

Google AI Studio exports mix plain files (PDF, CSV, PNG, etc.) and serialized conversations. Point the ingester at the directory that contains everything (the repository currently keeps them under `docs/samples/Google AI Studio`):

```bash
python -m ingest.aistudio "docs/samples/Google AI Studio"
```

The script recursively scans the directory, looking for JSON blobs that include both `runSettings` and `chunkedPrompt` objects. Those are treated as conversations and ingested into `documents`/`document_segments`. File uploads referenced in the conversations (`driveDocument`, `driveImage`, etc.) are preserved as `segment_assets` with their Drive IDs, even when we do not have a local file match yet.

> ℹ️ Many attachments in the current export do not expose a Drive ID → file mapping. The ingester still records the Drive IDs so that we can backfill the links later.
