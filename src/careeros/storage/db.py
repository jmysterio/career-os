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
    with engine.begin() as c:
        have = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(journal_entry)")}
        if "source" not in have:
            c.exec_driver_sql("ALTER TABLE journal_entry ADD COLUMN source VARCHAR NOT NULL DEFAULT ''")
        if "external_id" not in have:
            c.exec_driver_sql("ALTER TABLE journal_entry ADD COLUMN external_id VARCHAR")


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
