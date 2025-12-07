# Project: 2brain

## Project Overview

This project, "2brain," is a full-stack application designed to unify browsing and searching of ingested ChatGPT and Claude exports. It consists of a SvelteKit frontend and a Python-based FastAPI backend. The application allows users to view and search documents, with advanced search capabilities including BM25 and hybrid vector search.

**Frontend:**
- **Framework:** SvelteKit
- **Styling:** Tailwind CSS with DaisyUI
- **Key Dependencies:** `vite`, `svelte`, `tailwindcss`, `daisyui`

**Backend:**
- **Framework:** FastAPI
- **Database:** PostgreSQL
- **Search:** BM25, Hybrid (BM25 + Vector), with OpenAI for query embedding.
- **Key Dependencies (inferred):** `fastapi`, `psycopg`, `uvicorn`, `python-dotenv`, `openai`. Note: No `requirements.txt` was found, so this list is based on imports found in the source code.

**Architecture:**
The frontend and backend are decoupled. The SvelteKit frontend consumes the FastAPI backend service. The backend service connects to a PostgreSQL database for data storage and retrieval. Configuration for the backend is managed via environment variables.

## Building and Running

### Frontend (Viewer)

1.  **Navigate to the viewer directory:**
    ```bash
    cd viewer
    ```
2.  **Install dependencies:**
    ```bash
    npm install
    ```
3.  **Run the development server:**
    ```bash
    npm run dev -- --open
    ```
The frontend will be available at `http://localhost:5173` by default and will connect to the backend API at `http://localhost:8100`.

### Backend (FastAPI Service)

1.  **Set up the Python environment:**
    A `.venv` directory is present, suggesting a Python virtual environment is used. To activate it:
    ```bash
    source .venv/bin/activate
    ```
2.  **Install dependencies:**
    There is no `requirements.txt` file. You may need to install the dependencies manually. Based on the source code, the following dependencies are likely required:
    ```bash
    pip install fastapi uvicorn psycopg python-dotenv openai
    ```
3.  **Configure the environment:**
    The application requires a database connection. Copy the `.env.tiger.example` to `.env` and fill in the database credentials:
    ```bash
    cp .env.tiger.example .env
    ```
    Edit the `.env` file with your database connection details.

4.  **Run the backend server:**
    The backend can be run using `uvicorn`. From the root of the project:
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
    ```
    The API will be available at `http://localhost:8100`.

## Development Conventions

- The backend code follows a modular structure, with routes, services, and database logic separated into different files.
- The frontend uses TypeScript and Svelte 5.
- The project uses `git` for version control.
- The database schema is managed through SQL migration files in the `migrations` directory.
