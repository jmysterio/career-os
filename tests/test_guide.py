"""Leveling guide: import, topic grouping, suggestions, links, the promo map, and the promo case export.

Uses a small made-up guide in the same layout as a real export; real guides stay out of the repo.
"""
import csv
import io
import zipfile
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from careeros.cli import app as cli
from careeros.config import DataDir
from careeros.guide.parse import GuideFormatError, parse_guide
from careeros.guide.topics import topic_of
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import GuideItem, GuideLink, JournalEntry, Win
from careeros.web.app import create_app

BASE = "http://127.0.0.1"
G6 = ["Builds CI/CD pipelines for a project.", "Plans sandbox refresh strategies.", "Mentors newer engineers."]
G7 = ["Owns CI/CD pipelines for an engagement.", "Owns the sandbox strategy.", "Runs demos for customers."]


def write_guide(path, g6=G6, g7=G7):
    blank = [""] * 7
    rows = [["Group: Example", *[""] * 6], ["Career Path: Example", *[""] * 6],
            ["", "Grade", "", "Grade 5", "Grade 6", "Grade 7", ""],
            ["Job Profile", "Role Summary", "", "Grade five summary.", "Senior summary.", "Architect summary.", ""],
            ["", "Key Experiences", "", "- Helps with pipelines", "- " + "\n- ".join(g6), "- " + "\n- ".join(g7), ""],
            ["Skills ", *[""] * 6], blank,
            ["Transferable Skills", "Communicate Effectively", "Conveys information clearly.", "2", "3", "4", ""],
            ["", "Learning Mindset", "Keeps learning.", "2", "3", "3", ""],
            ["Path-Specific Skills", "Environment/Sandbox Management", "Manages sandboxes.", "2", "3", "4", ""],
            ["", "*Agentforce", "Guides customers on Agentforce.", "2", "3", "3", ""]]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return path


