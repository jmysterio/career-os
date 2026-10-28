from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from careeros.storage.models import JournalAttachment


def test_foreign_keys_enforced(session):
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    with pytest.raises(IntegrityError):
        session.add(JournalAttachment(entry_id=999, kind="notes", body="x", created_at=datetime.now()))
        session.commit()


def test_old_notebook_with_prototype_tables_still_opens(tmp_path):
    """Notebooks made before the prototype was retired keep its (empty) tables; they're simply ignored."""
    import sqlite3
    from careeros.storage.db import init_db, make_engine, make_session_factory
    from careeros.storage.models import JournalEntry
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE claim (id INTEGER PRIMARY KEY, subject VARCHAR)")
        c.execute("INSERT INTO claim (subject) VALUES ('old')")
    engine = make_engine(db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        assert s.query(JournalEntry).count() == 0
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM claim").fetchone()[0] == 1  # left alone, never dropped
