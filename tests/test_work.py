"""Grouping records of the same piece of work, so it counts once on the Promo map (fake Claude)."""
from datetime import datetime

from sqlalchemy import select

from careeros.guide import work
from careeros.guide.service import evidence, experiences
from careeros.storage.models import GuideLink, JournalEntry, Win, WorkItem

from test_guide import form, nb, session  # noqa: F401


def add(s, text, day, kind="note"):
    e = JournalEntry(day=day, kind=kind, text=text, created_at=datetime.now(), source="slack")
    s.add(e)
    s.commit()
    return e.id


def by_text(answers):
    """A reader that answers by record text; anything unknown is a one-off."""
    seen = []

    def reader(open_work, records):
        seen.append(dict(open_work=open_work, records=records))
        return {r["id"]: answers.get(r["text"]) for r in records}
    reader.seen = seen
    return reader


def test_three_records_of_one_deployment_count_once(nb):
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "Deploy meeting", "2026-10-20", "meeting")
        b = add(s, "Deploy thread", "2026-10-21", "conversation")
        c = add(s, "Deployed to prod", "2026-10-22", "task")
        d = add(s, "Lunch", "2026-10-22")
        item = experiences(s)[0].id
        for eid in (a, b, c):
            s.add(GuideLink(item_id=item, entry_id=eid, created_at=datetime.now()))
        s.commit()
        assert evidence(s)[item]["points"] == 3
        r = work.group(s, reader=by_text({"Deploy meeting": {"new": "Pine release", "key": "n1"},
                                          "Deploy thread": {"join": "n1"}, "Deployed to prod": {"join": "n1"}}))
        assert r == dict(read=4, joined=2, new=1, alone=1, failed=0)
        w = s.scalar(select(WorkItem))
        assert (w.title, w.day, w.by_ai) == ("Pine release", "2026-10-22", True)  # dated by its last record
        assert evidence(s)[item]["points"] == 1
        s.add(Win(day="2026-10-22", title="Shipped Pine", size="large", entry_id=c, created_at=datetime.now()))
        s.commit()
        w_id = s.scalar(select(Win.id))
        s.add(GuideLink(item_id=item, win_id=w_id, created_at=datetime.now()))
        s.commit()
        assert evidence(s)[item]["points"] == 4  # the group scores once, at its strongest evidence
        assert s.get(JournalEntry, d).work_item_id is None


def test_later_batches_join_earlier_work_and_bad_ids_are_ignored(nb):
    dd, *_ = nb
    with session(dd) as s:
        add(s, "Refresh kickoff", "2026-10-01")
        work.group(s, reader=by_text({"Refresh kickoff": {"new": "Full refresh", "key": "n1"}}))
        wid = s.scalar(select(WorkItem.id))
        add(s, "Refresh done", "2026-10-05")
        add(s, "Way later", "2026-11-30")
        add(s, "Made-up id", "2026-10-06")
        reader = by_text({"Refresh done": {"join": f"W{wid}"}, "Way later": {"join": f"W{wid}"},
                          "Made-up id": {"join": "W999"}})
        r = work.group(s, reader=reader)
        assert reader.seen[0]["open_work"] == [dict(id=f"W{wid}", title="Full refresh", day="2026-10-01")]
        texts = {e.text: e.work_item_id for e in s.scalars(select(JournalEntry))}
        assert texts == {"Refresh kickoff": wid, "Refresh done": wid, "Way later": None, "Made-up id": None}
        assert r["joined"] == 1 and r["alone"] == 2


def test_a_piece_of_work_cannot_chain_on_for_months(nb):
    dd, *_ = nb
    with session(dd) as s:
        add(s, "Sus deploy 1", "2026-08-01")
        work.group(s, reader=by_text({"Sus deploy 1": {"new": "Sustainment release", "key": "k"}}))
        wid = s.scalar(select(WorkItem.id))
        for i, day in enumerate(["2026-08-12", "2026-08-24", "2026-09-04"]):  # each within 14 days of the last
            add(s, f"Sus deploy {i + 2}", day)
            work.group(s, reader=by_text({f"Sus deploy {i + 2}": {"join": f"W{wid}"}}))
        days = sorted(e.day for e in s.scalars(select(JournalEntry).where(JournalEntry.work_item_id == wid)))
        assert days == ["2026-08-01", "2026-08-12", "2026-08-24"]  # Sept 4 is past 30 days from Aug 1


