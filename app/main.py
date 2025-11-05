from __future__ import annotations

from fastapi import FastAPI

from app.routes import documents, search

app = FastAPI(
    title="2brain Document Service",
    description="Unified API for browsing and searching ingested ChatGPT and Claude exports.",
    version="0.1.0",
)

app.include_router(documents.router)
app.include_router(search.router)
