"""Leveling guide storage, links from the user's work to guide items, and how much evidence each item has."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..storage.models import GuideItem, GuideLink, JournalEntry, Win
from .parse import parse_guide
from .topics import suggest

CURRENT_GRADE = 5
TARGET_GRADES = (6, 7)
POINTS = {"entry": 1, "small": 2, "medium": 3, "large": 4}
STATUSES = [(6, "strong", "Strong"), (3, "shown", "Shown"), (1, "started", "Started"), (0, "gap", "Not yet")]


def import_guide(s: Session, path: Path | str) -> dict:
    items = parse_guide(path)
    have = {g.key: g for g in s.scalars(select(GuideItem))}
    seen, added, updated = set(), 0, 0
    for pos, it in enumerate(items):
        if it["key"] in seen:
            continue
        seen.add(it["key"])
        g = have.get(it["key"])
        if g is None:
            s.add(GuideItem(**it, position=pos, active=True))
            added += 1
        else:
            changed = (g.name, g.description, g.targets, g.category, g.active) != (
                it["name"], it["description"], it["targets"], it["category"], True)
            g.name, g.description, g.targets, g.category, g.position, g.active = (
                it["name"], it["description"], it["targets"], it["category"], pos, True)
            updated += changed
    retired = 0
    for key, g in have.items():
        if key not in seen and g.active:
            g.active = False  # kept so existing links still show; it just leaves the map
            retired += 1
    s.commit()
    return dict(added=added, updated=updated, retired=retired)


def has_guide(s: Session) -> bool:
    return s.scalar(select(GuideItem.id).where(GuideItem.active).limit(1)) is not None


def experiences(s: Session, grades=TARGET_GRADES) -> list[GuideItem]:
    return list(s.scalars(select(GuideItem).where(
        GuideItem.kind == "experience", GuideItem.active, GuideItem.grade.in_(grades)).order_by(GuideItem.position)))


def skills(s: Session) -> list[GuideItem]:
    return list(s.scalars(select(GuideItem).where(GuideItem.kind == "skill", GuideItem.active)
                          .order_by(GuideItem.position)))


def summaries(s: Session) -> dict[int, str]:
    return {g.grade: g.name for g in s.scalars(select(GuideItem).where(GuideItem.kind == "summary", GuideItem.active))}


def status(points: float) -> tuple[str, str]:
    return next((key, label) for floor, key, label in STATUSES if points >= floor)


def evidence(s: Session) -> dict[int, dict]:
    """item id -> {points, wins, entries}. An entry already counted through a win made from it isn't counted twice."""
    links = list(s.scalars(select(GuideLink)))
    wins = {w.id: w for w in s.scalars(select(Win).where(Win.id.in_({l.win_id for l in links if l.win_id})))}
    entries = {e.id: e for e in s.scalars(select(JournalEntry).where(
        JournalEntry.id.in_({l.entry_id for l in links if l.entry_id})))}
    out: dict[int, dict] = {}
    for l in links:
        ev = out.setdefault(l.item_id, dict(points=0, wins=[], entries=[]))
        if l.win_id in wins:
            ev["wins"].append(wins[l.win_id])
    for l in links:
        ev = out[l.item_id]
        if l.entry_id in entries and all(w.entry_id != l.entry_id for w in ev["wins"]):
            ev["entries"].append(entries[l.entry_id])
    for ev in out.values():
        ev["wins"].sort(key=lambda w: w.day, reverse=True)
        ev["entries"].sort(key=lambda e: e.day, reverse=True)
        ev["points"] = sum(POINTS.get(w.size, 2) for w in ev["wins"]) + POINTS["entry"] * len(ev["entries"])
    return out


