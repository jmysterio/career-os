"""Sending a promo case draft to Google Docs (fake connector)."""
import time

import pytest
from sqlalchemy import select

from careeros.claude_cli import ClaudeError
from careeros.google import docs_export
from careeros.storage.models import PromoSection, PromoVersion

from test_guide import nb, session  # noqa: F401
from test_promo_editing import draft


def doc_reply(doc_id="abc123"):
    return (f"Successfully imported 'x' as Google Doc\n   Link: https://docs.google.com/document/d/{doc_id}/edit?usp=drivesdk")


def test_markdown_sourced_and_clean(nb):
    dd, *_ = nb
    with session(dd) as s:
        v = draft(s)
        secs = list(s.scalars(select(PromoSection).where(PromoSection.version_id == v.id).order_by(PromoSection.position)))
        secs[0].sentences = [dict(text="Jordan led it.", sources=[1], valid=True, reason=""),
                             dict(text="Jordan saved 9 hours.", sources=[1], valid=False, reason="9 isn't in the evidence")]
        sourced, clean = docs_export.markdown(v, secs, True), docs_export.markdown(v, secs, False)
        assert sourced.startswith("# Promotion case: Jordan") and "## Summary" in sourced and "## Growth areas" in sourced
        assert "Jordan led it. [1]" in sourced and "**[Check this: 9 isn't in the evidence]**" in sourced
        assert "## Sources" in sourced and "\n1. " in sourced
        assert "[1]" not in clean and "Check this" not in clean and "## Sources" not in clean
        assert "Jordan led it. Jordan saved 9 hours." in clean


def test_send_checks_the_doc_that_comes_back(nb, monkeypatch):
    dd, *_ = nb
    with session(dd) as s:
        v = draft(s)
        secs = list(s.scalars(select(PromoSection).where(PromoSection.version_id == v.id)))
        calls = []

        def fake(prompt, tool, timeout=240, stdin=None):
            calls.append((tool, stdin))
            if tool == docs_export.TOOL:
                return doc_reply()
            return calls[0][1]  # Google gives back exactly what was sent
        monkeypatch.setattr(docs_export, "call_tool", fake)
        link, same = docs_export.send(dd, v, secs, True)
        assert link.startswith("https://docs.google.com/document/d/abc123") and same
        assert calls[0][1].startswith("# Promotion case") and "document_id=abc123" not in (calls[1][1] or "")
        assert (dd.root / "exports" / f"promo-case-{v.id}-sourced.md").exists()
        monkeypatch.setattr(docs_export, "call_tool", lambda p, t, timeout=240, stdin=None:
                            doc_reply() if t == docs_export.TOOL else "# Something else entirely")
        assert docs_export.send(dd, v, secs, False)[1] is False
        monkeypatch.setattr(docs_export, "call_tool", lambda p, t, timeout=240, stdin=None: "Done, but no link here.")
        with pytest.raises(ClaudeError, match="didn't send back a link"):
            docs_export.send(dd, v, secs, True)


def test_button_saves_both_links(nb, monkeypatch):
    dd, c, token, _ = nb
    with session(dd) as s:
        vid = draft(s).id
    sent = {}

    def fake(prompt, tool, timeout=240, stdin=None):
        if tool == docs_export.TOOL:
            sent[len(sent)] = stdin
            return doc_reply(f"doc{len(sent)}")
        return sent[len(sent) - 1]
    monkeypatch.setattr(docs_export, "call_tool", fake)
    assert "Send to Google Docs" in c.get(f"/promo/case/{vid}").text
    assert c.post(f"/promo/case/{vid}/gdoc", data={"csrf": token}, headers={"X-Sync": "1"}).json() == {"started": True}
    for _ in range(200):
        job = c.get("/sync/status").json().get("promo")
        if job and job["state"] != "running":
            break
        time.sleep(0.05)
    assert job["state"] == "done" and all("every word checked" in st["detail"] for st in job["steps"]), job
    with session(dd) as s:
        v = s.get(PromoVersion, vid)
        assert v.google_doc_url.endswith("doc1/edit?usp=drivesdk") and "doc2" in v.google_doc_clean_url
    page = c.get(f"/promo/case/{vid}").text
    assert ">with sources</a>" in page and ">clean copy</a>" in page
