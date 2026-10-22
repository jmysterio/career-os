import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import SourceRecord


def test_foreign_keys_enforced(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
    Session = make_session_factory(engine)
    with Session() as s, pytest.raises(IntegrityError):
        s.add(SourceRecord(connector_instance_id="nope", native_record_id="x"))
        s.commit()
