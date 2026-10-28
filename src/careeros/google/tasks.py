"""Google Tasks into the notebook. Title, notes, and done/open state only."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import JournalAttachment, JournalEntry

SOURCE = "tasks"


LISTS_TOOL = "mcp__plugin_google-workspace_google-workspace__list_task_lists"
TASKS_TOOL = "mcp__plugin_google-workspace_google-workspace__list_tasks"
LIST_LINE = re.compile(r"^- .* \(ID: ([^)\s]+)\)\n  Updated: (\S+)", re.M)
TASK_HEAD = re.compile(r"- (.*) \(ID: ([^)\s]+)\)")


@dataclass(frozen=True)
class Task:
    title: str
    done: bool
    when: datetime   # completion time if done, else due/updated time (local)
    notes: str = ""
    gid: str = ""    # Google's task id, when it came from the connector

    @property
    def key(self) -> str:
        return "task:" + hashlib.sha1(f"{self.title}|{self.done}|{self.when:%Y-%m-%dT%H:%M}".encode()).hexdigest()[:16]


def sync(s: Session, tasks: list[Task]) -> dict[str, int]:
    """Replace-all for the fetched lists: add new, drop ones that vanished (kept if you attached anything)."""
    existing = {e.external_id: e for e in s.scalars(select(JournalEntry).where(JournalEntry.source == SOURCE))}
    from ..storage.removal import removed_ids
    gone_by_user = removed_ids(s, SOURCE)
    added = removed = 0
    today = date.today().isoformat()
    for t in tasks:
        if existing.pop(t.key, None) is not None or t.key in gone_by_user:
            continue
        day = min(t.when.date().isoformat(), today)
        e = JournalEntry(day=day, kind="task", text=t.title[:500], created_at=datetime.now(), source=SOURCE,
                         external_id=t.key, status="done" if t.done else "open")
        s.add(e)
        s.flush()
        if t.notes.strip():
            s.add(JournalAttachment(entry_id=e.id, kind="notes", title="Task notes", body=t.notes.strip(),
                                    created_at=datetime.now()))
        added += 1
    from ..guide.service import keeps_entry
    for gone in existing.values():
        if not keeps_entry(s, gone) and not s.scalar(select(JournalAttachment.id).where(
                JournalAttachment.entry_id == gone.id, JournalAttachment.title != "Task notes").limit(1)):
            for a in s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == gone.id)):
                s.delete(a)
            s.delete(gone)
            removed += 1
    from ..storage.sync_log import record
    record(s, SOURCE, added)
    s.commit()
    return dict(added=added, removed=removed)


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def parse_lists(text: str) -> list[tuple[str, datetime]]:
    return [(lid, _local(ts)) for lid, ts in LIST_LINE.findall(text)]


def parse_tasks(text: str) -> list[Task]:
    out = []
    for block in re.split(r"\n(?=- )", text):
        head = TASK_HEAD.match(block.strip())
        if not head:
            continue
        f = dict(re.findall(r"^  (\w+): (.*)$", block, re.M))
        done = f.get("Status") == "completed"
        ts = (f.get("Completed") if done else f.get("Due")) or f.get("Updated")
        if not ts:
            continue
        out.append(Task(head.group(1).strip(), done, _local(ts), f.get("Notes", "").strip(), head.group(2)))
    return out


def fetch(since: datetime) -> tuple[list[Task], int]:
    """Tasks changed since `since`, from task lists changed since then. Returns (tasks, lists that failed)."""
    from ..claude_cli import ClaudeError, call_tool, call_tools, connector_error
    raw = call_tool("Call the list_task_lists tool exactly once. When it returns, reply with only DONE.", LISTS_TOOL)
    if err := connector_error(raw, "Google"):
        raise ClaudeError(err)
    lists = [lid for lid, updated in parse_lists(raw) if updated >= since]
    if not lists:
        return [], 0
    stamp = since.astimezone().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = ("Call the list_tasks tool once for each of these task_list_id values, with show_completed=true, "
              f"show_hidden=true, max_results=100, updated_min={stamp}: {', '.join(lists)}. "
              "When they have all returned, reply with only DONE.")
    tasks, ok = [], set()
    for _tool, args, text in call_tools(prompt, [TASKS_TOOL], timeout=300, max_turns=len(lists) + 6):
        if connector_error(text, "Google") is None and args.get("task_list_id") in lists:
            ok.add(args["task_list_id"])
            tasks += parse_tasks(text)
    return tasks, len(set(lists) - ok)


def merge(s: Session, tasks: list[Task], complete: bool = True) -> dict[str, int]:
    """Adds new tasks and updates ones that changed (an open task that got done). Never deletes: a fetch only
    covers recently changed lists. An incomplete fetch isn't logged, so the next sync starts from the old mark."""
    from ..storage.removal import removed_ids
    mine = list(s.scalars(select(JournalEntry).where(JournalEntry.source == SOURCE)))
    by_key = {e.external_id: e for e in mine}
    gone = removed_ids(s, SOURCE)
    today = date.today().isoformat()
    added = updated = 0
    for t in tasks:
        ext = f"gtask:{t.gid}"
        if ext in gone or t.key in gone:
            continue
        status, day = ("done" if t.done else "open"), min(t.when.date().isoformat(), today)
        e = by_key.get(ext) or by_key.get(t.key) or next(
            (x for x in mine if x.text == t.title[:500] and not (x.external_id or "").startswith("gtask:")
             and ((x.status == "open" and t.done) or (x.status == status and x.day == day))), None)
        if e is None:
            e = JournalEntry(day=day, kind="task", text=t.title[:500], created_at=datetime.now(), source=SOURCE,
                             external_id=ext, status=status)
            s.add(e)
            s.flush()
            if t.notes:
                s.add(JournalAttachment(entry_id=e.id, kind="notes", title="Task notes", body=t.notes,
                                        created_at=datetime.now()))
            mine.append(e)
            added += 1
        elif e.kind == "task" and (e.status != status or e.external_id != ext):
            if e.status != status:
                e.status, e.day = status, day
                updated += 1
            e.external_id = ext
        by_key[ext] = e
    if complete:
        from ..storage.sync_log import record
        record(s, SOURCE, added)
    s.commit()
    return dict(added=added, updated=updated)
