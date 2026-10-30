import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from careeros.cli import app as cli
from careeros.config import DataDir, NotDemoData, resolve
from datetime import date

from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import GuideItem, JournalAttachment, JournalEntry, Win
from careeros.web.app import create_app

BASE = "http://127.0.0.1"


@pytest.fixture
def seeded(tmp_path):
    """An empty practice notebook (made-up-data folder), for testing the pages from a clean start."""
    dd = DataDir(tmp_path / "demo")
    dd.init_demo()
    app = create_app(dd)
    return dd, TestClient(app, base_url=BASE), app.state.csrf_token


def form(c, path, token, **data):
    return c.post(path, data={"csrf": token, **data}, follow_redirects=False)


def test_refuses_unmarked_dir(tmp_path):
    (tmp_path / "real").mkdir()
    with pytest.raises(NotDemoData):
        create_app(DataDir(tmp_path / "real"))


def test_host_origin_and_csrf_checks(seeded):
    dd, c, tok = seeded
    assert TestClient(create_app(dd), base_url="http://evil.example.com").get("/").status_code == 400
    assert c.get("/").status_code == 200
    assert c.post("/journal/add", data={"kind": "note", "text": "x"}).status_code == 403              # no token
    assert c.post("/journal/add", data={"csrf": "x", "kind": "note", "text": "x"}).status_code == 403  # wrong token
    r = c.post("/journal/add", data={"csrf": tok, "kind": "note", "text": "x"},
               headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 403                                                                       # cross origin
    assert "default-src 'none'" in c.get("/").headers["content-security-policy"]


def test_prototype_pages_are_gone(seeded):
    _, c, tok = seeded
    assert c.get("/releases").status_code == 404
    assert c.post("/claims/1/approve", data={"csrf": tok}).status_code in (404, 405)
    assert "Releases" not in c.get("/").text


def test_demo_seed_fills_every_page_with_made_up_data(tmp_path):
    root = tmp_path / "practice"
    r = CliRunner().invoke(cli, ["demo", "seed", "--data-dir", str(root)])
    assert r.exit_code == 0 and "Practice notebook ready" in r.output, r.output
    assert CliRunner().invoke(cli, ["demo", "seed", "--data-dir", str(root)]).exit_code == 0  # twice is harmless
    dd = DataDir(root)
    with make_session_factory(make_engine(dd.db))() as s:
        assert s.query(JournalEntry).count() == 10 and s.query(Win).count() == 2 and s.query(GuideItem).count() == 10
    c = TestClient(create_app(dd), base_url=BASE)
    home = c.get("/").text
    assert "practice notebook" in home and "Grade 5 to 6, aiming at 7" in home and "Sync Google" not in home
    assert "Release readiness review" in c.get("/meetings").text
    for path in ("/wins", "/promo", "/sheet?show=all", "/meetings", "/conversations", "/documents", "/tasks", "/other",
                 "/search?q=rollback"):
        assert c.get(path).status_code == 200, path
    assert "Planned and ran a full sandbox refresh" in c.get("/wins").text
    assert "Sandbox and test data strategy" in c.get("/promo").text


def test_data_files_are_owner_only(seeded):
    import stat
    dd, c, tok = seeded
    form(c, "/journal/add", tok, kind="note", text="x")
    for p in [dd.db, dd.secret_file, *dd.root.glob("careeros.db-*")]:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, p
    assert stat.S_IMODE(dd.root.stat().st_mode) == 0o700


def test_real_browser_origin_is_accepted_but_null_origin_is_not(seeded):
    """Regression: Referrer-Policy no-referrer made browsers send 'Origin: null' on form posts."""
    dd, c, tok = seeded
    ok = c.post("/theme", data={"csrf": tok, "theme": "light"}, headers={"Origin": "http://127.0.0.1:8765"},
                follow_redirects=False)
    assert ok.status_code == 303
    assert c.post("/theme", data={"csrf": tok, "theme": "light"}, headers={"Origin": "null"},
                  follow_redirects=False).status_code == 403
    assert c.get("/").headers["referrer-policy"] == "same-origin"


def test_dark_by_default_and_theme_toggle_persists(seeded):
    _, c, tok = seeded
    assert 'data-theme="dark"' in c.get("/").text
    r = c.post("/theme", data={"csrf": tok, "theme": "light"}, follow_redirects=False)
    assert "theme=light" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert 'data-theme="light"' in c.get("/").text
    c.post("/theme", data={"csrf": tok, "theme": "dark"})
    assert 'data-theme="dark"' in c.get("/").text


def test_journal_add_show_and_remove(seeded):
    dd, c, token = seeded
    r = form(c, "/journal/add", token, kind="meeting", text="Met with Sam about the rollout")
    assert r.status_code == 303 and r.headers["location"] == "/meetings?msg=Added."
    form(c, "/journal/add", token, kind="document", text="Wrote the <b>runbook</b>")
    assert "Met with Sam about the rollout" in c.get("/meetings").text
    docs = c.get("/documents").text
    assert "&lt;b&gt;runbook" in docs and "<b>runbook" not in docs
    assert "Met with Sam" not in c.get("/").text  # home is the dashboard, not a day list
    from careeros.storage.models import JournalEntry
    with make_session_factory(make_engine(dd.db))() as s:
        eid = s.scalar(select(JournalEntry.id).where(JournalEntry.kind == "meeting"))
    form(c, f"/journal/{eid}/delete", token)
    assert "Met with Sam" not in c.get("/meetings").text


def test_journal_needs_csrf_and_ignores_future_or_bad_dates(seeded):
    dd, c, token = seeded
    assert c.post("/journal/add", data={"kind": "note", "text": "x"}).status_code == 403
    form(c, "/journal/add", token, kind="bogus", text="Back-dated", day="2999-01-01")
    form(c, "/journal/add", token, kind="note", text="Garbled date", day="nope")
    html = c.get("/other").text
    assert "Back-dated" in html and "Garbled date" in html and "Something else" in html


def test_theme_toggle_returns_to_same_page(seeded):
    dd, c, token = seeded
    assert form(c, "/theme", token, theme="light", next="/wins").headers["location"] == "/wins"
    assert form(c, "/theme", token, theme="light", next="//evil.example").headers["location"] == "/"


def test_journal_attachments_multiple_escaped_and_removed_with_entry(seeded):
    dd, c, token = seeded
    big = "Transcript line <script>alert(1)</script>\n" * 3000
    form(c, "/journal/add", token, kind="meeting", text="Rollout sync", a_kind="transcript",
         a_title="Gemini notes", a_body=big)
    from careeros.storage.models import JournalAttachment, JournalEntry
    with make_session_factory(make_engine(dd.db))() as s:
        eid = s.scalar(select(JournalEntry.id))
    form(c, f"/journal/{eid}/attach", token, a_kind="link", a_body="https://docs.example.com/x")
    form(c, f"/journal/{eid}/attach", token, a_kind="link", a_body="javascript:alert(1)")
    form(c, f"/journal/{eid}/attach", token, a_kind="prompt", a_title="My prompt", a_body="Summarize my week")
    html = c.get("/meetings").text
    assert "Gemini notes" in html and "<script>alert" not in html and "&lt;script&gt;alert(1)" in html
    assert 'href="https://docs.example.com/x"' in html and 'href="javascript' not in html
    assert "Summarize my week" in html
    with make_session_factory(make_engine(dd.db))() as s:
        assert len(list(s.scalars(select(JournalAttachment)))) == 4
    form(c, f"/journal/{eid}/delete", token)
    with make_session_factory(make_engine(dd.db))() as s:
        assert not list(s.scalars(select(JournalAttachment)))


def test_search_finds_titles_and_pasted_text_escaped(seeded):
    dd, c, token = seeded
    form(c, "/journal/add", token, kind="meeting", text="Rollout sync", a_kind="transcript",
         a_title="Gemini notes", a_body="Priya said the <b>Runbook</b> is ready; 100% done_ok")
    form(c, "/journal/add", token, kind="note", text="Unrelated thing")
    html = c.get("/search", params={"q": "runbook"}).text
    assert "Rollout sync" in html and "<mark>Runbook</mark>" in html and "<b>Runbook" not in html
    assert "Unrelated thing" not in html
    assert "Rollout sync" in c.get("/search", params={"q": "priya rollout"}).text
    assert "Nothing found" in c.get("/search", params={"q": "priya zebra"}).text
    assert "Rollout sync" in c.get("/search", params={"q": "100%"}).text
    pct = c.get("/search", params={"q": "%"}).text  # a literal percent sign, not a wildcard
    assert "Rollout sync" in pct and "Unrelated thing" not in pct


def test_page_has_help_text_and_paste_warning(seeded):
    dd, c, token = seeded
    html = c.get("/").text
    assert "Before you paste" in html and "IRS" in html and "Something the syncs missed?" in html


def test_personal_notebook_is_journal_only(tmp_path):
    root = tmp_path / "mine"
    r = CliRunner().invoke(cli, ["notebook", "init", "--data-dir", str(root)])
    assert r.exit_code == 0, r.output
    dd = DataDir(root)
    assert (root / ".metadata_never_index").exists() and oct(root.stat().st_mode & 0o777) == "0o700"
    c = TestClient(create_app(dd), base_url=BASE)
    html = c.get("/").text
    assert "practice notebook" not in html and "Releases" not in html
    r = CliRunner().invoke(cli, ["demo", "seed", "--data-dir", str(root)])
    assert r.exit_code == 1 and "personal notebook" in r.output
    assert not dd.is_demo


def test_personal_init_refuses_synced_folders(tmp_path):
    r = CliRunner().invoke(cli, ["notebook", "init", "--data-dir", str(tmp_path / "Dropbox" / "n")])
    assert r.exit_code == 1 and "synced" in r.output


def test_tabs_list_by_kind_and_tasks_open_first(tmp_path):
    from careeros.google.tasks import Task, sync as sync_tasks
    from datetime import datetime
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    engine = make_engine(dd.db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        s.add(JournalEntry(day=date.today().isoformat(), kind="meeting", text="Rollout sync", created_at=datetime.now()))
        s.flush()
        s.add(JournalAttachment(entry_id=s.scalar(select(JournalEntry.id)), kind="link", title="Notes by Gemini",
                                body="https://docs.google.com/document/d/abc/edit", created_at=datetime.now()))
        when = datetime.now()
        batch = [Task("ship it", True, when), Task("write plan", False, when, notes="draft first")]
        assert sync_tasks(s, batch) == dict(added=2, removed=0)
        assert sync_tasks(s, batch) == dict(added=0, removed=0)
        assert sync_tasks(s, batch[:1]) == dict(added=0, removed=1)
        sync_tasks(s, batch)
    c = TestClient(create_app(dd), base_url=BASE)
    m = c.get("/meetings").text
    assert "Rollout sync" in m and "https://docs.google.com/document/d/abc/edit" in m and "ship it" not in m
    t = c.get("/tasks").text
    assert t.index("Still to do") < t.index("ship it") and "write plan" in t
    assert "write plan" not in c.get("/").text  # open tasks stay off Today
    for path in ("/conversations", "/documents", "/other"):
        assert c.get(path).status_code == 200
    assert 'href="/tasks"' in c.get("/").text


def test_wins_add_from_entry_edit_filter_search_and_export(seeded):
    from careeros.storage.models import Win
    dd, c, token = seeded
    form(c, "/journal/add", token, kind="task", text="Fixed the deploy script", day="2026-03-04")
    with make_session_factory(make_engine(dd.db))() as s:
        eid = s.scalar(select(JournalEntry.id))
    assert "Count this as a win" in c.get("/tasks").text
    r = form(c, "/wins/add", token, title="Fixed the <b>deploy</b> script", size="medium",
             theme="Quality & reliability", entry_id=eid, day="2026-03-04", next="/tasks")
    assert r.status_code == 303 and r.headers["location"].startswith("/tasks?msg=")
    form(c, "/wins/add", token, title="Led the October B release", impact="Shipped on time", size="large",
         theme="Delivery", day="2026-10-02")
    form(c, "/wins/add", token, title="   ")
    form(c, "/wins/add", token, title="Odd input", size="huge", theme="Made up", day="2999-01-01")
    with make_session_factory(make_engine(dd.db))() as s:
        ws = {w.title: w for w in s.scalars(select(Win))}
    assert len(ws) == 3 and ws["Odd input"].size == "small" and ws["Odd input"].theme == ""
    assert ws["Odd input"].day <= date.today().isoformat()
    html = c.get("/wins", params={"year": 2026}).text
    assert "&lt;b&gt;deploy" in html and "<b>deploy" not in html
    assert "From your notebook: Fixed the deploy script" in html
    assert "1 large, 1 medium" in html and "Why did this matter?" in html
    big = c.get("/wins", params={"year": 2026, "size": "large"}).text
    assert "Led the October B release" in big and "deploy</b> script" not in big
    assert "Led the October B" in c.get("/search", params={"q": "on time"}).text

    wid = ws["Fixed the <b>deploy</b> script"].id
    form(c, f"/wins/{wid}/edit", token, title="Fixed the deploy script", impact="No more failed Friday deploys",
         size="medium", theme="Quality & reliability", day="2026-03-04")
    form(c, f"/journal/{eid}/delete", token)  # the win outlives its entry
    md = c.get("/wins/export", params={"year": 2026})
    assert md.headers["content-type"].startswith("text/markdown")
    assert "my-wins-2026.md" in md.headers["content-disposition"]
    body = md.text
    assert body.startswith("# My wins, 2026") and "## Highlights" in body
    assert body.index("Led the October B release") < body.index("### Delivery")
    assert "### Quality & reliability" in body and "No more failed Friday deploys" in body
    assert "Led the October B" not in c.get("/wins/export", params={"year": 2025}).text
    form(c, f"/wins/{wid}/delete", token)
    assert "Fixed the deploy script" not in c.get("/wins", params={"year": 2026}).text


def test_download_everything_is_a_zip_of_csvs_with_formulas_defused(seeded):
    import csv, io, zipfile
    dd, c, token = seeded
    form(c, "/journal/add", token, kind="meeting", text="=HYPERLINK(\"http://evil\")", a_kind="notes",
         a_title="Notes", a_body="Line one,\nline \"two\" with café")
    form(c, "/journal/add", token, kind="task", text="Fixed the deploy script")
    with make_session_factory(make_engine(dd.db))() as s:
        eid = s.scalar(select(JournalEntry.id).where(JournalEntry.kind == "task"))
    form(c, "/wins/add", token, title="Fixed the deploy script", impact="Fewer failed deploys", size="medium",
         entry_id=eid)
    assert "Download everything (CSV)" in c.get("/").text
    r = c.get("/export/everything")
    assert r.headers["content-type"] == "application/zip" and ".zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["entries.csv", "guide_links.csv", "pasted_notes.csv", "wins.csv"]
    read = lambda n: list(csv.DictReader(io.StringIO(z.read(n).decode("utf-8-sig"))))
    entries, notes, wins = read("entries.csv"), read("pasted_notes.csv"), read("wins.csv")
    assert {e["text"] for e in entries} == {"'=HYPERLINK(\"http://evil\")", "Fixed the deploy script"}
    assert notes[0]["body"] == "Line one,\nline \"two\" with café" and notes[0]["entry_text"].startswith("'=")
    assert wins[0]["why_it_mattered"] == "Fewer failed deploys" and wins[0]["entry_text"] == "Fixed the deploy script"


def test_wins_page_works_on_an_existing_notebook(tmp_path):
    import sqlite3
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    con = sqlite3.connect(dd.db)
    con.execute("CREATE TABLE journal_entry (id INTEGER PRIMARY KEY, day VARCHAR, kind VARCHAR, "
                "text VARCHAR, created_at DATETIME)")
    con.commit()
    con.close()
    c = TestClient(create_app(dd), base_url=BASE)
    assert c.get("/wins").status_code == 200 and 'href="/wins"' in c.get("/").text
