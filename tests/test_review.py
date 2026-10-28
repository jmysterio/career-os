"""The Intake Review Queue page and Claude's read-through of records against the leveling guide (with a fake Claude)."""
import json
import sqlite3
from datetime import date, datetime

import pytest
from sqlalchemy import select

from careeros.claude_cli import ClaudeError
from careeros.google import calendar as gcal
from careeros.guide import ai_review
from careeros.guide.service import evidence, promo_map
from careeros.storage.db import init_db, make_engine
from careeros.storage.models import GuideLink, JournalEntry, Win

from test_guide import form, nb, session  # noqa: F401


def add(s, text, kind="note", source="slack", day="2026-10-20"):
    e = JournalEntry(day=day, kind=kind, text=text, created_at=datetime.now(), source=source)
    s.add(e)
    s.commit()
    return e.id


def fake(answers):
    """A reader that answers by record text."""
    seen = []

    def reader(guide, themes, records):
        seen.append(dict(guide=guide, records=records))
        return {r["id"]: answers.get(r["text"], {"guide": [], "kind": r["kind"], "win": None}) for r in records}
    reader.seen = seen
    return reader


def test_old_notebooks_get_the_new_columns(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE win (id INTEGER PRIMARY KEY, day VARCHAR, title VARCHAR, impact TEXT, size VARCHAR,"
                  " theme VARCHAR, entry_id INTEGER, created_at DATETIME)")
    init_db(make_engine(db))
    with sqlite3.connect(db) as c:
        assert "by_ai" in {r[1] for r in c.execute("PRAGMA table_info(win)")}
        assert {"kind_was", "ai_read", "reviewed"} <= {r[1] for r in c.execute("PRAGMA table_info(journal_entry)")}


def test_review_links_fixes_kinds_and_drafts_wins(nb):
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "Refreshed the full sandbox and ran the post-refresh steps")
        b = add(s, "10:00 AM Standup", kind="meeting", source="calendar")
        c = add(s, "Ran the CI/CD pipeline program for three teams", kind="conversation")
        answers = {
            "Refreshed the full sandbox and ran the post-refresh steps": dict(guide=["E1", "S2", "E99"], kind="task"),
            "10:00 AM Standup": dict(guide=[], kind="note"),
            "Ran the CI/CD pipeline program for three teams": dict(guide=["E3"], kind="conversation", win=dict(
                title="Led CI/CD across three teams", impact="Teams shipped on one pipeline.", size="large",
                theme="Leadership")),
        }
        r = ai_review.review(s, reader=fake(answers))
        assert r == dict(read=3, links=3, wins=1, kinds=1, failed=0)
        ea, eb = s.get(JournalEntry, a), s.get(JournalEntry, b)
        assert (ea.kind, ea.kind_was, ea.status, ea.ai_read) == ("task", "note", "done", True)
        assert eb.kind == "meeting" and eb.kind_was == ""  # calendar items stay meetings
        assert all(l.by_ai for l in s.scalars(select(GuideLink)))
        w = s.scalar(select(Win))
        assert (w.entry_id, w.size, w.by_ai, w.theme) == (c, "large", True, "Leadership")
        pm = promo_map(s)
        g7 = [x for row in pm["rows"] for x in row["cells"][7] if x["wins"]]
        assert g7 and g7[0]["status"] == "shown"  # a large win is 4 points, counted once with its entry
        assert ai_review.review(s, reader=fake({})) == dict(read=0, links=0, wins=0, kinds=0, failed=0)


def test_review_keeps_user_links_and_checked_rows(nb):
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "Mine")
        b = add(s, "Checked")
        from careeros.guide.service import experiences
        item = experiences(s)[0].id
        s.add(GuideLink(item_id=item, entry_id=a, created_at=datetime.now()))
        s.get(JournalEntry, b).reviewed = True
        s.commit()
        reader = fake({"Mine": dict(guide=["E4"], kind="note")})
        ai_review.review(s, reader=reader)
        assert [r["text"] for r in reader.seen[0]["records"]] == ["Mine"]
        assert [(l.item_id, l.by_ai) for l in s.scalars(select(GuideLink))] == [(item, False)]


def test_review_failure_changes_nothing(nb):
    dd, *_ = nb
    with session(dd) as s:
        add(s, "x")

        def down(*a):
            raise ClaudeError("no")
        with pytest.raises(ClaudeError):
            ai_review.review(s, reader=down)
        assert not s.scalar(select(JournalEntry)).ai_read


