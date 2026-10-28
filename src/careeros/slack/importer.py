"""Saves Slack canvas items as notebook entries, tagged as coming from Slack, once each."""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DataDir
from ..storage.models import JournalAttachment, JournalEntry
from .parse import TRACKER, SlackItem

SOURCE = "slack"
NOTES_TITLE = "From Slack (AI-written)"
IMPACT_LINE = re.compile(r"^Why it mattered: (.+)$", re.M)


def new_items(s: Session, items: list[SlackItem]) -> list[SlackItem]:
    from ..storage.removal import removed_ids
    have = set(s.scalars(select(JournalEntry.external_id).where(JournalEntry.source == SOURCE))) | removed_ids(s, SOURCE)
    return [i for i in items if i.key not in have]


def import_items(s: Session, items: list[SlackItem], classify: Callable[[list[SlackItem]], dict[str, str]]) -> dict:
    todo = new_items(s, items)
    kinds = classify(todo) if todo else {}
    todo = new_items(s, todo)  # classify takes minutes; another sync may have saved some of these meanwhile
    counts = {k: 0 for k in ("meeting", "conversation", "document", "task", "note")}
    for it in todo:
        kind = kinds.get(it.key, "note")
        kind = kind if kind in counts else "note"
        e = JournalEntry(day=it.day, kind=kind, text=it.text, created_at=datetime.now(), source=SOURCE,
                         external_id=it.key, status="done" if kind == "task" else "")
        s.add(e)
        s.flush()
        s.add(JournalAttachment(entry_id=e.id, kind="notes", title=f"{NOTES_TITLE}, {it.origin}", body=it.body,
                                created_at=datetime.now()))
        if it.link:
            s.add(JournalAttachment(entry_id=e.id, kind="link", title="Slack thread", body=it.link,
                                    created_at=datetime.now()))
        counts[kind] += 1
    if any(i.origin == TRACKER for i in items):  # old promo canvases don't say anything about the daily log
        from ..storage.sync_log import record
        record(s, SOURCE, len(todo))
    s.commit()
    return dict(added=len(todo), skipped=len(items) - len(todo), **counts)


def impact_of(body: str) -> str:
    m = IMPACT_LINE.search(body)
    return m.group(1).strip() if m else ""


def canvas_file(dd: DataDir):
    return dd.root / "slack.canvas"


def save_canvas_id(dd: DataDir, value: str) -> str:
    m = re.search(r"\b(F[A-Z0-9]{8,})\b", value.strip())
    if not m:
        raise ValueError("That doesn't look like a canvas link or ID (it starts with F, like F0C2ZF10L02).")
    fd = os.open(canvas_file(dd), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(m.group(1) + "\n")
    return m.group(1)


def load_canvas_id(dd: DataDir) -> str | None:
    f = canvas_file(dd)
    return f.read_text().strip() if f.exists() else None
