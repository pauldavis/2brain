from __future__ import annotations

import os
from functools import lru_cache

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


class Settings:
    """Simple settings container backed by environment variables."""

    def __init__(self) -> None:
        if load_dotenv:
            load_dotenv()

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required for the document service. Populate it via .env or the environment."
            )
        self.database_url = database_url

        probes = os.environ.get("IVFFLAT_PROBES", "").strip()
        if probes:
            try:
                parsed = int(probes)
            except ValueError as exc:  # pragma: no cover - defensive config guard
                raise RuntimeError("IVFFLAT_PROBES must be an integer") from exc
            self.ivfflat_probes = parsed if parsed > 0 else None
        else:
            self.ivfflat_probes = 10


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