def test_sheet_one_click_actions(nb):
    dd, c, token, _ = nb
    with session(dd) as s:
        a = add(s, "Wrote the refresh runbook")
        b = add(s, "Next row")
        ai_review.review(s, reader=fake({"Wrote the refresh runbook": dict(guide=["E1"], kind="document", win=dict(
            title="Wrote the refresh runbook", impact="Anyone can run a refresh.", size="medium"))}))
    page = c.get("/sheet").text
    assert "Wrote the refresh runbook" in page and "AI, was Other" in page and "AI win" in page
    assert "1 guide link and 1 win picked by Claude" in page

    r = form(c, f"/sheet/{a}/kind", token, kind="task", ret="show=all&source=any&kind=any&page=1")
    assert r.status_code == 303 and r.headers["location"].endswith(f"#r{a}") and "show=all" in r.headers["location"]
    form(c, f"/sheet/{a}/win", token, size="large", ret="")
    with session(dd) as s:
        e, w = s.get(JournalEntry, a), s.scalar(select(Win))
        assert (e.kind, e.kind_was, e.status) == ("task", "", "done") and (w.size, w.by_ai) == ("large", False)
        lid = s.scalar(select(GuideLink.id).where(GuideLink.entry_id == a))
    r = form(c, f"/sheet/{a}/ok", token, ret="", after=str(b))
    assert r.headers["location"].endswith(f"#r{b}")
    with session(dd) as s:
        assert s.get(JournalEntry, a).reviewed and not any(l.by_ai for l in s.scalars(select(GuideLink)))
    assert "Wrote the refresh runbook" not in c.get("/sheet").text  # checked rows leave "Not checked yet"
    assert "Wrote the refresh runbook" in c.get("/sheet?show=checked").text

    form(c, f"/sheet/link/{lid}/delete", token, ret="")
    with session(dd) as s:
        assert s.scalar(select(GuideLink)) is None  # removed from the entry and the win made from it
    form(c, f"/sheet/{a}/unwin", token, ret="")
    form(c, f"/sheet/{b}/win", token, size="small", ret="")
    with session(dd) as s:
        assert [w.entry_id for w in s.scalars(select(Win))] == [b]
    assert c.post(f"/sheet/{a}/kind", data={"csrf": "nope", "kind": "task"}).status_code == 403


