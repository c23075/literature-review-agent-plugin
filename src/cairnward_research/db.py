"""SQLite settings and migrations for research.db."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, event

MIGRATIONS = Path(__file__).parent / "migrations"


def unmanaged_table(name: str) -> bool:
    """Virtual tables (and their shadow tables) created outside the SQLAlchemy metadata."""
    return name.startswith(("chunks_fts", "vec_"))


# WAL for concurrency; FULL sync so a power cut can't lose committed data; secure_delete
# overwrites deleted rows in the file.
PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=FULL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA secure_delete=ON",
    "PRAGMA busy_timeout=5000",
)


def make_engine(path: Path, *, vectors: bool = False) -> Engine:
    """vectors=True loads the sqlite-vec extension on every connection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        if vectors:
            import sqlite_vec

            dbapi_conn.enable_load_extension(True)
            sqlite_vec.load(dbapi_conn)
            dbapi_conn.enable_load_extension(False)
        cur = dbapi_conn.cursor()
        for pragma in PRAGMAS:
            cur.execute(pragma)
        cur.close()

    return engine


def upgrade(engine: Engine, db: str = "research") -> None:
    """Bring the database to the latest schema (creates it if new)."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