@pytest.fixture
def nb(tmp_path):
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    init_db(make_engine(dd.db))
    guide = write_guide(tmp_path / "guide.csv")
    r = CliRunner().invoke(cli, ["guide", "import", str(guide), "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    app = create_app(dd)
    return dd, TestClient(app, base_url=BASE), app.state.csrf_token, guide


def session(dd):
    return make_session_factory(make_engine(dd.db))()


def form(c, path, token, **data):
    return c.post(path, data={"csrf": token, **data}, follow_redirects=False)


def test_parse_reads_summaries_experiences_and_skill_targets(tmp_path):
    items = parse_guide(write_guide(tmp_path / "g.csv"))
    exps = [i for i in items if i["kind"] == "experience"]
    assert [i["name"] for i in exps if i["grade"] == 6] == G6 and len(exps) == 7
    skills = {i["name"]: i for i in items if i["kind"] == "skill"}
    assert skills["Agentforce"]["targets"] == {"5": 2, "6": 3, "7": 3}
    assert skills["Communicate Effectively"]["category"] == "Transferable"
    assert skills["Environment/Sandbox Management"]["category"] == "Path-specific"
    assert {i["grade"]: i["name"] for i in items if i["kind"] == "summary"}[7] == "Architect summary."
    (tmp_path / "bad.csv").write_text("a,b\n1,2\n")
    with pytest.raises(GuideFormatError):
        parse_guide(tmp_path / "bad.csv")


def test_experiences_group_into_topics():
    assert [topic_of(t).key for t in G6] == ["pipelines", "sandbox", "knowledge"]
    assert [topic_of(t).key for t in G7] == ["pipelines", "sandbox", "communication"]
    assert topic_of("Something the topics don't cover").key == "other"


def test_win_flow_suggests_then_saves_only_what_user_confirms(nb):
    dd, c, tok, _ = nb
    r = form(c, "/wins/add", tok, title="Automated the sandbox refresh for UAT", size="large", next="/wins")
    assert r.status_code == 303 and r.headers["location"].startswith("/guide/link?win=")
    page = c.get(r.headers["location"]).text
    assert "I ticked the ones that look related" in page
    with session(dd) as s:
        sandbox = {g.grade or 0: g.id for g in s.scalars(select(GuideItem)) if "andbox" in g.name}
        win_id = s.scalar(select(Win.id))
    for gid in sandbox.values():
        assert f'value="{gid}" checked' in page
    with session(dd) as s:
        assert not list(s.scalars(select(GuideLink)))          # nothing is linked until the user saves
    r = form(c, "/guide/link", tok, win=win_id, item=[sandbox[6], sandbox[0]], next="/wins")
    assert r.status_code == 303 and "Linked%20to%202" in r.headers["location"]
    assert "Sandbox and test data strategy (Grade 6)" in c.get("/wins").text
    page = c.get(f"/guide/link?win={win_id}").text
    assert f'value="{sandbox[6]}" checked' in page and f'value="{sandbox[7]}" checked' not in page

    promo = c.get("/promo").text
    assert 'title="Grade 6: 1 of 3 key experiences shown' in promo and 'title="Grade 7: 0 of 3' in promo
    assert "<b>33%</b> <span class=\"muted\">1/3</span>" in promo
    assert "Automated the sandbox refresh for UAT" in promo and "Aim for next" in promo
    md = c.get("/promo/export")
    assert md.headers["content-type"].startswith("text/markdown")
    body = md.text
    assert body.startswith("# Promotion case draft: Grade 5 to Grade 6, with Grade 7 evidence")
    assert "Plans sandbox refresh strategies" in body and "Automated the sandbox refresh for UAT" in body
    assert "## Not shown yet" in body and "Grade 7: Owns the sandbox strategy" in body
    assert "Environment/Sandbox Management (Grade 6 asks for 3, Grade 7 asks for 4)" in body

    form(c, f"/wins/{win_id}/delete", tok)
    with session(dd) as s:
        assert not list(s.scalars(select(GuideLink)))


def test_entry_links_count_once_and_entry_cards_show_hints(nb):
    dd, c, tok, _ = nb
    form(c, "/journal/add", tok, kind="meeting", text="Demo of the pipeline to the customer")
    form(c, "/journal/add", tok, kind="note", text="Lunch")
    html = c.get("/meetings").text
    assert '<span class="meta-label">Might show</span>' in html and "Communication, demos, and solution reviews" in html
    with session(dd) as s:
        eid = s.scalar(select(JournalEntry.id).where(JournalEntry.text.startswith("Demo")))
        demo7 = s.scalar(select(GuideItem.id).where(GuideItem.name.startswith("Runs demos")))
    form(c, "/guide/link", tok, entry=eid, item=[demo7], next="/")
    assert '<span class="meta-label">Shows</span>' in c.get("/meetings").text
    # a win made from that entry starts with the entry's links, and the entry isn't counted twice
    r = form(c, "/wins/add", tok, title="Ran the customer pipeline demo", size="small", entry_id=eid, next="/")
    with session(dd) as s:
        wid = s.scalar(select(Win.id))
    assert f'value="{demo7}" checked' in c.get(r.headers["location"]).text
    form(c, "/guide/link", tok, win=wid, item=[demo7], next="/")
    from careeros.guide.service import evidence
    with session(dd) as s:
        ev = evidence(s)[demo7]
    assert len(ev["wins"]) == 1 and ev["entries"] == [] and ev["points"] == 2
    form(c, f"/journal/{eid}/delete", tok)
    with session(dd) as s:
        assert [l.win_id for l in s.scalars(select(GuideLink))] == [wid]


def test_reimport_keeps_links_and_retires_removed_items(nb, tmp_path):
    dd, c, tok, guide = nb
    with session(dd) as s:
        mentor = s.scalar(select(GuideItem).where(GuideItem.name.startswith("Mentors newer"))).id
        s.add(Win(day=date.today().isoformat(), title="Mentored Sam", size="medium", created_at=datetime.now()))
        s.commit()
        wid = s.scalar(select(Win.id))
    form(c, "/guide/link", tok, win=wid, item=[mentor])
    write_guide(guide, g6=G6[:2] + ["A brand new expectation about pipelines."])
    r = CliRunner().invoke(cli, ["guide", "import", str(guide), "--data-dir", str(dd.root)])
    assert r.exit_code == 0 and "1 new" in r.output and "1 no longer in the guide" in r.output
    with session(dd) as s:
        g = s.get(GuideItem, mentor)
        assert g.active is False and s.scalar(select(GuideLink.item_id)) == mentor
    assert "Mentors newer" not in c.get("/promo").text


def test_guide_links_are_in_the_csv_export_and_bad_input_is_ignored(nb):
    dd, c, tok, _ = nb
    form(c, "/journal/add", tok, kind="note", text="Mentored a new hire on Git")
    with session(dd) as s:
        eid = s.scalar(select(JournalEntry.id))
        summary = s.scalar(select(GuideItem.id).where(GuideItem.kind == "summary"))
        mentor = s.scalar(select(GuideItem.id).where(GuideItem.name.startswith("Mentors newer")))
    form(c, "/guide/link", tok, entry=eid, item=[mentor, summary, 99999], next="//evil.example")
    with session(dd) as s:
        assert [l.item_id for l in s.scalars(select(GuideLink))] == [mentor]
    z = zipfile.ZipFile(io.BytesIO(c.get("/export/everything").content))
    rows = list(csv.DictReader(io.StringIO(z.read("guide_links.csv").decode("utf-8-sig"))))
    assert rows[0]["linked_to"] == "entry" and rows[0]["linked_text"] == "Mentored a new hire on Git"
    assert rows[0]["grade"] == "6"


def test_promo_page_without_a_guide_explains_how_to_load_it(tmp_path):
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    c = TestClient(create_app(dd), base_url=BASE)
    assert "careeros guide import" in c.get("/promo").text
    assert "Link to the leveling guide" not in c.get("/").text
