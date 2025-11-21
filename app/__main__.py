from __future__ import annotations

import os

import uvicorn

from app.config import get_settings


def _should_reload() -> bool:
    value = os.environ.get("API_RELOAD", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=_should_reload(),
    )


if __name__ == "__main__":  # pragma: no cover - manual invocation helper
    main()
