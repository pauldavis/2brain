from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings


@contextmanager
def connection() -> Generator[psycopg.Connection, None, None]:
    """Yield a psycopg connection with a dict row factory."""
    settings = get_settings()
    conn = psycopg.connect(settings.database_url)
    conn.row_factory = dict_row
    probes = getattr(settings, "ivfflat_probes", None)
    if probes:
        with conn.cursor() as cur:
            cur.execute(f"SET ivfflat.probes = {int(probes)}")
    try:
        yield conn
    finally:
        conn.close()


def get_connection() -> Generator[psycopg.Connection, None, None]:
    """FastAPI dependency that yields a connection per request."""
    with connection() as conn:
        yield conn
