import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from typer.testing import CliRunner

from careeros.claude_cli import ClaudeError
from careeros.cli import app as cli
from careeros.config import DataDir
from careeros.slack import classify as cls
from careeros.slack.importer import import_items, impact_of, load_canvas_id, save_canvas_id
from careeros.slack.parse import CanvasFormatError, parse_canvas
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import JournalAttachment, JournalEntry
from careeros.web.app import create_app

BASE = "http://127.0.0.1"
LINK = "https://example.slack.com/archives/C111/p1700000000000100?thread_ts=1700000000.000100"

TRACKER = f"""# Slack Work Activity Tracker

## ![](slack_date:2026-10-26)

### Daily Summary
* Meaningful Work Items: 2

**Primary Work**
* **Deployment — Ship the hotfix**
   * Action: Deployed the hotfix to production.
   * Outcome: Customers unblocked.
   * Impact / Why It Mattered: Stopped the error spike before the weekend.
   * Workflow: Unknown
   * Link: {LINK}
* **Documentation — Update the runbook**
   * Action: Rewrote the rollback steps.

**Decisions**
* **Decision — Not a work item**
   * Action: Should be ignored.

## ![](slack_date:2026-10-27)

**Primary Work**
* **Coordination — Plan the refresh**
   * Action: Lined up teams for Friday.
"""

PROMO = """# Weekly Contributions for Promotion Case
Canvas Created: November 3, 2025

## Weekly Contributions (Week of November 3)

### Led the release review
**Channel:** <#C222> - November 5, 2025
**Summary:** Ran the review and caught a bad merge.
**Impact:** Kept the release on schedule.
**Full Comment:**

> Found the bad merge, reverting now.

**Link:** https://example.slack.com/archives/C222/p1700000000000200
"""


def personal(tmp_path):
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    engine = make_engine(dd.db)
    init_db(engine)
    return dd, make_session_factory(engine)


def test_parse_tracker_keeps_work_items_only():
    items = parse_canvas(TRACKER)
    assert [i.text for i in items] == ["Deployment: Ship the hotfix", "Documentation: Update the runbook",
                                       "Coordination: Plan the refresh"]
    first = items[0]
    assert first.day == "2026-10-26" and items[2].day == "2026-10-27"
    assert first.key == "slack:C111/p1700000000000100" and first.link == LINK
    assert "Why it mattered: Stopped the error spike" in first.body and "Unknown" not in first.body
    assert impact_of(first.body) == "Stopped the error spike before the weekend."
    assert items[1].key.startswith("slack:") and not items[1].link


def test_parse_promo_canvas():
    [it] = parse_canvas(PROMO)
    assert it.day == "2025-11-05" and it.text == "Led the release review"
    assert it.key == "slack:C222/p1700000000000200"
    assert "Why it mattered: Kept the release on schedule." in it.body and "reverting now" in it.body


def test_parse_accepts_connector_json_and_rejects_other_canvases():
    assert len(parse_canvas(json.dumps({"markdown_content": TRACKER}))) == 3
    with pytest.raises(CanvasFormatError):
        parse_canvas("# Lunch menu\n\n* Tacos")


def test_import_tags_source_and_skips_repeats(tmp_path):
    dd, Session = personal(tmp_path)
    items = parse_canvas(TRACKER)
    kinds = {items[0].key: "task", items[1].key: "document", items[2].key: "bogus"}
    with Session() as s:
        r = import_items(s, items, lambda todo: {i.key: kinds[i.key] for i in todo})
        assert r["added"] == 3 and r["task"] == 1 and r["document"] == 1 and r["note"] == 1
        rows = s.scalars(select(JournalEntry).order_by(JournalEntry.id)).all()
        assert {e.source for e in rows} == {"slack"} and rows[0].status == "done" and rows[2].kind == "note"
        atts = s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == rows[0].id)).all()
        assert {a.kind for a in atts} == {"notes", "link"}

        def boom(todo):
            assert not todo
            return {}
        assert import_items(s, items, boom) == dict(added=0, skipped=3, meeting=0, conversation=0, document=0,
                                                   task=0, note=0)


def test_classify_falls_back_to_other(monkeypatch):
    items = parse_canvas(TRACKER)
    seen = []

    def fake_ask(prompt, data):
        seen.append(json.loads(data))
        return 'Sure: {"i0": "task", "i1": "poem"}'
    monkeypatch.setattr(cls, "ask", fake_ask)
    got = cls.classify(items)
    assert got == {items[0].key: "task", items[1].key: "note", items[2].key: "note"}
    assert "Deployment: Ship the hotfix" in seen[0][0]["text"]


