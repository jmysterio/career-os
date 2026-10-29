"""When each source was last pulled, and whether that's recent enough to have yesterday's work."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import JournalEntry, SyncRun

SOURCES = {"slack": "Slack tracker", "calendar": "Google Calendar", "tasks": "Google Tasks", "github": "GitHub pull requests"}
SLACK_READY = time(17, 30)  # the Slack tracker automation runs at 5 PM; give it time to finish


def record(s: Session, source: str, added: int) -> None:
    """Call inside the sync's own transaction; the caller commits."""
    s.add(SyncRun(source=source, at=datetime.now(), added=added))


def when(d: datetime | date, now: datetime) -> str:
    day = d.date() if isinstance(d, datetime) else d
    label = ("today" if day == now.date() else "yesterday" if day == now.date() - timedelta(days=1)
             else f"{day:%a, %b} {day.day}")
    return f"{label} at {d:%I:%M %p}".replace(" 0", " ") if isinstance(d, datetime) else label


def status(s: Session, now: datetime | None = None) -> dict[str, dict]:
    now = now or datetime.now()
    out = {}
    for src, label in SOURCES.items():
        run = s.scalars(select(SyncRun).where(SyncRun.source == src).order_by(SyncRun.at.desc()).limit(1)).first()
        last = run.at if run else s.scalar(select(func.max(JournalEntry.created_at)).where(JournalEntry.source == src))
        newest = s.scalar(select(func.max(JournalEntry.day)).where(JournalEntry.source == src))
        ok, hint = None, ""
        if src == "slack":
            cutoff = datetime.combine(now.date(), SLACK_READY)
            if now < cutoff:
                cutoff -= timedelta(days=1)
            ok = bool(last and last >= cutoff)
            hint = "" if ok else f"The 5 PM Slack log from {when(cutoff.date(), now)} isn't pulled in yet."
        else:
            ok = bool(last and last.date() == now.date())
            hint = "" if ok else "Not synced today yet."
        out[src] = dict(label=label, at=last, at_text=when(last, now) if last else "never",
                        added=run.added if run else None, estimated=bool(last and not run),
                        newest=when(date.fromisoformat(newest), now) if newest else "", ok=ok, hint=hint)
    return out