def test_sheet_script_updates_rows_in_place(nb):
    dd, c, token, _ = nb
    with session(dd) as s:
        a = add(s, "Wrote the refresh runbook")
    js = c.get("/static/sheet.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert "script-src 'self'" in c.get("/sheet").headers["content-security-policy"]
    assert 'src="/static/sheet.js"' in c.get("/sheet").text
    hdr = {"X-Sheet": "1"}
    ret = "show=todo&source=any&kind=any&page=1"
    r = c.post(f"/sheet/{a}/kind", data={"csrf": token, "kind": "document", "ret": ret}, headers=hdr)
    assert r.status_code == 200 and r.text.lstrip().startswith(f'<tr id="r{a}"') and 'value="document" class="on"' in r.text
    r = c.post(f"/sheet/{a}/win", data={"csrf": token, "size": "medium", "ret": ret}, headers=hdr)
    assert "Wrote the refresh runbook" in r.text and 'value="medium" class="on"' in r.text
    r = c.post(f"/sheet/{a}/ok", data={"csrf": token, "ret": ret}, headers=hdr)
    assert r.status_code == 200 and r.headers["x-row"] == "gone" and r.text == ""
    r = c.post(f"/sheet/{a}/undo", data={"csrf": token, "ret": "show=checked"}, headers=hdr)
    assert r.headers["x-row"] == "gone"
    assert c.post(f"/sheet/{a}/ok", data={"csrf": "nope", "ret": ret}, headers=hdr).status_code == 403


def test_remove_keeps_it_out_of_syncs_and_can_restore(nb):
    from careeros.slack.importer import new_items
    from careeros.slack.parse import SlackItem
    from careeros.storage.models import RemovedEntry
    dd, c, token, _ = nb
    with session(dd) as s:
        e = JournalEntry(day="2026-10-20", kind="meeting", text="9:00 AM Not my meeting", created_at=datetime.now(),
                         source="calendar", external_id="cal@1")
        sl = JournalEntry(day="2026-10-20", kind="conversation", text="Slack thing", created_at=datetime.now(),
                          source="slack", external_id="slack:C1/p1")
        s.add_all([e, sl])
        s.commit()
        mine = Win(day=e.day, title="My own win", entry_id=e.id, created_at=datetime.now())
        drafted = Win(day=e.day, title="Claude's draft", entry_id=e.id, created_at=datetime.now(), by_ai=True)
        s.add_all([mine, drafted])
        s.commit()
        eid, sid = e.id, sl.id
    r = c.post(f"/sheet/{eid}/remove", data={"csrf": token, "ret": "show=all"}, headers={"X-Sheet": "1"})
    assert r.headers["x-row"] == "gone"
    form(c, f"/sheet/{sid}/remove", token, ret="show=all")
    with session(dd) as s:
        assert s.get(JournalEntry, eid) is None
        assert [(w.title, w.entry_id) for w in s.scalars(select(Win))] == [("My own win", None)]
        ev = gcal.Event("cal@1", "2026-10-20", datetime(2026, 10, 20, 9), None, "Not my meeting")
        assert gcal.sync(s, [ev], date(2026, 10, 19), date(2026, 10, 21))["added"] == 0
        assert not new_items(s, [SlackItem("slack:C1/p1", "2026-10-20", "Slack thing", "", "", None, "Slack tracker")])
        rid = s.scalar(select(RemovedEntry.id).where(RemovedEntry.external_id == "cal@1"))
    page = c.get("/sheet?show=removed").text
    assert "Not my meeting" in page and "Restore" in page
    assert "Not my meeting" not in c.get("/sheet?show=all").text
    form(c, f"/sheet/removed/{rid}/restore", token, ret="show=removed")
    with session(dd) as s:
        back = s.scalar(select(JournalEntry).where(JournalEntry.external_id == "cal@1"))
        assert back and back.kind == "meeting" and s.get(RemovedEntry, rid) is None


def test_calendar_skip_rule(nb):
    from typer.testing import CliRunner
    from careeros.cli import app as cli
    dd, *_ = nb
    with session(dd) as s:
        for i, t in enumerate(["11:45 AM  [EXT] IRS Sustainment DSU — OCC", "12:00 PM  [EXT] irs sustainment dsu - TAS",
                               "1:00 PM  Refresh review"]):
            s.add(JournalEntry(day="2026-10-20", kind="meeting", text=t, created_at=datetime.now(), source="calendar",
                               external_id=f"u{i}"))
        s.commit()
    r = CliRunner().invoke(cli, ["calendar", "skip", "IRS Sustainment DSU", "--data-dir", str(dd.root)])
    assert r.exit_code == 0 and "Removed 2" in r.output, r.output
    with session(dd) as s:
        assert [e.text for e in s.scalars(select(JournalEntry))] == ["1:00 PM  Refresh review"]
        new = gcal.Event("u9", "2026-10-21", datetime(2026, 10, 21, 11, 45), None, "[EXT] IRS Sustainment DSU — OCC")
        assert gcal.sync(s, [new], date(2026, 10, 21), date(2026, 10, 21))["added"] == 0
    assert "Sustainment" in CliRunner().invoke(cli, ["calendar", "skip", "--data-dir", str(dd.root)]).output


def test_last_pulled_status(nb):
    from careeros.storage.models import SyncRun
    from careeros.storage.sync_log import status
    dd, c, *_ = nb
    with session(dd) as s:
        assert status(s)["slack"]["at_text"] == "never" and status(s)["slack"]["ok"] is False
        s.add(JournalEntry(day="2026-10-26", kind="task", text="old", created_at=datetime(2026, 10, 27, 12), source="slack"))
        s.commit()
        st = status(s, now=datetime(2026, 10, 28, 8, 30))
        assert st["slack"]["estimated"] and st["slack"]["at_text"] == "yesterday at 12:00 PM"
        assert st["slack"]["ok"] is False and "yesterday" in st["slack"]["hint"]
        s.add(SyncRun(source="slack", at=datetime(2026, 10, 27, 18, 5), added=4))
        s.add(SyncRun(source="calendar", at=datetime(2026, 10, 28, 8, 1), added=2))
        s.commit()
        st = status(s, now=datetime(2026, 10, 28, 8, 30))
        assert st["slack"]["ok"] and st["slack"]["added"] == 4 and st["slack"]["newest"] == "Mon, Oct 26"
        assert st["calendar"]["ok"] and st["calendar"]["at_text"] == "today at 8:01 AM"
        assert status(s, now=datetime(2026, 10, 28, 18))["slack"]["ok"] is False  # tonight's log is ready now
        assert status(s, now=datetime(2026, 10, 29, 9))["calendar"]["ok"] is False
        gcal.sync(s, [], date(2026, 10, 28), date(2026, 10, 28))
        assert s.scalar(select(SyncRun).where(SyncRun.source == "calendar").order_by(SyncRun.id.desc())).added == 0
    html = c.get("/").text
    assert "Google Calendar</b> last pulled today" in html and "Slack tracker</b> last pulled" in html
    assert "Last pulled in" in c.get("/sheet").text


TASKS_TEXT = """Tasks in list L1 for me@example.com:
- deploy occ to uat (ID: T1)
  Status: completed
  Completed: 2026-10-27T13:43:50.919Z
  Updated: 2026-10-27T13:43:51.275Z

- 10 questions (ID: T2)
  Status: needsAction
  Updated: 2026-10-20T12:14:45.468Z

- write (the) plan (ID: T3)
  Status: needsAction
  Due: 2026-10-30T00:00:00.000Z
  Notes: draft first
  Updated: 2026-10-27T12:00:00.000Z
"""


def test_google_tasks_parse_and_merge(nb):
    from careeros.google import tasks as gtasks
    dd, *_ = nb
    ts = gtasks.parse_tasks(TASKS_TEXT)
    assert [(t.title, t.done, t.gid) for t in ts] == [("deploy occ to uat", True, "T1"), ("10 questions", False, "T2"),
                                                      ("write (the) plan", False, "T3")]
    assert ts[2].notes == "draft first"
    from careeros.claude_cli import _result_text
    assert len(gtasks.parse_tasks(_result_text(json.dumps({"result": TASKS_TEXT})))) == 3
    assert gtasks.parse_lists("- Week of 7/14/25 (ID: A1)\n  Updated: 2026-10-22T04:01:38.851Z\n- Old (ID: B2)\n"
                              "  Updated: 2025-07-28T12:39:12.431Z")[0][0] == "A1"
    with session(dd) as s:
        s.add(JournalEntry(day="2026-10-20", kind="task", text="deploy occ to uat", created_at=datetime.now(),
                           source="tasks", external_id="task:legacy", status="open"))
        s.commit()
        assert gtasks.merge(s, ts) == dict(added=2, updated=1)
        rows = {e.text: e for e in s.scalars(select(JournalEntry).where(JournalEntry.source == "tasks"))}
        assert rows["deploy occ to uat"].status == "done" and rows["deploy occ to uat"].external_id == "gtask:T1"
        assert gtasks.merge(s, ts) == dict(added=0, updated=0)


def test_sync_google_runs_every_step(nb, monkeypatch):
    import json as _json
    import time
    from careeros.google import connector, summaries, tasks as gtasks
    dd, c, token, _ = nb
    today = date.today().isoformat()
    monkeypatch.setattr(connector, "fetch", lambda first, last: [
        {"id": "ev1", "title": "Release go/no-go", "start": f"{today}T09:00:00-04:00", "end": f"{today}T09:30:00-04:00",
         "links": []}])
    monkeypatch.setattr(gtasks, "fetch", lambda since: (gtasks.parse_tasks(TASKS_TEXT), 1))
    monkeypatch.setattr(summaries, "summarize_pending", lambda s, f, l, progress=None: dict(summarized=0, failed=0))

    def fake_ask(prompt, data, timeout=0):
        recs = _json.loads(data)["records"]
        return _json.dumps({"results": [dict(id=r["id"], guide=["E0"], kind=r["kind"], win=None) for r in recs]})
    monkeypatch.setattr(ai_review, "ask", fake_ask)
    assert c.post("/sync/google", data={"csrf": token}, headers={"X-Sync": "1"}).json() == {"started": True}
    for _ in range(200):
        job = c.get("/sync/status").json()["google"]
        if job["state"] != "running":
            break
        time.sleep(0.05)
    assert [st["state"] for st in job["steps"]] == ["done", "error", "done", "done"]
    assert "1 task list couldn't be read" in job["steps"][1]["detail"] and job["state"] == "partial"
    assert job["message"] == "Google synced: 1 meeting and 3 tasks new."
    assert "4 guide links" in job["steps"][3]["detail"]
    page = c.get("/").text
    assert 'data-sync="google"' in page and "/static/sync.js" in page and "Sync calendar" not in page
    assert c.get("/static/sync.js").status_code == 200


def test_sync_never_deletes_entries_you_built_on(nb):
    dd, *_ = nb
    with session(dd) as s:
        e = JournalEntry(day="2026-10-20", kind="meeting", text="9:00 AM Go/no-go", created_at=datetime.now(),
                         source="calendar", external_id="gone@1")
        s.add(e)
        s.commit()
        s.add(Win(day=e.day, title="Ran go/no-go", entry_id=e.id, created_at=datetime.now()))
        s.commit()
        assert gcal.sync(s, [], date(2026, 10, 19), date(2026, 10, 21))["removed"] == 0
        assert s.get(JournalEntry, e.id) is not None
