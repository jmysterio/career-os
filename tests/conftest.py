import pytest

from careeros.storage.db import init_db, make_engine, make_session_factory


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    """Tests never start the real `claude` command; a test that needs Claude passes a fake reader or patches ask."""
    from careeros import claude_cli

    def refuse():
        raise claude_cli.ClaudeError("tests never call the real Claude")
    monkeypatch.setattr(claude_cli, "_claude", refuse)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s
