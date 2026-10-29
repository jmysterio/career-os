"""Claude writes the promotion case from numbered evidence; the app checks every sentence (fake Claude)."""
import json
import time
from datetime import date, datetime

import pytest
from sqlalchemy import select

from careeros.claude_cli import ClaudeError
from careeros.guide.service import experiences
from careeros.promo import evidence as pe, write as pw
from careeros.storage.models import GuideLink, JournalEntry, PromoSection, PromoVersion, Win

from test_guide import nb, session  # noqa: F401


def seed(s):
    item = experiences(s)[0].id
    e = JournalEntry(day="2026-10-20", kind="task", text="Ran the full sandbox refresh", created_at=datetime.now(),
                     source="slack", activity="sandbox_refresh")
    old = JournalEntry(day="2024-01-05", kind="task", text="Ancient deploy", created_at=datetime.now(), source="slack")
    s.add_all([e, old])
    s.flush()
    w = Win(day="2026-10-20", title="Planned and ran a full sandbox refresh for four teams", impact="No team lost data.",
            size="large", entry_id=e.id, created_at=datetime.now())
    s.add(w)
    s.flush()
    s.add_all([GuideLink(item_id=item, win_id=w.id, created_at=datetime.now()),
               GuideLink(item_id=item, entry_id=old.id, created_at=datetime.now())])
    s.commit()
    return w


def by_key(answers):
    def reader(name, key, evidence):
        assert all(set(p) == {"n", "kind", "text", "day", "refs"} for p in evidence)
        return answers(key, evidence)
    return reader


def test_evidence_stays_inside_the_window(nb):
    dd, *_ = nb
    with session(dd) as s:
        seed(s)
        pieces, slices = pe.build(s, "2025-10-29", "2026-10-29")
        texts = " ".join(p["text"] for p in pieces)
        assert "Planned and ran a full sandbox refresh" in texts and "Ancient deploy" not in texts
        assert any(p["kind"] == "count" and "1 sandbox refreshes" in p["text"] for p in pieces)
        assert any(p["kind"] == "progress" for p in pieces) and any(p["kind"] == "gap" for p in pieces)
        win = next(p for p in pieces if p["kind"] == "win")
        assert win["n"] in slices["accomplishments"] and win["n"] in slices["summary"]
        assert all(pieces[n - 1]["kind"] in ("gap", "next", "progress") for n in slices["growth"])


def test_bad_citations_and_invented_numbers_are_flagged():
    ev = [dict(n=1, kind="win", text="Win (large, 2026-10-20): Ran 4 refreshes.", day="", refs=[]),
          dict(n=2, kind="count", text="Count: 27 deployments.", day="", refs=[])]
    got = pw.check([dict(text="Jordan ran 4 refreshes.", sources=[1]),
                    dict(text="Jordan led 31 deployments.", sources=[2]),
                    dict(text="Jordan is great.", sources=[9]),
                    dict(text="Jordan  shipped   27 deployments.", sources=[2, "x"])], ev)
    assert [(x["valid"], x["reason"]) for x in got] == [
        (True, ""), (False, "31 isn't in the evidence"), (False, "no source in the evidence"), (True, "")]
    assert got[3]["text"] == "Jordan shipped 27 deployments." and got[3]["sources"] == [2]


def test_write_case_saves_a_version_with_its_evidence(nb):
    dd, *_ = nb
    with session(dd) as s:
        seed(s)

        def answers(key, ev):
            if key == "growth":
                raise ClaudeError("timed out")
            return [dict(text=f"Jordan's {key}, sourced.", sources=[ev[0]["n"]]),
                    dict(text="Jordan saved $5000.", sources=[ev[0]["n"]])]
        v = pw.write_case(s, start="2025-10-29", end="2026-10-29", name="Jordan", reader=by_key(answers))
        secs = {x.key: x for x in s.scalars(select(PromoSection).where(PromoSection.version_id == v.id))}
        assert list(secs) == ["summary", "accomplishments", "impact", "behaviors", "growth"]
        assert secs["growth"].sentences == [] and "timed out" in secs["growth"].error
        assert [x["valid"] for x in secs["summary"].sentences] == [True, False]
        assert v.evidence and v.name == "Jordan"
        with pytest.raises(ClaudeError):  # nothing to write from: nothing saved
            pw.write_case(s, start="2020-01-01", end="2020-12-31", name="Jordan", reader=by_key(answers))
        assert s.query(PromoVersion).count() == 1


def test_write_button_shows_the_draft_with_sources(nb, monkeypatch):
    dd, c, token, _ = nb
    with session(dd) as s:
        seed(s)
    monkeypatch.setattr(pw, "ask", lambda prompt, data, timeout=0: json.dumps({"sentences": [
        {"text": "Jordan ran the full sandbox refresh <b>for four teams</b>.", "sources": [json.loads(data)["evidence"][0]["n"]]},
        {"text": "Jordan cut costs by 40%.", "sources": [1]}]}))
    assert "Write my promo case" in c.get("/promo/case").text and "No draft yet" in c.get("/promo/case").text
    r = c.post("/promo/write", data={"csrf": token, "name": "Jordan", "start": "2025-10-29", "end": "2026-10-29"},
               headers={"X-Sync": "1"})
    assert r.json() == {"started": True}
    for _ in range(200):
        job = c.get("/sync/status").json().get("promo")
        if job and job["state"] != "running":
            break
        time.sleep(0.05)
    assert job["state"] == "done" and all(st["state"] in ("done", "skipped") for st in job["steps"]), job
    assert "No evidence for this section" in next(st["detail"] for st in job["steps"] if st["state"] == "skipped")
    page = c.get("/promo/case").text
    assert "Promotion case: Jordan" in page and "&lt;b&gt;for four teams" in page and "<b>for four teams" not in page
    assert 'href="#src-' in page and 'id="src-' in page and "Check this (40 isn" in page
    assert "sentences to check" in page
    assert c.get("/promo/case/999").status_code == 404
    assert c.post("/promo/write", data={"csrf": "nope"}).status_code == 403
    assert pw.load_name(dd) == "Jordan"
