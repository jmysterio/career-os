"""The Sheet page and Claude's read-through of records against the leveling guide (with a fake Claude)."""
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
