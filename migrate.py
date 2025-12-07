#!/usr/bin/env python3
import logging
import os
import sys
from pathlib import Path
from typing import List

import psycopg
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def get_connection():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)
    return psycopg.connect(dsn, autocommit=True)


def ensure_migrations_table(conn: psycopg.Connection):
    """Create the migrations table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)


def get_applied_migrations(conn: psycopg.Connection) -> set:
    """Return a set of applied migration versions."""
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def record_migration(conn: psycopg.Connection, version: str):
    """Record a migration as applied."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))


def run_sql_file(conn: psycopg.Connection, filepath: Path):
    """Read and execute a SQL file."""
    logger.info(f"Executing {filepath.name}...")
    with open(filepath, "r", encoding="utf-8") as f:
        sql = f.read()

    with conn.cursor() as cur:
        cur.execute(sql)


def apply_migrations(conn: psycopg.Connection, migrations_dir: Path):
    """Apply all pending migrations from the directory."""
    ensure_migrations_table(conn)
    applied = get_applied_migrations(conn)

    # Get all .sql files in the migrations directory, sorted by name
    migration_files = sorted(
        [f for f in migrations_dir.iterdir() if f.is_file() and f.suffix == ".sql"],
        key=lambda f: f.name,
    )

    if not migration_files:
        logger.warning(f"No migration files found in {migrations_dir}")
        return

    new_migrations_count = 0
    for script in migration_files:
        if script.name in applied:
            continue

        logger.info(f"Applying migration: {script.name}")
        try:
            # Run migration in a transaction (though autocommit is True on conn,
            # psycopg blocks might behave differently, but for DDL we generally want
            # either a transaction or explicit steps. Let's use a transaction block.)
            with conn.transaction():
                run_sql_file(conn, script)
                record_migration(conn, script.name)
            new_migrations_count += 1
        except Exception as e:
            logger.error(f"Failed to apply migration {script.name}: {e}")
            sys.exit(1)

    if new_migrations_count == 0:
        logger.info("Database is up to date.")
    else:
        logger.info(f"Successfully applied {new_migrations_count} migrations.")


def apply_repeatable_schema(conn: psycopg.Connection, db_dir: Path):
    """
    Apply repeatable schema definitions (views, functions, indexes)
    found in the db/ directory.
    """
    # These are typically idempotent (CREATE OR REPLACE) or generally safe to run
    # to update definitions.
    logger.info("Applying repeatable schema definitions from db/...")

    sql_files = sorted(
        [f for f in db_dir.iterdir() if f.is_file() and f.suffix == ".sql"],
        key=lambda f: f.name,
    )

    for script in sql_files:
        try:
            # These might contain large index creations, so we log start/finish
            with conn.transaction():
                run_sql_file(conn, script)
        except Exception as e:
            logger.warning(f"Error running {script.name}: {e}")
            # We don't exit here because some might fail if dependencies aren't ready,
            # though ideally they should work.


def main():
    base_dir = Path(__file__).parent.resolve()
    migrations_dir = base_dir / "migrations"
    db_dir = base_dir / "db"

    try:
        with get_connection() as conn:
            logger.info(
                f"Connected to database: {conn.info.dsn_parameters.get('dbname')}"
            )

            # 1. Apply Versioned Migrations
            if migrations_dir.exists():
                apply_migrations(conn, migrations_dir)
            else:
                logger.error(f"Migrations directory not found: {migrations_dir}")
                sys.exit(1)

            # 2. Apply Repeatable Schema (Views, Indexes, etc.)
            # This is optional but ensures views match the new table structures.
            if db_dir.exists():
                apply_repeatable_schema(conn, db_dir)

    except psycopg.OperationalError as e:
        logger.error(f"Could not connect to database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
