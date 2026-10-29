from datetime import date, datetime, timedelta

from typer.testing import CliRunner

from careeros import digest
from careeros.cli import app as cli
from careeros.guide.service import experiences
from careeros.storage.models import GuideLink, JournalEntry, Win

from test_guide import nb, session  # noqa: F401

TODAY = date.today()


def day(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def rec(s, ago, text, kind="task", source="slack", activity="", status="done", reviewed=True):
    e = JournalEntry(day=day(ago), kind=kind, text=text, created_at=datetime.now(), source=source, activity=activity,
                     status=status, reviewed=reviewed)
    s.add(e)
    s.flush()
    return e


def week(s):
    item = experiences(s)[0]
    a = rec(s, 1, "Deployed OCC 5.1 to production", activity="deployment")
    rec(s, 3, "Deployed CT 1.9 to production", activity="deployment")
    rec(s, 2, 'Pat Lee: "Huge shout-out for the 3.4 release"', kind="recognition", source="kudos")
    rec(s, 1, "Still to do", status="open")
    rec(s, 20, "An older deploy", activity="deployment")
    s.add(Win(day=day(1), title="Shipped OCC 5.1 with no downtime", impact="", size="large", entry_id=a.id,
              created_at=datetime.now()))
    s.add(GuideLink(item_id=item.id, entry_id=a.id, created_at=datetime.now()))
    s.commit()
    return item


def test_the_week_counts_wins_records_kudos_links_and_activity(nb):
    dd, *_ = nb
    with session(dd) as s:
        item = week(s)
        d = digest.build(s, TODAY)
    assert d["first"] == TODAY - timedelta(days=6) and [w.title for w in d["wins"]] == ["Shipped OCC 5.1 with no downtime"]
    assert d["records"] == 3 and len(d["kudos"]) == 1  # the open task doesn't count
    assert dict(d["sources"]) == {"Slack tracker items": 2, "kudos": 1}
    assert d["gained"] == [dict(name=item.name, topic=d["gained"][0]["topic"], n=1)]
    assert [(c["key"], c["n"]) for c in d["activity"]] == [("deployment", 2)]
    assert any('without "why it mattered"' in n["text"] and n["link"] == "/wins" for n in d["nudges"])
    assert any(n["text"].startswith("Aim for next") for n in d["nudges"])


def test_no_nudges_when_nothing_is_wrong(session):
    session.add(Win(day=day(1), title="Wrote the runbook", impact="Anyone can run a refresh.", size="large",
                    created_at=datetime.now()))
    session.commit()
    d = digest.build(session, TODAY)
    assert d["nudges"] == [] and not d["has_guide"] and len(d["wins"]) == 1


def test_quiet_area_and_full_queue_get_nudges(nb):
    dd, *_ = nb
    from careeros.guide.topics import topic_of
    with session(dd) as s:
        topic = topic_of(experiences(s)[1].name)
        old = rec(s, 90, "Planned the spring sandbox refresh")
        w = Win(day=old.day, title="Planned the spring sandbox refresh", impact="No team lost data.", size="large",
                entry_id=old.id, created_at=datetime.now())
        s.add(w)
        s.flush()
        for g in experiences(s):  # enough evidence that the area isn't an Aim for next, just quiet
            if topic_of(g.name) == topic:
                s.add(GuideLink(item_id=g.id, win_id=w.id, created_at=datetime.now()))
        for i in range(digest.QUEUE_NUDGE):
            rec(s, 2, f"Unchecked {i}", reviewed=False)
        s.commit()
        nudges = digest.build(s, TODAY)["nudges"]
    assert any(n["text"] == f"Nothing new for {topic.name} in 60 days (last: {day(90)})." for n in nudges)
    assert not any(n["text"].startswith(f"Aim for next in {topic.name}") for n in nudges)
    assert any(n["link"] == "/sheet?show=todo" and f"{digest.QUEUE_NUDGE} records" in n["text"] for n in nudges)


def test_every_nudge_link_resolves_and_the_page_shows_the_week(nb):
    dd, c, *_ = nb
    with session(dd) as s:
        week(s)
        for i in range(digest.QUEUE_NUDGE):
            rec(s, 2, f"Unchecked {i}", reviewed=False)
        s.commit()
        nudges = digest.build(s, TODAY)["nudges"]
    assert {n["link"] for n in nudges} >= {"/promo", "/wins", "/sheet?show=todo"}
    for n in nudges:
        assert c.get(n["link"]).status_code == 200, n["link"]
    page = c.get("/digest").text
    assert "Shipped OCC 5.1 with no downtime" in page and "Huge shout-out" in page and "deployments</a>: 2 this week" in page
    assert 'href="/digest"' in c.get("/").text  # in the Menu
    assert c.get(f"/digest?week={day(7)}").status_code == 200 and c.get("/digest?week=nonsense").status_code == 200


def test_notify_shows_a_line_written_by_code(nb, monkeypatch):
    dd, *_ = nb
    with session(dd) as s:
        week(s)
    shown = []
    monkeypatch.setattr("careeros.sync_all.mac_notify", lambda title, msg: shown.append((title, msg)))
    r = CliRunner().invoke(cli, ["digest", "notify", "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert shown and shown[0][0] == "Career OS: your week"
    assert shown[0][1].startswith("This week: 1 win, 3 records, 1 kudos,") and "/digest" in shown[0][1]
