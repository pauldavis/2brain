from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import quote_plus

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
            database_url = _build_database_url_from_pg_env()
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL (or PG* env vars) is required for the document service. "
                "Populate it via .env or the environment."
            )
        self.database_url = database_url

        api_host = os.environ.get("API_HOST", "127.0.0.1").strip()
        self.api_host = api_host or "127.0.0.1"

        port_raw = os.environ.get("API_PORT", "8100").strip()
        if not port_raw:
            port_raw = "8100"
        try:
            self.api_port = int(port_raw)
        except ValueError as exc:  # pragma: no cover - defensive config guard
            raise RuntimeError("API_PORT must be an integer") from exc
        if self.api_port <= 0:
            raise RuntimeError("API_PORT must be a positive integer")

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


def _build_database_url_from_pg_env() -> str | None:
    """Build a Postgres URL from standard PG* env vars if DATABASE_URL is absent."""
    host = os.environ.get("PGHOST")
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE")
    user = os.environ.get("PGUSER")
    password = os.environ.get("PGPASSWORD")
    sslmode = os.environ.get("PGSSLMODE", "").strip()

    if host is None or dbname is None or user is None or password is None:
        return None

    user_enc = quote_plus(user)
    password_enc = quote_plus(password)
    base = f"postgresql://{user_enc}:{password_enc}@{host}:{port}/{dbname}"
    if sslmode:
        return f"{base}?sslmode={sslmode}"
    return base
