"""The numbered evidence a promotion case is written from: built from the notebook only, nothing else.

Each piece has a number the draft cites, a plain-text line Claude reads, and refs back to the records or wins it
came from. Each section of the case gets its own slice of the pieces.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..guide.activities import LABEL, counts_between
from ..guide.service import promo_map
from ..guide.topics import topic_of
from ..storage.models import GuideItem, GuideLink, JournalEntry, Win, WorkItem

SECTIONS = [  # key, heading, what goes in it (for Claude), how long
    ("summary", "Summary", "where the candidate stands: ready for Grade 6, the areas where the work already reaches "
     "Grade 7, and the scale of the work", "3 to 4 sentences"),
    ("accomplishments", "Key accomplishments", "the most significant accomplishments, most significant first, one "
     "per sentence, saying what was done and how big it was", "5 to 8 sentences"),
    ("impact", "Impact", "what changed because of the work: outcomes, who it helped, and the activity counts",
     "3 to 6 sentences"),
    ("behaviors", "Behaviors & values", "how the candidate works: communication, mentoring, ownership, improving "
     "process, helping other teams", "3 to 5 sentences"),
    ("growth", "Growth areas", "an honest account of the Grade 6 and Grade 7 experiences not shown yet, and the "
     "concrete next steps; do not spin gaps as strengths", "3 to 5 sentences"),
]
SIZE_ORDER = {"large": 0, "medium": 1, "small": 2}
CAPS = dict(summary=40, accomplishments=50, impact=40, behaviors=40, growth=40)
SUMMARY_WINS = 15  # leaves room in the summary for the counts and the Promo map progress
SKILL_ACTIVITIES = {"mentoring", "process_change", "document", "demo"}


def _label(g: GuideItem) -> str:
    return f"{topic_of(g.name).name} (Grade {g.grade})" if g.kind == "experience" else g.name


def build(s: Session, start: str, end: str) -> tuple[list[dict], dict[str, list[int]]]:
    """(pieces, section key -> piece numbers). Only records and wins dated inside the window count."""
    items = {g.id: g for g in s.scalars(select(GuideItem))}
    shows: dict[tuple[str, int], list[GuideItem]] = {}
    for l in s.scalars(select(GuideLink)):
        if l.item_id in items:
            shows.setdefault(("win", l.win_id) if l.win_id else ("entry", l.entry_id), []).append(items[l.item_id])
    entries = {e.id: e for e in s.scalars(select(JournalEntry).where(
        JournalEntry.day >= start, JournalEntry.day <= end, JournalEntry.status != "open"))}
    wins = sorted(s.scalars(select(Win).where(Win.day >= start, Win.day <= end)), key=lambda w: w.day, reverse=True)
    wins.sort(key=lambda w: SIZE_ORDER.get(w.size, 3))  # biggest first, newest first within a size
    pieces: list[dict] = []
    slices: dict[str, list[int]] = {k: [] for k, *_ in SECTIONS}

    def add(kind: str, text: str, day: str, refs: list[dict], into: list[str]) -> None:
        n = len(pieces) + 1
        pieces.append(dict(n=n, kind=kind, text=text, day=day, refs=refs))
        for key in into:
            if len(slices[key]) < CAPS[key]:
                slices[key].append(n)

    # wins first: the strongest evidence
    won_entries = set()
    for i, w in enumerate(wins):
        g = shows.get(("win", w.id), [])
        text = f"Win ({w.size}, {w.day}): {w.title}." + (f" Why it mattered: {w.impact}" if w.impact else "") \
            + (f" Shows: {', '.join(_label(x) for x in g)}." if g else "")
        into = ["accomplishments"] + (["impact"] if w.impact else []) \
            + (["summary"] if w.size != "small" and i < SUMMARY_WINS else []) \
            + (["behaviors"] if any(x.kind == "skill" for x in g) else [])
        add("win", text, w.day, [dict(win=w.id), *([dict(entry=w.entry_id)] if w.entry_id else [])], into)
        if w.entry_id:
            won_entries.add(w.entry_id)

    # pieces of work with guide links or an activity, unless a win already covers them
    members: dict[int, list[JournalEntry]] = {}
    for e in entries.values():
        if e.work_item_id:
            members.setdefault(e.work_item_id, []).append(e)
    for w in sorted(s.scalars(select(WorkItem).where(WorkItem.id.in_(members))), key=lambda w: w.day, reverse=True):
        recs = sorted(members[w.id], key=lambda e: e.day)
        if any(e.id in won_entries for e in recs):
            continue
        g = {x.id: x for e in recs for x in shows.get(("entry", e.id), [])}.values()
        acts = sorted({LABEL[e.activity] for e in recs if e.activity})
        if not g and not acts:
            continue
        text = (f"Piece of work: {w.title} ({recs[0].day} to {recs[-1].day}, {len(recs)} records): "
                + "; ".join(e.text[:120] for e in recs[:4]) + "."
                + (f" Shows: {', '.join(_label(x) for x in g)}." if g else "")
                + (f" Activity: {', '.join(acts)}." if acts else ""))
        into = ["accomplishments"] + (["impact"] if acts else []) \
            + (["behaviors"] if any(x.kind == "skill" for x in g) or {e.activity for e in recs} & SKILL_ACTIVITIES else [])
        add("work", text, recs[-1].day, [dict(entry=e.id) for e in recs], into)

    # single linked records that aren't part of a piece of work or a win
    singles = [e for e in sorted(entries.values(), key=lambda e: e.day, reverse=True)
               if not e.work_item_id and e.id not in won_entries and (shows.get(("entry", e.id)) or e.activity)]
    for e in singles[:60]:
        g = shows.get(("entry", e.id), [])
        text = f"Record ({e.day}): {e.text[:200]}." + (f" Shows: {', '.join(_label(x) for x in g)}." if g else "") \
            + (f" Activity: {LABEL[e.activity]}." if e.activity else "")
        into = ["accomplishments"] + (["behaviors"] if any(x.kind == "skill" for x in g) or e.activity in SKILL_ACTIVITIES
                                      else [])
        add("record", text, e.day, [dict(entry=e.id)], into)

    # activity counts over the window
    for c in counts_between(s, start, end):
        add("count", f"Count: {c['n']} {c['label']} between {start} and {end}.", end, [dict(activity=c["key"])],
            ["summary", "impact"])

    # where the Promo map stands today, and what's still missing
    pm = promo_map(s)
    for gr in pm["grades"]:
        p = pm["progress"][gr]
        add("progress", f"Promo map, Grade {gr}: {p['shown'] + p['strong']} of {p['total']} key experiences shown "
            f"({p['strong']} strong), {p['started']} started, {p['gap']} not shown yet.", end, [],
            ["summary", "growth"])
    for row in pm["rows"]:
        for gr in pm["grades"]:
            for x in row["cells"][gr]:
                if x["status"] in ("gap", "started"):
                    what = "not shown yet" if x["status"] == "gap" else "started, needs more evidence"
                    add("gap", f"Grade {gr} key experience {what}: {x['item'].name}", end, [], ["growth"])
    for nxt in pm["next"]:
        add("next", f"Next step idea for {nxt['topic'].name} (Grade {nxt['grade']}): {nxt['idea']}", end, [], ["growth"])
    return pieces, slices