def test_classify_aborts_when_claude_is_unreachable(monkeypatch):
    def down(prompt, data):
        raise ClaudeError("no claude")
    monkeypatch.setattr(cls, "ask", down)
    with pytest.raises(ClaudeError):
        cls.classify(parse_canvas(TRACKER))


def test_canvas_id_from_link(tmp_path):
    dd, _ = personal(tmp_path)
    assert save_canvas_id(dd, "https://x.slack.com/docs/T1/F0C2ZF10L02") == "F0C2ZF10L02"
    assert load_canvas_id(dd) == "F0C2ZF10L02"
    with pytest.raises(ValueError):
        save_canvas_id(dd, "not a canvas")


def test_cli_import(tmp_path, monkeypatch):
    dd, Session = personal(tmp_path)
    f = tmp_path / "c.md"
    f.write_text(TRACKER)
    monkeypatch.setattr(cls, "ask", lambda p, d: '{"i0": "task"}')
    r = CliRunner().invoke(cli, ["slack", "import", str(f), "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert "3 added" in r.output and "1 tasks" in r.output and "2 other" in r.output
    r = CliRunner().invoke(cli, ["slack", "import", str(f), "--data-dir", str(dd.root)])
    assert "0 added" in r.output and "3 already here" in r.output


def test_web_sync_and_cards(tmp_path, monkeypatch):
    from careeros.slack import connector
    dd, Session = personal(tmp_path)
    app = create_app(dd)
    c, token = TestClient(app, base_url=BASE), app.state.csrf_token
    assert "Not connected yet" in c.get("/").text
    job = run_sync(c, token, "slack")
    assert job["state"] == "error" and "No Slack canvas connected" in job["steps"][0]["detail"]

    save_canvas_id(dd, "F0C2ZF10L02")
    monkeypatch.setattr(connector, "call_tool", lambda prompt, tool: json.dumps({"markdown_content": TRACKER}))
    monkeypatch.setattr(cls, "ask", lambda p, d: '{"i0": "task", "i1": "document", "i2": "conversation"}')
    job = run_sync(c, token, "slack")
    assert job["message"] == "Slack synced: 3 new items." and job["pct"] == 100
    assert [st["state"] for st in job["steps"]] == ["done", "done", "skipped"]  # no leveling guide loaded
    tasks = c.get("/tasks").text
    assert "from Slack" in tasks and "suggested win" in tasks and "Stopped the error spike before the weekend." in tasks
    assert "Written by Slack" in tasks
    assert run_sync(c, token, "slack")["message"] == "Slack synced: 0 new items."

    monkeypatch.setattr(connector, "call_tool", lambda prompt, tool: 'MCP tool call failed: status 401 {"error": "invalid_token"}')
    job = run_sync(c, token, "slack")
    assert job["state"] == "error" and "sign-in has expired" in job["steps"][0]["detail"]


def run_sync(c, token, name):
    import time
    path = {"slack": "/slack/sync", "google": "/sync/google"}[name]
    assert c.post(path, data={"csrf": token}, headers={"X-Sync": "1"}).json()["started"]
    for _ in range(200):
        job = c.get("/sync/status").json().get(name)
        if job and job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("sync never finished")


def test_saved_big_answers_are_read_back(tmp_path, monkeypatch):
    from careeros import claude_cli
    monkeypatch.setattr(claude_cli, "SAVED_DIRS", (tmp_path.resolve(),))
    f = tmp_path / "slack-x.json"
    f.write_text(json.dumps({"content": [{"type": "text", "text": json.dumps({"markdown_content": TRACKER})}]}))
    got = claude_cli._result_text(f"Result text too large for inline response (276037 bytes). Full results saved to: {f}")
    assert len(parse_canvas(got)) == 3
    with pytest.raises(ClaudeError):
        claude_cli._result_text("Result text too large. Full results saved to: /etc/passwd.txt")
    with pytest.raises(ClaudeError):
        claude_cli._result_text("Result text too large for inline response (276037 bytes).")


def test_a_long_answer_that_mentions_saved_to_is_kept_as_is():
    from careeros import claude_cli
    text = "# Tracker\n" + "x" * 5000 + "\nExport saved to: notes.txt\n"
    assert claude_cli._result_text(text) == text


def test_import_skips_items_another_sync_saved_while_claude_sorted(tmp_path):
    dd, Session = personal(tmp_path)
    items = parse_canvas(TRACKER)
    with Session() as s, Session() as other:
        def classify_while_other_sync_saves(todo):
            import_items(other, items[:1], lambda t: {})  # the scheduled sync finishes first
            return {}
        r = import_items(s, items, classify_while_other_sync_saves)
        assert r["added"] == 2 and r["skipped"] == 1
        assert s.scalar(select(func.count()).select_from(JournalEntry)) == 3
