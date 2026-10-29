import pytest

from careeros.storage.db import init_db, make_engine, make_session_factory


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    """Tests never start the real `claude` command; a test that needs Claude passes a fake reader or patches ask."""
    from careeros import claude_cli

    def refuse():
        raise claude_cli.ClaudeError("tests never call the real Claude")
    monkeypatch.setattr(claude_cli, "_claude", refuse)
    monkeypatch.setattr("careeros.google.summaries._claude", refuse)  # imported by name, so patched separately

    def no_gh(*args):
        from careeros.github.connector import GitHubError
        raise GitHubError("tests never call the real gh")
    monkeypatch.setattr("careeros.github.connector._gh", no_gh)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s