def promo_map(s: Session) -> dict:
    """Topics as rows with each target grade's experiences, plus per-grade progress and skills, with evidence."""
    from .topics import OTHER, TOPICS, topic_of
    ev = evidence(s)
    empty = dict(points=0, wins=[], entries=[])

    def view(g: GuideItem) -> dict:
        e = ev.get(g.id, empty)
        key, label = status(e["points"])
        return dict(item=g, status=key, status_label=label, **e)

    exps = [view(g) for g in experiences(s)]
    rows = []
    for t in [*TOPICS, OTHER]:
        cells = {gr: [x for x in exps if x["item"].grade == gr and topic_of(x["item"].name) == t] for gr in TARGET_GRADES}
        if any(cells.values()):
            rows.append(dict(topic=t, cells=cells))
    progress = {}
    for gr in TARGET_GRADES:
        mine = [x for x in exps if x["item"].grade == gr]
        progress[gr] = dict(total=len(mine), **{k: sum(1 for x in mine if x["status"] == k)
                                                for _f, k, _l in STATUSES})
    skill_views = [dict(view(g), now=g.targets.get(str(CURRENT_GRADE)),
                        **{f"g{gr}": g.targets.get(str(gr)) for gr in TARGET_GRADES}) for g in skills(s)]
    hi, lo = TARGET_GRADES[-1], TARGET_GRADES[0]
    rising = [x for x in skill_views if (x[f"g{hi}"] or 0) > (x[f"g{lo}"] or 0)]
    nxt = []  # one step per topic: finish the lower grade first, then step up
    for row in rows:
        t = row["topic"]
        for i, gr in enumerate(TARGET_GRADES):
            todo = [x for x in row["cells"][gr] if x["status"] in ("gap", "started")]
            if todo and t.ideas:
                started = any(x["status"] != "gap" for gr2 in TARGET_GRADES for x in row["cells"][gr2])
                nxt.append(dict(topic=t, grade=gr, item=todo[0]["item"], started=started,
                                idea=t.ideas[0] if i == 0 else t.ideas[-1]))
                break
    nxt.sort(key=lambda n: (not n["started"], n["grade"]))
    return dict(rows=rows, progress=progress, rising=rising, next=nxt,
                steady=[x for x in skill_views if x not in rising], summaries=summaries(s), grades=TARGET_GRADES,
                current=CURRENT_GRADE)


def suggested_ids(s: Session, text: str) -> set[int]:
    from .topics import topic_of
    topics, skill_names = suggest(text)
    keys = {t.key for t in topics}
    ids = {g.id for g in experiences(s) if topic_of(g.name).key in keys}
    return ids | {g.id for g in skills(s) if g.name in skill_names}


def linked_ids(s: Session, *, win_id: int | None = None, entry_id: int | None = None) -> set[int]:
    return set(s.scalars(select(GuideLink.item_id).where(GuideLink.win_id == win_id, GuideLink.entry_id == entry_id)))


def set_links(s: Session, ids: set[int], *, win_id: int | None = None, entry_id: int | None = None) -> None:
    valid = set(s.scalars(select(GuideItem.id).where(GuideItem.id.in_(ids), GuideItem.kind != "summary")))
    s.execute(delete(GuideLink).where(GuideLink.win_id == win_id, GuideLink.entry_id == entry_id))
    s.add_all(GuideLink(item_id=i, win_id=win_id, entry_id=entry_id, created_at=datetime.now()) for i in sorted(valid))
    s.commit()


def keeps_entry(s: Session, e: JournalEntry) -> bool:
    """True when the user (or Claude) built on this entry, so a sync must not delete it."""
    return e.reviewed or s.scalar(select(Win.id).where(Win.entry_id == e.id).limit(1)) is not None or \
        s.scalar(select(GuideLink.id).where(GuideLink.entry_id == e.id).limit(1)) is not None


def confirm(s: Session, entry_id: int) -> None:
    """The user checked this row: Claude's picks for it (links, type, drafted win) become the user's own."""
    e = s.get(JournalEntry, entry_id)
    if e is None:
        return
    e.reviewed = True
    wins = list(s.scalars(select(Win).where(Win.entry_id == entry_id)))
    for w in wins:
        w.by_ai = False
    for l in s.scalars(select(GuideLink).where(
            (GuideLink.entry_id == entry_id) | GuideLink.win_id.in_([w.id for w in wins]))):
        l.by_ai = False
    s.commit()


def ai_counts(s: Session) -> dict[str, int]:
    from sqlalchemy import func
    return dict(links=s.scalar(select(func.count()).select_from(GuideLink).where(
        GuideLink.by_ai, GuideLink.entry_id.is_not(None))) or 0,
                wins=s.scalar(select(func.count()).select_from(Win).where(Win.by_ai)) or 0)


def drop_links(s: Session, *, win_id: int | None = None, entry_id: int | None = None) -> None:
    q = delete(GuideLink)
    s.execute(q.where(GuideLink.win_id == win_id) if win_id is not None else q.where(GuideLink.entry_id == entry_id))
