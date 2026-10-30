"""The home dashboard: how close the promotion is, and whether the work keeps coming. Built from the notebook when the
page loads (no Claude, nothing stored)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .storage.models import GuideLink, JournalEntry, Win

WEEKS = 12


def _half_start(today: date) -> str:
    return date(today.year, 1 if today.month <= 6 else 7, 1).isoformat()


def momentum(s: Session, today: date) -> list[dict]:
    """Evidence per week for the last WEEKS weeks (oldest first): wins plus records linked to the guide."""
    first = today - timedelta(days=today.weekday()) - timedelta(weeks=WEEKS - 1)
    lo = first.isoformat()
    linked = set(s.scalars(select(GuideLink.entry_id).where(GuideLink.entry_id.is_not(None))))
    days = [e.day for e in s.scalars(select(JournalEntry).where(JournalEntry.day >= lo, JournalEntry.status != "open"))
            if e.id in linked]
    days += list(s.scalars(select(Win.day).where(Win.day >= lo)))
    weeks = [dict(start=first + timedelta(weeks=i), n=0) for i in range(WEEKS)]
    for d in days:
        i = (date.fromisoformat(d) - first).days // 7
        if 0 <= i < WEEKS:
            weeks[i]["n"] += 1
    top = max([w["n"] for w in weeks] + [1])
    for w in weeks:
        w["pct"] = round(100 * w["n"] / top)
    return weeks


def build(s: Session, today: date | None = None) -> dict:
    from .guide.service import CURRENT_GRADE, has_guide, promo_map
    today = today or date.today()
    half = _half_start(today)
    pm = promo_map(s) if has_guide(s) else None
    grades = []
    skills = None
    nxt = None
    if pm:
        for gr in pm["grades"]:
            p = pm["progress"][gr]
            shown = p["shown"] + p["strong"]
            grades.append(dict(grade=gr, shown=shown, total=p["total"], strong=p["strong"], started=p["started"],
                               pct=round(100 * shown / p["total"]) if p["total"] else 0))
        views = pm["rising"] + pm["steady"]
        skills = dict(shown=sum(1 for x in views if x["status"] in ("shown", "strong")), total=len(views))
        nxt = pm["next"][0] if pm["next"] else None
    return dict(
        grades=grades, skills=skills, next=nxt, current=CURRENT_GRADE, weeks=momentum(s, today),
        wins=s.scalar(select(func.count()).select_from(Win).where(Win.day >= half)) or 0,
        kudos=s.scalar(select(func.count()).select_from(JournalEntry).where(
            JournalEntry.kind == "recognition", JournalEntry.day >= half)) or 0,
        queue=s.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.reviewed.is_(False))) or 0,
        half="Jan to Jun" if today.month <= 6 else "Jul to Dec")
