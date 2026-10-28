"""Impact numbers: activity tags counted once per piece of work (fake Claude)."""
from datetime import date, datetime

from sqlalchemy import select

from careeros.guide import activities, work
from careeros.storage.models import JournalEntry

from test_guide import form, nb, session  # noqa: F401


def add(s, text, day, kind="task", status="done"):
    e = JournalEntry(day=day, kind=kind, text=text, created_at=datetime.now(), source="slack", status=status)
    s.add(e)
    s.commit()
    return e.id


def tags(answers):
    seen = []

    def reader(records):
        seen.append(records)
        return {r["id"]: answers.get(r["text"]) for r in records}
    reader.seen = seen
    return reader


def test_the_list_lives_in_one_place():
    assert len(activities.ACTIVITIES) == 13 and len(activities.KEYS) == 13
    assert {"deployment", "access_request", "branch_audit", "hotfix", "training"} <= activities.KEYS
    for key, label, meaning in activities.ACTIVITIES:
        assert label and meaning


def test_tagging_counts_once_per_piece_of_work_and_skips_open_tasks(nb):
    dd, *_ = nb
    with session(dd) as s:
        add(s, "Deploy meeting", "2026-10-21", "meeting")
        add(s, "Deployed to prod", "2026-10-21")
        add(s, "Deployed to UAT", "2026-10-23")
        add(s, "Deployed hotfix", "2026-03-02")
        add(s, "Deployed last year", "2025-11-03")
        add(s, "Deploy still open", "2026-10-22", status="open")
        add(s, "Made it up", "2026-10-22")
        r = activities.tag(s, reader=tags({"Deploy meeting": "deployment", "Deployed to prod": "deployment",
                                           "Deployed to UAT": "deployment", "Deployed hotfix": "hotfix",
                                           "Deployed last year": "deployment", "Deploy still open": "deployment",
                                           "Made it up": "juggling"}))
        assert r == dict(read=7, tagged=6, failed=0)
        assert s.scalar(select(JournalEntry).where(JournalEntry.text == "Made it up")).activity == ""
        today = date(2026, 10, 28)
        c = {x["key"]: x for x in activities.counts(s, today)}
        assert (c["deployment"]["half"], c["deployment"]["year"], c["deployment"]["all"]) == (3, 3, 4)
        assert (c["hotfix"]["half"], c["hotfix"]["year"]) == (0, 1)
        pine = {"Deploy meeting": {"new": "Pine", "key": "k"}, "Deployed to prod": {"join": "k"},
                "Deployed to UAT": {"join": "k"}}
        work.group(s, reader=lambda ow, recs: {r["id"]: pine.get(r["text"]) for r in recs})
        c = {x["key"]: x for x in activities.counts(s, today)}
        # the meeting and the prod deploy on 10/21 count once; the UAT deploy two days later counts again
        assert c["deployment"]["half"] == 2 and c["deployment"]["all"] == 3
        groups = activities.records(s, "deployment", "half", today)
        assert [(g["title"], g["count"], len(g["records"])) for g in groups] == [("Pine", 2, 3)]


def test_half_year_boundaries():
    w = activities.windows
    assert w(date(2026, 6, 30))["half"] == ("2026-01-01", "2026-06-30")
    assert w(date(2026, 7, 1))["half"] == ("2026-07-01", "2026-07-01")
    assert w(date(2026, 12, 31))["year"] == ("2026-01-01", "2026-12-31")


def test_your_choice_sticks_and_pages_show_the_numbers(nb):
    dd, c, token, _ = nb
    with session(dd) as s:
        eid = add(s, "Refreshed fulldata", date.today().isoformat())
        activities.tag(s, reader=tags({"Refreshed fulldata": "deployment"}))
    row = c.get("/sheet?show=all").text
    assert "Counts as" in row and 'value="deployment" selected' in row
    form(c, f"/sheet/{eid}/activity", token, activity="sandbox_refresh", ret="show=all")
    with session(dd) as s:
        activities.tag(s, everything=True, reader=tags({"Refreshed fulldata": "deployment"}))
        e = s.get(JournalEntry, eid)
        assert (e.activity, e.activity_fixed) == ("sandbox_refresh", True)
    promo = c.get("/promo").text
    assert "By the numbers" in promo and 'href="/impact/sandbox_refresh?window=year"' in promo
    page = c.get("/impact/sandbox_refresh?window=year").text
    assert "1 sandbox refreshes this year" in page and "Refreshed fulldata" in page
    assert c.get("/impact/nope").status_code == 404
    md = c.get("/promo/export").text
    assert "## By the numbers" in md and "| Sandbox refreshes | 1 | 1 | 1 |" in md
