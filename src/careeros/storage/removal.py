"""Removing a journal entry for good, while remembering it so syncs don't bring it back."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import GuideLink, JournalAttachment, JournalEntry, RemovedEntry, SkipRule, Win


def skip_patterns(s: Session, source: str = "calendar") -> list[str]:
    return [p.lower() for p in s.scalars(select(SkipRule.pattern).where(SkipRule.source == source))]


def add_skip_rule(s: Session, pattern: str, source: str = "calendar") -> int:
    """Saves the rule and removes existing entries from that source whose text contains it. Returns how many."""
    pattern = " ".join(pattern.split())
    if not pattern:
        raise ValueError("Give some title text to match.")
    if pattern.lower() not in skip_patterns(s, source):
        s.add(SkipRule(source=source, pattern=pattern, created_at=datetime.now()))
        s.commit()
    ids = [e.id for e in s.scalars(select(JournalEntry).where(JournalEntry.source == source))
           if pattern.lower() in e.text.lower()]
    for eid in ids:
        remove_entry(s, eid)
    return len(ids)


def drop_skip_rule(s: Session, pattern: str, source: str = "calendar") -> bool:
    n = s.execute(delete(SkipRule).where(SkipRule.source == source, SkipRule.pattern == pattern)).rowcount
    s.commit()
    return bool(n)


def removed_ids(s: Session, source: str) -> set[str]:
    return set(s.scalars(select(RemovedEntry.external_id).where(
        RemovedEntry.source == source, RemovedEntry.external_id.is_not(None))))


def remove_entry(s: Session, eid: int) -> bool:
    """Deletes the entry, its pasted text, its guide links, and wins Claude drafted from it.
    Wins the user made or edited stay, unlinked from the entry."""
    e = s.get(JournalEntry, eid)
    if e is None:
        return False
    s.add(RemovedEntry(day=e.day, kind=e.kind, text=e.text, source=e.source, external_id=e.external_id,
                       status=e.status, removed_at=datetime.now()))
    s.execute(delete(JournalAttachment).where(JournalAttachment.entry_id == eid))
    for w in s.scalars(select(Win).where(Win.entry_id == eid)):
        if w.by_ai:
            s.execute(delete(GuideLink).where(GuideLink.win_id == w.id))
            s.delete(w)
        else:
            w.entry_id = None
    s.execute(delete(GuideLink).where(GuideLink.entry_id == eid))
    s.delete(e)
    s.commit()
    return True


def restore_entry(s: Session, rid: int) -> int | None:
    """Puts a removed entry back (without its pasted text, links, or drafted wins). Returns the new entry id."""
    r = s.get(RemovedEntry, rid)
    if r is None:
        return None
    e = JournalEntry(day=r.day, kind=r.kind, text=r.text, source=r.source, external_id=r.external_id,
                     status=r.status, created_at=datetime.now())
    s.add(e)
    s.delete(r)
    s.commit()
    return e.id
