"""The two Sync buttons: what each runs, step by step, reporting into a Job."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..claude_cli import ClaudeError
from ..config import DataDir
from .jobs import Job

GOOGLE_STEPS = ["Read Google Calendar (yesterday and today)", "Read Google Tasks", "Summarize meeting notes",
                "Read Google Docs you wrote or edited", "Link new records to the leveling guide"]
SLACK_STEPS = ["Read your Slack tracker canvas", "Sort the new items", "Look for kudos in public channels",
               "Link new records to the leveling guide"]
TASKS_LOOKBACK = timedelta(days=14)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _tasks_since(s) -> datetime:
    from ..storage.sync_log import status
    last = status(s)["tasks"]["at"]
    return (last - timedelta(days=1)) if last else datetime.now() - TASKS_LOOKBACK


def _link_new(job: Job, i: int, s) -> int:
    from ..guide import activities, work
    from ..guide.ai_review import pending, review
    from ..guide.service import has_guide
    if not has_guide(s):
        job.skip(i, "The leveling guide isn't loaded.")
        return 0
    if not pending(s) and not work.pending(s) and not activities.pending(s):
        job.done(i, "Nothing new to link.")
        return 0
    job.start(i)
    r = dict(read=0, links=0, wins=0, failed=0)
    try:
        if pending(s):
            r = review(s, progress=job.sub)
        g = work.group(s) if work.pending(s) else dict(new=0, joined=0)
        a = activities.tag(s) if activities.pending(s) else dict(tagged=0)
    except ClaudeError as exc:
        job.fail(i, str(exc))
        return 0
    job.done(i, f"{_plural(r['links'], 'guide link')}, {_plural(r['wins'], 'drafted win')}, "
             f"{_plural(g['joined'], 'record')} grouped with earlier work, {a['tagged']} counted toward impact"
             + (f"; {r['failed']} couldn't be read" if r["failed"] else ""))
    return r["read"]


def run_google(job: Job, Session_, lock) -> None:
    from ..google import calendar as gcal, connector, docs as gdocs, summaries, tasks as gtasks
    last = date.today()
    first = last - timedelta(days=1)
    new = []
    with Session_() as s:
        job.start(0)
        try:
            items = connector.fetch(first, last)
            with lock:
                r = gcal.import_events(s, items, first, last)
            job.done(0, f"{_plural(r['added'], 'new meeting')}, {r['updated']} changed, {r['removed']} gone"
                        + (f"; {r['later']} later today come in once they've ended" if r.get("later") else ""))
            new.append(_plural(r["added"], "meeting"))
        except (gcal.CalendarError, ClaudeError) as exc:
            job.fail(0, f"{exc} Is Google Workspace signed in for Claude Code?")
        job.start(1)
        try:
            tasks, failed = gtasks.fetch(_tasks_since(s))
            with lock:
                r = gtasks.merge(s, tasks, complete=not failed)
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
        job.start(3)
        try:
            found, short = gdocs.fetch(gdocs.since(s))
            with lock:
                r = gdocs.merge(s, found, complete=not short)
            n = gdocs.summarize_pending(s, progress=job.sub)
            detail = f"{_plural(r['added'], 'new file')}, {n['summarized']} summarized" + (
                f", {r['skipped']} skipped by your rules" if r["skipped"] else "")
            if short or n["failed"]:
                job.fail(3, detail + (f"; {_plural(short, 'search')} came back incomplete" if short else "")
                         + (f"; {n['failed']} couldn't be read" if n["failed"] else "") + ". Press Sync Google again.")
            else:
                job.done(3, detail)
            new.append(_plural(r["added"], "file"))
        except ClaudeError as exc:
            job.fail(3, str(exc))
        _link_new(job, 4, s)
    listed = ", ".join(new[:-1]) + " and " + new[-1] if len(new) > 1 else "".join(new)
    job.finish(f"Google synced: {listed} new." if new else "Google sync couldn't read anything.")


def run_promo(job: Job, Session_, start: str, end: str, name: str) -> None:
    """Write a promo case draft: one step per section, ticked as each comes back."""
    from ..promo import write as pw
    keys = [k for k, *_ in pw.SECTIONS]
    for i in range(len(keys)):
        job.start(i)

    def on_section(key: str, detail: str) -> None:
        i = keys.index(key)
        if detail.endswith(" sentences"):
            job.done(i, detail)
        elif detail.startswith("No evidence"):
            job.skip(i, detail)
        else:
            job.fail(i, detail)

    with Session_() as s:
        try:
            v = pw.write_case(s, start=start, end=end, name=name, on_section=on_section)
        except ClaudeError as exc:
            for i, st in enumerate(job.steps):
                if st["state"] == "running":
                    job.fail(i, str(exc))
            job.finish("No draft was saved.")
            return
    job.finish(f"Draft {v.id} is ready.")


def run_rewrite(job: Job, Session_, vid: int, key: str) -> None:
    """Claude redoes one section of a draft; the result is saved as a new draft."""
    from ..promo import write as pw
    from ..storage.models import PromoVersion
    job.start(0)
    with Session_() as s:
        v = s.get(PromoVersion, vid)
        try:
            new = pw.rewrite_section(s, v, key)
        except (ClaudeError, KeyError) as exc:
            job.fail(0, str(exc) if isinstance(exc, ClaudeError) else "That section isn't in this draft.")
            job.finish("Nothing changed.")
            return
    job.done(0, f"Saved as draft {new.id}")
    job.finish(f"Draft {new.id} is ready: open the newest draft to see it.")


GDOC_STEPS = ["Send the copy with sources", "Send the clean copy for sharing"]


def run_gdoc(job: Job, Session_, dd: DataDir, vid: int) -> None:
    """Send a draft to Google Docs twice (with sources, and clean), reading each back to check every word arrived."""
    from sqlalchemy import select
    from ..google import docs_export
    from ..storage.models import PromoSection, PromoVersion
    with Session_() as s:
        v = s.get(PromoVersion, vid)
        sections = list(s.scalars(select(PromoSection).where(PromoSection.version_id == vid)
                                  .order_by(PromoSection.position)))
        for i, sourced in enumerate((True, False)):
            job.start(i)
            try:
                link, same = docs_export.send(dd, v, sections, sourced)
            except ClaudeError as exc:
                job.fail(i, str(exc))
                continue
            if sourced:
                v.google_doc_url = link
            else:
                v.google_doc_clean_url = link
            s.commit()
            if same:
                job.done(i, "Created in My Drive; every word checked")
            else:
                job.fail(i, "Created, but its words don't fully match the draft; open the Doc and check it")
    job.finish("Sent to Google Docs. The links are on the draft.")


GITHUB_STEPS = ["Read your GitHub pull requests", "Link new records to the leveling guide"]


def run_github(job: Job, Session_, lock) -> None:
    from ..github import connector as gh
    with Session_() as s:
        job.start(0)
        try:
            me, prs = gh.fetch(gh.since(s))
            with lock:
                r = gh.merge(s, prs)
        except gh.GitHubError as exc:
            job.fail(0, str(exc))
            job.skip(1)
            job.finish("GitHub sync couldn't read anything.")
            return
        job.done(0, f"{_plural(r['added'], 'new record')} for {me}, {r['updated']} weeks of reviews grew"
                    + (f", {r['skipped']} skipped by your rules" if r["skipped"] else ""))
        _link_new(job, 1, s)
    job.finish(f"GitHub synced: {_plural(r['added'], 'new record')}.")


def run_slack(job: Job, Session_, lock, dd: DataDir) -> None:
    from ..slack.classify import classify
    from ..slack.connector import fetch_canvas
    from ..slack.importer import import_items, load_canvas_id, new_items
    from ..slack.parse import CanvasFormatError, parse_canvas
    with Session_() as s:
        cid = load_canvas_id(dd)
        if not cid:
            job.fail(0, "No Slack canvas connected yet. In Terminal run: uv run careeros slack connect <canvas link>")
            for i in (1, 2, 3):
                job.skip(i)
            job.finish("Slack sync couldn't start.")
            return
        job.start(0)
        try:
            items = parse_canvas(fetch_canvas(cid))
        except (ClaudeError, CanvasFormatError) as exc:
            job.fail(0, str(exc))
            for i in (1, 2, 3):
                job.skip(i)
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
            job.skip(3)
            job.finish("Slack sync read the tracker but couldn't sort the new items, so nothing was saved.")
            return
        job.done(1, f"{r['meeting']} meetings, {r['conversation']} conversations, {r['document']} documents, "
                    f"{r['task']} tasks, {r['note']} other" if r["added"] else "Nothing new since the last pull.")
        praised = _kudos(job, 2, s, lock, dd)
        _link_new(job, 3, s)
    job.finish(f"Slack synced: {_plural(r['added'], 'new item')}" + (f" and {praised} kudos." if praised else "."))


def _kudos(job: Job, i: int, s, lock, dd: DataDir) -> int:
    from ..slack import kudos
    job.start(i)
    try:
        uid, name = kudos.user(dd)
        msgs, full = kudos.fetch(uid, kudos.since(s))
        todo = kudos.new(s, msgs)
        kept = kudos.choose(todo, uid, name)
        with lock:
            n = kudos.merge(s, kept, complete=not full)
    except ClaudeError as exc:
        job.fail(i, str(exc))
        return 0
    detail = f"{_plural(len(todo), 'new mention')} read, {n} kept as kudos"
    if full:
        job.fail(i, detail + f"; {_plural(full, 'search')} didn't fully come back. Press Sync Slack tracker again.")
    else:
        job.done(i, detail)
    return n
