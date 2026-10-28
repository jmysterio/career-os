import pytest

from careeros.storage.db import init_db, make_engine, make_session_factory


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s
