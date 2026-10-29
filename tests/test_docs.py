from datetime import date, datetime

import pytest
from sqlalchemy import select

from careeros.claude_cli import ClaudeError
from careeros.google import docs as gdocs
from careeros.storage.models import JournalAttachment, JournalEntry
from careeros.storage.removal import add_skip_rule, remove_entry

ME = "jtetzel@salesforce.com"


def row(gid, name, kind="document", modified="2026-10-20T15:00:00.000Z", editor=f"Jordan Tetzel <{ME}>"):
    slug = {"document": "document", "spreadsheet": "spreadsheets", "presentation": "presentation"}[kind]
    return (f'- Name: "{name}" (ID: {gid}, Type: application/vnd.google-apps.{kind}, Size: 1024, '
            f"Created: 2026-09-01T12:00:00.000Z, Modified: {modified}, Last Edited By: {editor}) "
            f"Link: https://docs.google.com/{slug}/d/{gid}/edit?usp=drivesdk")


def answer(*rows, more=False):
    return (f"Found {len(rows)} files for {ME} matching 'query':\n" + "\n".join(rows)
            + ("\nnextPageToken: ~!!~abc" if more else ""))


OWNED = answer(row("own1", "Release Manager Runbook"), row("own2", "Pine release plan", "spreadsheet"),
               row("own3", "Hotfix deck", "presentation", "2026-10-13T15:00:00.000Z"))
OTHERS = answer(row("oth1", "Sandbox Refresh SOP"),
                row("oth2", "Team stand-up doc", editor="Pat Lee <plee@salesforce.com>"))


def by_text(s):
    return {e.text: e for e in s.scalars(select(JournalEntry).where(JournalEntry.source == "docs"))}


def test_parse_keeps_owned_and_others_you_last_edited():
    assert [d.name for d in gdocs.parse(OWNED, True)] == ["Release Manager Runbook", "Pine release plan", "Hotfix deck"]
    others = gdocs.parse(OTHERS, False)
    assert [(d.name, d.kind, d.owned) for d in others] == [("Sandbox Refresh SOP", "doc", False)]
    assert others[0].modified == date(2026, 10, 20) and others[0].link.endswith("/oth1/edit?usp=drivesdk")


def test_merge_adds_once_per_file_per_week_and_says_wrote_edited_updated(session):
    found = gdocs.parse(OWNED, True) + gdocs.parse(OTHERS, False)
    assert gdocs.merge(session, found) == dict(added=4, skipped=0)
    assert gdocs.merge(session, found)["added"] == 0
    later = gdocs.parse(answer(row("own1", "Release Manager Runbook", modified="2026-10-28T15:00:00.000Z")), True)
    assert gdocs.merge(session, later)["added"] == 1
    rows = by_text(session)
    assert set(rows) == {"Wrote doc: Release Manager Runbook", "Wrote sheet: Pine release plan", "Wrote slides: Hotfix deck",
                         "Edited doc: Sandbox Refresh SOP", "Updated doc: Release Manager Runbook"}
    assert rows["Wrote slides: Hotfix deck"].day == "2026-10-13"
    assert all(e.kind == "document" for e in rows.values())
    link = session.scalar(select(JournalAttachment).where(JournalAttachment.entry_id == rows["Edited doc: Sandbox Refresh SOP"].id))
    assert link.kind == "link" and "/oth1/" in link.body


def test_meeting_notes_skip_rules_and_removed_files_stay_out(session):
    meeting = JournalEntry(day="2026-10-20", kind="meeting", text="Release sync", source="calendar",
                           created_at=datetime.now(), external_id="cal:1")
    session.add(meeting)
    session.flush()
    session.add(JournalAttachment(entry_id=meeting.id, kind="link", title="Notes",
                                  body="https://docs.google.com/document/d/own1/edit", created_at=datetime.now()))
    session.commit()
    add_skip_rule(session, "pine", "docs")
    assert gdocs.merge(session, gdocs.parse(OWNED, True)) == dict(added=1, skipped=1)  # only the deck
    remove_entry(session, by_text(session)["Wrote slides: Hotfix deck"].id)
    again = gdocs.parse(answer(row("own3", "Hotfix deck", "presentation", "2026-10-28T15:00:00.000Z")), True)
    assert gdocs.merge(session, again)["added"] == 0  # a removed file doesn't come back as "Updated"


def test_fetch_searches_a_month_at_a_time_and_counts_incomplete(monkeypatch):
    seen = {}

    def fake(prompt, tools, timeout, max_turns):
        qs = [line.split(". ", 1)[1] for line in prompt.splitlines() if line[:1].isdigit()]
        seen["n"] = len(qs)
        out = [("t", {"query": q}, OWNED if "'me' in owners" in q and not q.startswith("not") else OTHERS) for q in qs]
        out[0] = (out[0][0], out[0][1], answer(row("x", "Big month"), more=True))
        return out[:-1]  # the last search never came back
    monkeypatch.setattr("careeros.claude_cli.call_tools", fake)
    found, short = gdocs.fetch(date(2025, 10, 29), date(2026, 10, 29))
    assert seen["n"] == 24 and short == 2
    assert "own1" in {d.gid for d in found} and "oth2" not in {d.gid for d in found}


def test_signed_out_google_stops_the_step(monkeypatch):
    monkeypatch.setattr("careeros.claude_cli.call_tools", lambda *a, **k: [
        ("t", {"query": gdocs._query(True, date(2026, 10, 27), date(2026, 10, 29))}, "Error: invalid_token")])
    with pytest.raises(ClaudeError, match="sign-in has expired"):
        gdocs.fetch(date(2026, 10, 27), date(2026, 10, 29))


def test_summaries_saved_and_a_failure_keeps_the_record_for_next_time(session, monkeypatch):
    gdocs.merge(session, gdocs.parse(OWNED, True))
    asked = []

    def fake(gid, kind, name):
        asked.append((gid, kind, name))
        if gid == "own2":
            raise ClaudeError("nope")
        return f"A {kind} about {name}.\nIt covers things."
    monkeypatch.setattr(gdocs, "summarize", fake)
    assert gdocs.summarize_pending(session) == dict(summarized=2, failed=1)
    assert ("own1", "doc", "Release Manager Runbook") in asked
    assert [p[1] for p in gdocs.pending(session)] == ["own2"]
    rows = by_text(session)
    note = session.scalar(select(JournalAttachment).where(JournalAttachment.entry_id == rows["Wrote doc: Release Manager Runbook"].id,
                                                          JournalAttachment.title == gdocs.AI_TITLE))
    assert note.body.startswith("A doc about Release Manager Runbook")


def test_summary_reads_the_file_then_summarizes_it_without_tools(monkeypatch):
    calls = []
    monkeypatch.setattr("careeros.claude_cli.call_tool", lambda prompt, tool, timeout=0: calls.append(tool) or "body text")
    monkeypatch.setattr("careeros.claude_cli.ask", lambda prompt, data, timeout=0: calls.append(data) or
                        " A runbook.\n\nIt covers releases.\nSkipped: the tabs.\nA third line.")
    assert gdocs.summarize("own1", "doc", "Runbook") == "A runbook.\nIt covers releases."
    assert calls == [gdocs.READ_TOOL, "body text"]
