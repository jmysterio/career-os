"""The two Sync buttons: what each runs, step by step, reporting into a Job."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..claude_cli import ClaudeError
from ..config import DataDir
from .jobs import Job

GOOGLE_STEPS = ["Read Google Calendar (yesterday and today)", "Read Google Tasks", "Summarize meeting notes",
                "Link new records to the leveling guide"]
SLACK_STEPS = ["Read your Slack tracker canvas", "Sort the new items", "Link new records to the leveling guide"]
TASKS_LOOKBACK = timedelta(days=14)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _tasks_since(s) -> datetime:
    from ..storage.sync_log import status
    last = status(s)["tasks"]["at"]
    return (last - timedelta(days=1)) if last else datetime.now() - TASKS_LOOKBACK


def _link_new(job: Job, i: int, s) -> int:
    from ..guide.ai_review import pending, review
    from ..guide.service import has_guide
    if not has_guide(s):
        job.skip(i, "The leveling guide isn't loaded.")
        return 0
    if not pending(s):
        job.done(i, "Nothing new to link.")
        return 0
    job.start(i)
    try:
        r = review(s, progress=job.sub)
    except ClaudeError as exc:
        job.fail(i, str(exc))
        return 0
    job.done(i, f"{_plural(r['links'], 'guide link')}, {_plural(r['wins'], 'drafted win')}"
             + (f"; {r['failed']} couldn't be read" if r["failed"] else ""))
    return r["read"]


def run_google(job: Job, Session_, lock) -> None:
    from ..google import calendar as gcal, connector, summaries, tasks as gtasks
    last = date.today()
    first = last - timedelta(days=1)
    new = []
    with Session_() as s:
        job.start(0)
        try:
            items = connector.fetch(first, last)
            with lock:
                r = gcal.import_events(s, items, first, last)
            job.done(0, f"{_plural(r['added'], 'new meeting')}, {r['updated']} changed, {r['removed']} gone")
            new.append(_plural(r["added"], "meeting"))
        except (gcal.CalendarError, ClaudeError) as exc:
            job.fail(0, f"{exc} Is Google Workspace signed in for Claude Code?")
        job.start(1)
        try:
            tasks, failed = gtasks.fetch(_tasks_since(s))
            with lock:
                r = gtasks.merge(s, tasks)
            detail = f"{_plural(r['added'], 'new task')}, {r['updated']} marked done"
            if failed:
                job.fail(1, detail + f"; {_plural(failed, 'task list')} couldn't be read. Press Sync Google again.")
            else:
                job.done(1, detail)
            new.append(_plural(r["added"], "task"))
        except ClaudeError as exc:
            job.fail(1, str(exc))
        job.start(2)
        try:
            n = summaries.summarize_pending(s, first, last, progress=job.sub)
            if n["failed"]:
                job.fail(2, f"{n['summarized']} written, {n['failed']} couldn't be read. Press Sync Google again.")
            else:
                job.done(2, f"{n['summarized']} written" if n["summarized"] else "No new meeting notes.")
        except gcal.CalendarError as exc:
            job.fail(2, str(exc))
        _link_new(job, 3, s)
    job.finish(("Google synced: " + " and ".join(new) + " new.") if new else "Google sync couldn't read anything.")


def run_slack(job: Job, Session_, lock, dd: DataDir) -> None:
    from ..slack.classify import classify
    from ..slack.connector import fetch_canvas
    from ..slack.importer import import_items, load_canvas_id, new_items
    from ..slack.parse import CanvasFormatError, parse_canvas
    with Session_() as s:
        cid = load_canvas_id(dd)
        if not cid:
            job.fail(0, "No Slack canvas connected yet. In Terminal run: uv run careeros slack connect <canvas link>")
            job.skip(1)
            job.skip(2)
            job.finish("Slack sync couldn't start.")
            return
        job.start(0)
        try:
            items = parse_canvas(fetch_canvas(cid))
        except (ClaudeError, CanvasFormatError) as exc:
            job.fail(0, str(exc))
            job.skip(1)
            job.skip(2)
            job.finish("Slack sync couldn't read the tracker, so nothing changed.")
            return
        todo = new_items(s, items)
        job.done(0, f"{_plural(len(items), 'item')} on the canvas, {len(todo)} new")
        job.start(1)
        try:  # not under the write lock: Claude's sorting takes a while and the page stays usable meanwhile
            r = import_items(s, items, lambda t: classify(t, progress=job.sub))
        except ClaudeError as exc:
            job.fail(1, str(exc))
            job.skip(2)
            job.finish("Slack sync read the tracker but couldn't sort the new items, so nothing was saved.")
            return
        job.done(1, f"{r['meeting']} meetings, {r['conversation']} conversations, {r['document']} documents, "
                    f"{r['task']} tasks, {r['note']} other" if r["added"] else "Nothing new since the last pull.")
        _link_new(job, 2, s)
    job.finish(f"Slack synced: {_plural(r['added'], 'new item')}.")
