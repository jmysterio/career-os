"""Google Tasks into the notebook. Title, notes, and done/open state only."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import JournalAttachment, JournalEntry

SOURCE = "tasks"


@dataclass(frozen=True)
class Task:
    title: str
    done: bool
    when: datetime   # completion time if done, else due/updated time (local)
    notes: str = ""

    @property
    def key(self) -> str:
        return "task:" + hashlib.sha1(f"{self.title}|{self.done}|{self.when:%Y-%m-%dT%H:%M}".encode()).hexdigest()[:16]


def sync(s: Session, tasks: list[Task]) -> dict[str, int]:
    """Replace-all for the fetched lists: add new, drop ones that vanished (kept if you attached anything)."""
    existing = {e.external_id: e for e in s.scalars(select(JournalEntry).where(JournalEntry.source == SOURCE))}
    added = removed = 0
    today = date.today().isoformat()
    for t in tasks:
        if existing.pop(t.key, None) is not None:
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
    for gone in existing.values():
        if not s.scalar(select(JournalAttachment.id).where(JournalAttachment.entry_id == gone.id,
                                                           JournalAttachment.title != "Task notes").limit(1)):
            for a in s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == gone.id)):
                s.delete(a)
            s.delete(gone)
            removed += 1
    s.commit()
    return dict(added=added, removed=removed)