def test_dry_run_saves_nothing(nb):
    dd, *_ = nb
    with session(dd) as s:
        add(s, "A", "2026-10-01")
        add(s, "B", "2026-10-02")
        r = work.group(s, dry_run=True, reader=by_text({"A": {"new": "Pine", "key": "k"}, "B": {"join": "k"}}))
        assert r["groups"] == {"Pine": ["A", "B"]}
        assert s.scalar(select(WorkItem)) is None and not any(e.grouped for e in s.scalars(select(JournalEntry)))


def test_split_and_group_in_the_queue_stick(nb):
    dd, c, token, _ = nb
    with session(dd) as s:
        a = add(s, "Deploy meeting", "2026-10-20")
        b = add(s, "Deploy thread", "2026-10-21")
        x = add(s, "Runbook draft", "2026-10-21")
        work.group(s, reader=by_text({"Deploy meeting": {"new": "Pine release", "key": "n"},
                                      "Deploy thread": {"join": "n"}}))
        wid = s.scalar(select(WorkItem.id))
    page = c.get("/sheet?show=all").text
    assert "AI: Part of: Pine release" in page and "2 records" in page
    form(c, f"/sheet/{b}/split", token, ret="show=all")
    form(c, f"/sheet/{x}/group", token, item=str(wid), ret="show=all")
    with session(dd) as s:
        eb, ex = s.get(JournalEntry, b), s.get(JournalEntry, x)
        assert (eb.work_item_id, eb.work_fixed) == (None, True) and (ex.work_item_id, ex.work_fixed) == (wid, True)
        # a regroup run leaves records you grouped or split by hand alone
        work.group(s, everything=True, reader=by_text({"Deploy thread": {"join": f"W{wid}"}, "Runbook draft": None}))
        assert s.get(JournalEntry, b).work_item_id is None and s.get(JournalEntry, x).work_item_id == wid
    form(c, f"/sheet/{a}/group", token, title="Brand new piece", ret="show=all")
    form(c, f"/sheet/{x}/split", token, ret="show=all")
    with session(dd) as s:
        assert s.get(WorkItem, wid) is None  # nobody left in it, so it's gone
        assert s.get(WorkItem, s.get(JournalEntry, a).work_item_id).title == "Brand new piece"


def test_removing_the_last_record_drops_its_group(nb):
    from careeros.storage.removal import remove_entry
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "Only one", "2026-10-01")
        work.group(s, reader=by_text({"Only one": {"new": "Solo", "key": "k"}}))
        remove_entry(s, a)
        assert s.scalar(select(WorkItem)) is None


def test_a_run_skips_records_another_run_grouped_meanwhile(nb):
    dd, *_ = nb
    with session(dd) as s:
        add(s, "A", "2026-10-01")
        add(s, "B", "2026-10-02")

        def reader(open_work, records):  # the app's own run groups B while this reader is thinking
            with session(dd) as other:
                work.group(other, reader=by_text({"B": {"new": "Other run's work", "key": "k"}}))
            return {r["id"]: {"new": "Mine", "key": r["id"]} for r in records}
        work.group(s, reader=reader)
        assert [w.title for w in s.scalars(select(WorkItem))] == ["Other run's work"]  # this run left both alone


def test_confirming_a_row_locks_it_even_when_ungrouped(nb):
    from careeros.guide.service import confirm
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "One-off", "2026-10-01")
        work.group(s, reader=by_text({}))
        confirm(s, a)
        seen = by_text({"One-off": {"new": "Late idea", "key": "k"}})
        work.group(s, everything=True, reader=seen)
        assert s.get(JournalEntry, a).work_item_id is None and seen.seen == []


def test_dry_run_from_the_cli_never_locks_the_real_notebook(nb, monkeypatch):
    import json
    import sqlite3
    from typer.testing import CliRunner
    from careeros.cli import app
    dd, *_ = nb
    with session(dd) as s:
        add(s, "A", "2026-10-01")
        add(s, "B", "2026-10-02")
    monkeypatch.setattr(work, "BATCH", 1)
    monkeypatch.setattr(work, "pending", work.pending)
    calls = []

    def fake_ask(prompt, data, timeout=0):
        recs = json.loads(data)["records"]
        if calls:  # second batch: the first one has already written to the scratch copy
            with sqlite3.connect(dd.db, timeout=0.2) as live:
                live.execute("update journal_entry set text = text")  # raises "database is locked" if held
        calls.append(1)
        return json.dumps({"results": [{"id": r["id"], "work": {"new": "Pine", "key": "k"}} for r in recs]})
    monkeypatch.setattr(work, "ask", fake_ask)
    r = CliRunner().invoke(app, ["guide", "group", "--dry-run", "--data-dir", str(dd.root)])
    assert r.exit_code == 0 and "nothing was saved" in r.output, r.output
    with session(dd) as s:
        assert s.scalar(select(WorkItem)) is None
