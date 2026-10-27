"""Master export: everything in the notebook as CSV files in one zip, readable without this app."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import GuideItem, GuideLink, JournalAttachment, JournalEntry, Win

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(v) -> str:
    """Spreadsheets run cells that start with = + - @ as formulas, and calendar titles come from other people."""
    s = "" if v is None else v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else str(v)
    return "'" + s if s.startswith(FORMULA_START) else s


def _csv(header: list[str], rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows([_cell(v) for v in r] for r in rows)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")  # the BOM makes Excel read accents and emoji correctly


def notebook_zip(s: Session) -> bytes:
    entries = list(s.scalars(select(JournalEntry).order_by(JournalEntry.day, JournalEntry.id)))
    text_of = {e.id: (e.day, e.text) for e in entries}
    atts = s.scalars(select(JournalAttachment).order_by(JournalAttachment.entry_id, JournalAttachment.id))
    wins = list(s.scalars(select(Win).order_by(Win.day, Win.id)))
    title_of = {w.id: w.title for w in wins}
    links = s.execute(select(GuideLink, GuideItem).join(GuideItem, GuideItem.id == GuideLink.item_id)
                      .order_by(GuideItem.position, GuideLink.id))
    files = {
        "entries.csv": _csv(
            ["entry_id", "day", "kind", "text", "task_status", "source", "created_at"],
            ([e.id, e.day, e.kind, e.text, e.status, e.source or "typed", e.created_at] for e in entries)),
        "pasted_notes.csv": _csv(
            ["note_id", "entry_id", "entry_day", "entry_text", "kind", "title", "body", "created_at"],
            ([a.id, a.entry_id, *text_of.get(a.entry_id, ("", "")), a.kind, a.title, a.body, a.created_at]
             for a in atts)),
        "wins.csv": _csv(
            ["win_id", "day", "what_i_did", "why_it_mattered", "size", "theme", "entry_id", "entry_text", "created_at"],
            ([w.id, w.day, w.title, w.impact, w.size, w.theme, w.entry_id or "",
              text_of.get(w.entry_id, ("", ""))[1], w.created_at] for w in wins)),
        "guide_links.csv": _csv(
            ["guide_kind", "grade", "guide_item", "linked_to", "linked_id", "linked_text", "linked_at"],
            ([g.kind, g.grade or "", g.name, "win" if l.win_id else "entry", l.win_id or l.entry_id,
              title_of.get(l.win_id, "") if l.win_id else text_of.get(l.entry_id, ("", ""))[1], l.created_at]
             for l, g in links)),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()
