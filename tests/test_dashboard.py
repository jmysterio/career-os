from datetime import date, datetime, timedelta

from careeros import dashboard
from careeros.guide.service import experiences, promo_map
from careeros.storage.models import GuideLink, JournalEntry, Win

from test_guide import nb, session  # noqa: F401

TODAY = date.today()


def add(s, ago, text, kind="task", reviewed=True, link=None):
    e = JournalEntry(day=(TODAY - timedelta(days=ago)).isoformat(), kind=kind, text=text, created_at=datetime.now(),
                     source="slack", status="done", reviewed=reviewed)
    s.add(e)
    s.flush()
    if link:
        s.add(GuideLink(item_id=link.id, entry_id=e.id, created_at=datetime.now()))
    return e


def test_dashboard_numbers_match_the_promo_map(nb):
    dd, *_ = nb
    with session(dd) as s:
        item = experiences(s)[0]
        a = add(s, 0, "Ran the refresh", link=item)
        add(s, 1, "Kudos from Pat", kind="recognition")
        add(s, 2, "Unchecked thing", reviewed=False)
        add(s, 100, "Old linked work", link=item)
        s.add(Win(day=a.day, title="Ran the refresh", size="large", impact="x", entry_id=a.id, created_at=datetime.now()))
        s.commit()
        d = dashboard.build(s, TODAY)
        pm = promo_map(s)
    g6 = pm["progress"][6]
    assert d["grades"][0] == dict(grade=6, shown=g6["shown"] + g6["strong"], total=g6["total"], strong=g6["strong"],
                                  started=g6["started"], pct=round(100 * (g6["shown"] + g6["strong"]) / g6["total"]))
    assert d["skills"]["total"] == len(pm["rising"] + pm["steady"])
    assert (d["wins"], d["kudos"], d["queue"]) == (1, 1, 1)
    assert len(d["weeks"]) == dashboard.WEEKS and d["weeks"][-1]["n"] == 2  # the linked record and its win this week
    assert sum(w["n"] for w in d["weeks"]) == 2  # 100 days ago is outside the 12 weeks
    assert d["weeks"][-1]["pct"] == 100 and d["next"] is not None


def test_home_is_the_dashboard_not_a_day_list(nb):
    dd, c, *_ = nb
    with session(dd) as s:
        add(s, 0, "Something done today")
        s.commit()
    html = c.get("/").text
    assert "Grade 5 to 6, aiming at 7" in html and html.count("<rect class=") == dashboard.WEEKS
    assert "wins this half" in html and "kudos this half" in html and 'href="/sheet?show=todo"' in html
    assert "Something done today" not in html and "<h2>Today</h2>" not in html
    assert 'data-sync="google"' in html and 'action="/journal/add"' in html


def test_home_without_a_guide_says_how_to_load_it(tmp_path):
    from starlette.testclient import TestClient
    from careeros.config import DataDir
    from careeros.web.app import create_app
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    html = TestClient(create_app(dd), base_url="http://127.0.0.1").get("/").text
    assert "careeros guide import" in html and html.count("<rect class=") == dashboard.WEEKS
