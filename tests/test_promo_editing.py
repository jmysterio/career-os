"""Editing, rewriting, and comparing drafts of the promotion case (fake Claude)."""
import time

from sqlalchemy import select

from careeros.promo import write as pw
from careeros.storage.models import PromoSection, PromoVersion

from test_guide import form, nb, session  # noqa: F401
from test_promo_writer import by_key, seed


def draft(s):
    seed(s)
    return pw.write_case(s, start="2025-10-29", end="2026-10-29", name="Jordan", reader=by_key(
        lambda key, ev: [dict(text=f"Jordan's {key} one.", sources=[ev[0]["n"]]),
                         dict(text=f"Jordan's {key} two.", sources=[ev[-1]["n"]])]))


def sections(s, v):
    return {x.key: x for x in s.scalars(select(PromoSection).where(PromoSection.version_id == v.id))}


def test_text_round_trip():
    sentences = [dict(text="Jordan led the refresh.", sources=[3, 7]), dict(text="No sources here.", sources=[])]
    text = pw.to_text(sentences)
    assert text == "Jordan led the refresh. [3] [7]\nNo sources here."
    assert pw.from_text(text + "\n\n   ") == sentences


def test_edit_saves_a_checked_new_draft_and_keeps_the_old(nb):
    dd, *_ = nb
    with session(dd) as s:
        v = draft(s)
        n = sections(s, v)["impact"].sentences[0]["sources"][0]
        new = pw.edit_section(s, v, "impact", f"Jordan ran the refresh for four teams. [{n}]\nJordan saved 99 hours. [{n}]")
        imp = sections(s, new)["impact"]
        assert imp.edited and [x["valid"] for x in imp.sentences] == [True, False]
        assert "99 isn't in the evidence" in imp.sentences[1]["reason"]
        assert sections(s, v)["impact"].sentences[0]["text"] == "Jordan's impact one."  # the old draft is untouched
        assert new.evidence == v.evidence and new.slices == v.slices and new.note == "Edited Impact"
        assert sections(s, new)["summary"].sentences == sections(s, v)["summary"].sentences


def test_rewrite_one_section_from_its_own_evidence(nb):
    dd, *_ = nb
    with session(dd) as s:
        v = draft(s)
        seen = []

        def reader(name, key, ev):
            seen.append((key, [p["n"] for p in ev]))
            return [dict(text="Jordan, rewritten.", sources=[ev[0]["n"]])]
        new = pw.rewrite_section(s, v, "growth", reader=reader)
        assert seen == [("growth", v.slices["growth"])]
        assert sections(s, new)["growth"].sentences[0]["text"] == "Jordan, rewritten."
        assert new.note == "Rewrote Growth areas" and not sections(s, new)["growth"].edited
        diff = pw.compare(sections(s, v)["growth"].sentences, sections(s, new)["growth"].sentences)
        assert [d["op"] for d in diff] == ["removed", "removed", "added"]


def test_pages_edit_rewrite_confirm_and_compare(nb, monkeypatch):
    dd, c, token, _ = nb
    with session(dd) as s:
        vid = draft(s).id
    page = c.get("/promo/case").text
    assert 'data-label="Rewrite"' in page and "Save as a new draft" in page and "[" in page
    r = form(c, f"/promo/case/{vid}/edit/summary", token, text="Jordan is ready for Grade 6.")
    assert r.status_code == 303 and r.headers["location"].endswith("#sec-summary")
    with session(dd) as s:
        edited_id = s.scalar(select(PromoVersion.id).order_by(PromoVersion.id.desc()))
    new_page = c.get(f"/promo/case/{edited_id}").text
    assert "edited by you" in new_page and "Replace my edits" in new_page
    assert "The newest is draft" in c.get(f"/promo/case/{vid}").text
    # an edited section needs a confirm before Claude rewrites it
    r = c.post(f"/promo/case/{edited_id}/rewrite/summary", data={"csrf": token}, headers={"X-Sync": "1"})
    assert r.status_code == 409 and "Replace my edits" in r.json()["message"]
    monkeypatch.setattr(pw, "ask", lambda prompt, data, timeout=0: '{"sentences": [{"text": "Fresh summary.", "sources": []}]}')
    r = c.post(f"/promo/case/{edited_id}/rewrite/summary", data={"csrf": token, "confirm": "yes"}, headers={"X-Sync": "1"})
    assert r.json() == {"started": True}
    for _ in range(200):
        job = c.get("/sync/status").json().get("promo")
        if job and job["state"] != "running":
            break
        time.sleep(0.05)
    assert job["state"] == "done", job
    cmp = c.get(f"/promo/compare?a={vid}&b={edited_id}").text
    assert "Jordan is ready for Grade 6." in cmp and "diff-added" in cmp and "diff-removed" in cmp
    assert c.get("/promo/compare?a=1&b=999", follow_redirects=False).status_code == 303
    assert form(c, f"/promo/case/{vid}/edit/nope", token, text="x").status_code == 303
