from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import get_current_user
from app.config import get_settings
from app.routes import admin, attachments, chat, documents, ingest, search, stats

# Ensure INFO-level logs from app modules show up when running under uvicorn.
# Uvicorn configures its own loggers; this ensures our application loggers
# have a handler/level as well.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(
    title="2brain Document Service",
    description="Unified API for browsing and searching ingested ChatGPT and Claude exports.",
    version="0.1.0",
)


# Custom middleware to ensure CORS headers are always present, even on errors
class CORSErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "*")

        # Handle preflight OPTIONS requests immediately
        if request.method == "OPTIONS":
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Max-Age": "600",
                },
            )

        try:
            response = await call_next(request)
        except Exception as e:
            # On exception, return error with CORS headers
            logging.exception("Request failed with exception")
            return Response(
                content=str(e),
                status_code=500,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                },
            )

        # Ensure CORS headers on all responses
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

        return response


# Add custom CORS middleware first (handles errors and OPTIONS)
app.add_middleware(CORSErrorMiddleware)

# Standard CORS middleware as backup
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(documents.router, dependencies=[Depends(get_current_user)])
app.include_router(attachments.router, dependencies=[Depends(get_current_user)])
app.include_router(search.router, dependencies=[Depends(get_current_user)])
app.include_router(stats.router, dependencies=[Depends(get_current_user)])
app.include_router(ingest.router, dependencies=[Depends(get_current_user)])
app.include_router(admin.router, dependencies=[Depends(get_current_user)])
app.include_router(chat.router, dependencies=[Depends(get_current_user)])
