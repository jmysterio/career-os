import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from careeros.cli import app as cli
from careeros.config import DataDir, NotDemoData, resolve
from datetime import date

from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import Claim, JournalAttachment, JournalEntry
from careeros.web.app import create_app

BASE = "http://127.0.0.1"


@pytest.fixture
def seeded(tmp_path):
    root = tmp_path / "demo"
    r = CliRunner().invoke(cli, ["demo", "seed", "--data-dir", str(root)])
    assert r.exit_code == 0, r.output
    dd = DataDir(root)
    app = create_app(dd)
    return dd, TestClient(app, base_url=BASE), app.state.csrf_token


def anchor_id(dd) -> int:
    from careeros.storage.models import Activity
    with make_session_factory(make_engine(dd.db))() as s:
        return s.scalar(select(Activity).where(Activity.title.contains("R-2026-10-B"))).id


def form(c, path, token, **data):
    return c.post(path, data={"csrf": token, **data}, follow_redirects=False)


def test_refuses_non_demo_dir(tmp_path):
    (tmp_path / "real").mkdir()
    with pytest.raises(NotDemoData):
        create_app(DataDir(tmp_path / "real"))


def test_host_origin_and_csrf_checks(seeded):
    dd, c, tok = seeded
    assert TestClient(create_app(dd), base_url="http://evil.example.com").get("/").status_code == 400
    assert c.get("/").status_code == 200 and c.get("/releases").status_code == 200
    assert c.post("/claims/1/approve", data={}).status_code == 403                     # no token
    assert c.post("/claims/1/approve", data={"csrf": "x"}).status_code == 403          # wrong token
    r = c.post("/claims/1/approve", data={"csrf": tok}, headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 403                                                        # cross origin
    assert "default-src 'none'" in c.get("/releases").headers["content-security-policy"]


def test_imported_text_is_escaped(seeded):
    dd, c, tok = seeded
    aid = anchor_id(dd)
    form(c, f"/episodes/{aid}/impact", tok, text="<script>alert(1)</script>")
    html = c.get("/releases").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_page_shows_layers_provenance_and_traps(seeded):
    _, c, _ = seeded
    html = c.get("/releases").text
    assert "made-up demo data" in html and "cos://obs/" in html
    assert "What happened" in html and "What I did" in html and "Why it mattered" in html
    assert "maybe related" in html and "Why did this matter?" in html
    assert "Team deployed 12 changes" in html or "team deployed 12 changes" in html.lower()


def test_review_flow_approve_publish_export(seeded):
    dd, c, tok = seeded
    aid = anchor_id(dd)
    engine = make_engine(dd.db)
    with make_session_factory(engine)() as s:
        obs = [x.id for x in s.scalars(select(Claim).where(Claim.layer == "observation"))]
        attr = [x.id for x in s.scalars(select(Claim).where(Claim.layer == "attribution"))]
    # publish with nothing approved is blocked with a message, not a crash
    r = form(c, f"/episodes/{aid}/publish", tok)
    assert r.status_code == 303 and "Not%20saved%20yet" in r.headers["location"]
    for cid in obs + attr:
        assert form(c, f"/claims/{cid}/approve", tok).status_code == 303
    form(c, f"/episodes/{aid}/impact", tok, text="Fewer failed deployments")
    with make_session_factory(engine)() as s:
        imp = s.scalar(select(Claim).where(Claim.layer == "interpretation")).id
    form(c, f"/claims/{imp}/approve", tok)
    form(c, f"/episodes/{aid}/publish", tok)
    r = CliRunner().invoke(cli, ["export", "--anchor", str(aid), "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    md = next(dd.exports.glob("*.md")).read_text()
    assert "[attribution | human_approved]" in md and "Fewer failed deployments" in md


def test_unlink_via_ui_persists_constraint(seeded):
    dd, c, tok = seeded
    aid = anchor_id(dd)
    html = c.get("/releases").text
    assert "This isn't part of it" in html
    with make_session_factory(make_engine(dd.db))() as s:
        from careeros.storage.models import Activity
        m1 = s.scalar(select(Activity).where(Activity.title.contains("DEMO-101"))).id
    form(c, f"/episodes/{aid}/unlink", tok, activity_id=m1)
    r = CliRunner().invoke(cli, ["import", "--data-dir", str(dd.root)])  # full rebuild
    assert r.exit_code == 0
    assert "DEMO-101-fix-validation" not in c.get("/releases").text.split("What I did")[0]


def test_cli_edit_flags_and_purge_flow(seeded):
    dd, c, tok = seeded
    runner = CliRunner()
    assert runner.invoke(cli, ["demo", "edit", "--data-dir", str(dd.root)]).exit_code == 0
    assert runner.invoke(cli, ["demo", "tombstone", "--data-dir", str(dd.root)]).exit_code == 0
    r = runner.invoke(cli, ["purge", "--source", "demo-sheet", "--reason", "test", "--yes",
                            "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert b"October B" not in dd.db.read_bytes()


def test_data_files_are_owner_only(seeded):
    import stat
    dd, c, _ = seeded
    c.get("/releases")
    for p in [dd.db, dd.secret_file, *dd.root.glob("careeros.db-*"), *dd.approvals.glob("*.toml"),
              *(dd.inbox / "processed").glob("*.json")]:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, p
    assert stat.S_IMODE(dd.root.stat().st_mode) == 0o700


def test_export_without_published_version_is_a_friendly_error(seeded):
    dd, _, _ = seeded
    r = CliRunner().invoke(cli, ["export", "--anchor", str(anchor_id(dd)), "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "Publish approved claims" in r.output and "Traceback" not in r.output


def test_real_browser_origin_is_accepted_but_null_origin_is_not(seeded):
    """Regression: Referrer-Policy no-referrer made browsers send 'Origin: null' on form posts."""
    dd, c, tok = seeded
    ok = c.post("/theme", data={"csrf": tok, "theme": "light"}, headers={"Origin": "http://127.0.0.1:8765"},
                follow_redirects=False)
    assert ok.status_code == 303
    assert c.post("/theme", data={"csrf": tok, "theme": "light"}, headers={"Origin": "null"},
                  follow_redirects=False).status_code == 403
    assert c.get("/releases").headers["referrer-policy"] == "same-origin"


def test_dark_by_default_and_theme_toggle_persists(seeded):
    _, c, tok = seeded
    assert 'data-theme="dark"' in c.get("/releases").text
    r = c.post("/theme", data={"csrf": tok, "theme": "light"}, follow_redirects=False)
    assert "theme=light" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert 'data-theme="light"' in c.get("/releases").text
    c.post("/theme", data={"csrf": tok, "theme": "dark"})
    assert 'data-theme="dark"' in c.get("/releases").text


def test_page_avoids_internal_jargon(seeded):
    _, c, _ = seeded
    html = c.get("/releases").text
    import re
    visible = re.sub(r"<[^>]+>", " ", html.split("</style>", 1)[1])  # text a person can see
    for word in ("rule_checked", "human_approved", "by template", "claims", "Attribution", "Interpretation",
                 "Observation", "unverified", "suggested/ambiguous"):
        assert word not in visible, word


def test_journal_add_show_and_remove(seeded):
    dd, c, token = seeded
    r = form(c, "/journal/add", token, kind="meeting", text="Met with Sam about the rollout")
    assert r.status_code == 303 and r.headers["location"] == "/"
    form(c, "/journal/add", token, kind="document", text="Wrote the <b>runbook</b>")
    html = c.get("/").text
    assert "Met with Sam about the rollout" in html and "Had a meeting" in html
    assert "&lt;b&gt;runbook" in html and "<b>runbook" not in html
    assert "1 meeting, 1 document" in html
    from careeros.storage.models import JournalEntry
    with make_session_factory(make_engine(dd.db))() as s:
        eid = s.scalar(select(JournalEntry.id).where(JournalEntry.kind == "meeting"))
    form(c, f"/journal/{eid}/delete", token)
    assert "Met with Sam" not in c.get("/").text


def test_journal_needs_csrf_and_ignores_future_or_bad_dates(seeded):
    dd, c, token = seeded
    assert c.post("/journal/add", data={"kind": "note", "text": "x"}).status_code == 403
    form(c, "/journal/add", token, kind="bogus", text="Back-dated", day="2999-01-01")
    form(c, "/journal/add", token, kind="note", text="Garbled date", day="nope")
    html = c.get("/").text
    assert "Back-dated" in html and "Garbled date" in html and "Something else" in html


def test_theme_toggle_returns_to_same_page(seeded):
    dd, c, token = seeded
    assert form(c, "/theme", token, theme="light", next="/releases").headers["location"] == "/releases"
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
    html = c.get("/").text
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
    assert "Before you paste" in html and "IRS" in html and "Who or what</b>" in html


def test_personal_notebook_is_journal_only(tmp_path):
    root = tmp_path / "mine"
    r = CliRunner().invoke(cli, ["notebook", "init", "--data-dir", str(root)])
    assert r.exit_code == 0, r.output
    dd = DataDir(root)
    assert (root / ".metadata_never_index").exists() and oct(root.stat().st_mode & 0o777) == "0o700"
    c = TestClient(create_app(dd), base_url=BASE)
    html = c.get("/").text
    assert "practice notebook" not in html and "Releases" not in html
    assert c.get("/releases").status_code == 404
    assert CliRunner().invoke(cli, ["demo", "seed", "--data-dir", str(root)]).exit_code == 1
    assert not dd.is_demo
    assert CliRunner().invoke(cli, ["import", "--data-dir", str(root)]).exit_code != 0


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
    assert sorted(z.namelist()) == ["entries.csv", "pasted_notes.csv", "wins.csv"]
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
