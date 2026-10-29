"""The Friday digest: what the week added, and a few nudges, each linking to where to act. Built from the notebook
when the page loads (no Claude, nothing stored)."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .storage.models import GuideItem, GuideLink, JournalEntry, Win

QUIET_DAYS = 60
QUEUE_NUDGE = 25  # unchecked records before the queue gets a nudge
SOURCE_NAME = {"calendar": "meetings", "tasks": "Google Tasks", "slack": "Slack tracker items", "docs": "Google files",
               "github": "GitHub records", "kudos": "kudos", "": "typed notes"}


def week_of(day: date) -> tuple[date, date]:
    """The seven days ending on `day`."""
    return day - timedelta(days=6), day


def build(s: Session, week_end: date | None = None) -> dict:
    from .guide.activities import counts, counts_between
    from .guide.service import has_guide, promo_map
    from .guide.topics import topic_of
    first, last = week_of(week_end or date.today())
    lo, hi = first.isoformat(), last.isoformat()
    wins = list(s.scalars(select(Win).where(Win.day >= lo, Win.day <= hi).order_by(Win.day.desc())))
    entries = list(s.scalars(select(JournalEntry).where(JournalEntry.day >= lo, JournalEntry.day <= hi,
                                                        JournalEntry.status != "open")))
    by_source = Counter(e.source or "" for e in entries)
    kudos = [e for e in entries if e.kind == "recognition"]
    start, end = datetime.combine(first, time.min), datetime.combine(last, time.max)
    gained = Counter(s.scalars(select(GuideItem.name).join(GuideLink, GuideLink.item_id == GuideItem.id)
                               .where(GuideLink.created_at >= start, GuideLink.created_at <= end)))
    pm = promo_map(s) if has_guide(s) else None
    totals = {c["key"]: c for c in counts(s, last)} if pm else {}
    activity = [dict(c, half=totals.get(c["key"], {}).get("half", c["n"])) for c in counts_between(s, lo, hi)]

    nudges = []
    aimed = {n["topic"].name for n in pm["next"][:2]} if pm else set()
    if pm:
        for n in pm["next"][:2]:
            nudges.append(dict(text=f"Aim for next in {n['topic'].name} (Grade {n['grade']}): {n['idea']}",
                               link="/promo", act="Open the Promo map"))
    unexplained = s.scalar(select(func.count()).select_from(Win).where(Win.size.in_(("large", "medium")),
                                                                      Win.impact == "")) or 0
    if unexplained:
        nudges.append(dict(text=f"{unexplained} big win{'s' if unexplained != 1 else ''} without \"why it mattered\". "
                                "A sentence each makes them count in the promo case.", link="/wins", act="Open Wins"))
    if pm:
        quiet_since = (last - timedelta(days=QUIET_DAYS)).isoformat()
        for row in pm["rows"]:
            days = [x.day for gr in pm["grades"] for c in row["cells"][gr] for x in c["wins"] + c["entries"]]
            if days and max(days) < quiet_since and row["topic"].name not in aimed:
                nudges.append(dict(text=f"Nothing new for {row['topic'].name} in {QUIET_DAYS} days (last: {max(days)}).",
                                   link="/promo", act="Open the Promo map"))
    queue = s.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.reviewed.is_(False))) or 0
    if queue >= QUEUE_NUDGE:
        nudges.append(dict(text=f"{queue} records in the Intake Review Queue haven't been checked yet.",
                           link="/sheet?show=todo", act="Open the queue"))
    return dict(first=first, last=last, wins=wins, kudos=kudos, records=len(entries),
                sources=[(SOURCE_NAME.get(k, k), n) for k, n in by_source.most_common()],
                gained=[dict(name=k, topic=topic_of(k).name, n=n) for k, n in gained.most_common(8)],
                activity=activity, nudges=nudges, has_guide=bool(pm))


def summary(d: dict) -> str:
    """One line for the notification, written by code."""
    parts = [f"{len(d['wins'])} win{'s' if len(d['wins']) != 1 else ''}", f"{d['records']} records"]
    if d["kudos"]:
        parts.append(f"{len(d['kudos'])} kudos")
    nudge = f", {len(d['nudges'])} nudge{'s' if len(d['nudges']) != 1 else ''}" if d["nudges"] else ""
    return "This week: " + ", ".join(parts) + nudge + ". Open http://127.0.0.1:8765/digest"
