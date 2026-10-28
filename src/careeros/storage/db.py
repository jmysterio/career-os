"""SQLite engine factory. Foreign keys are enforced on every connection."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_engine(db_path: Path | str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    # create_all never alters an existing table, so add columns introduced after a notebook was made.
    added = {
        "journal_entry": [("source", "VARCHAR NOT NULL DEFAULT ''"), ("status", "VARCHAR NOT NULL DEFAULT ''"),
                          ("external_id", "VARCHAR"), ("kind_was", "VARCHAR NOT NULL DEFAULT ''"),
                          ("ai_read", "BOOLEAN NOT NULL DEFAULT 0"), ("reviewed", "BOOLEAN NOT NULL DEFAULT 0"),
                          ("work_item_id", "INTEGER REFERENCES work_item(id)"),
                          ("grouped", "BOOLEAN NOT NULL DEFAULT 0"), ("work_fixed", "BOOLEAN NOT NULL DEFAULT 0")],
        "win": [("by_ai", "BOOLEAN NOT NULL DEFAULT 0")],
        "guide_link": [("by_ai", "BOOLEAN NOT NULL DEFAULT 0")],
    }
    with engine.begin() as c:
        for table, cols in added.items():
            have = {r[1] for r in c.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in cols:
                if name not in have:
                    c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
