# Deployment Plan: 2brain to Railway

This document tracks the roadmap for deploying the 2brain system (FastAPI + SvelteKit) to Railway.

## Phase 1: Project Hygiene & Configuration (Local)
*Goal: Ensure the project is buildable and configurable via environment variables.*

- [x] **Standardize Python Dependencies**: Generate `requirements.txt` for the backend based on actual usage.
- [x] **Environment Variables**: Audit code to ensure all secrets (DB URL, OpenAI Key) are loaded from env vars.
- [x] **Port Configuration**: Ensure servers listen on ports defined by `PORT` env var (critical for Railway).

## Phase 2: Authentication & Authorization (Security)
*Goal: Secure the application so only authorized users can view or upload data.*

- [x] **Frontend Auth (SvelteKit)**: 
    - [x] Install `@auth/sveltekit`.
    - [x] Configure an OAuth provider (e.g., GitHub or Google).
    - [x] Implement an **Email Allowlist** to restrict access.
- [x] **Backend Auth (FastAPI)**:
    - [x] Create `get_current_user` dependency.
    - [x] validate JWT tokens passed from the frontend.
- [x] **Secure Communication**: Ensure frontend passes auth tokens in headers when calling backend.

## Phase 3: Ingestion (Uploads)
*Goal: Allow adding new data (Claude/ChatGPT exports) via web UI or remote script.*

- [x] **Backend API**: Create `POST /ingest/upload` endpoint (handling file uploads).
- [x] **Background Processing**: Use `BackgroundTasks` for ingestion to prevent timeouts.
- [x] **Frontend UI**: Build a protected `/admin/upload` page in SvelteKit.
- [x] **CLI Script**: Create `upload_remote.py` for pushing local files to the production API.
- [x] **Vectorizer Service**: Implement Python fallback for embedding generation (replacing DB-side `pgai`).

## Phase 4: Deployment to Railway
*Goal: Get the services running in the cloud.*

- [ ] **Database**: Provision PostgreSQL on Railway.
- [x] **Schema Script**: Created `migrate.py` to manage database schema updates.
- [ ] **Execute Migration**: Run `python migrate.py` against production DB.
- [ ] **Backend Service**: 
    - [ ] Link repo.
    - [ ] Set build command (`pip install -r requirements.txt`).
    - [ ] Set start command (`uvicorn ...`).
- [ ] **Frontend Service**: 
    - [ ] Link repo (Root: `viewer`).
    - [x] Configure Node/Nixpacks build (Installed `adapter-node`).
- [ ] **Networking**: Configure environment variables (`API_URL`, `DATABASE_URL`) to link services.

## Phase 5: Automation (Maintenance)
*Goal: Keep search indices optimized.*

- [x] **Maintenance Endpoint**: Create `POST /admin/refresh-indices` to trigger vector re-indexing/DB vacuum.
- [ ] **Cron Job**: Configure Railway Cron (or curl scheduler) to hit this endpoint periodically.

## Required Environment Variables

### Backend
- `DATABASE_URL`: Connection string to PostgreSQL.
- `OPENAI_API_KEY`: For embedding queries.
- `AUTH_SECRET`: Shared secret for signing JWTs (must match Frontend).
- `ALLOWED_USERS`: Comma-separated emails (e.g. `alice@example.com,bob@example.com`).
- `ADMIN_API_KEY`: Secret key for CLI/Cron access.
- `PORT`: (Automatically set by Railway)

### Frontend
- `AUTH_SECRET`: Shared secret (must match Backend).
- `GITHUB_ID`: GitHub OAuth Client ID.
- `GITHUB_SECRET`: GitHub OAuth Client Secret.
- `ALLOWED_USERS`: Comma-separated emails.
- `API_URL`: Internal URL to the backend service (for server-side actions).
- `PUBLIC_API_BASE`: Public URL to the backend service (for client-side data fetching).
- `PORT`: (Automatically set by Railway)
- `ORIGIN`: The public URL of the frontend (required for CSRF checks).