"""Year-end Markdown of the user's wins, shaped for a promotion case or resume update."""
from __future__ import annotations

from datetime import date

from ..storage.models import Win

ORDER = {"large": 0, "medium": 1, "small": 2}


def _when(w: Win) -> str:
    d = date.fromisoformat(w.day)
    return d.strftime("%b ") + str(d.day)


def _line(w: Win, *, theme: bool) -> str:
    tail = [w.size] + ([w.theme] if theme and w.theme else [])
    line = f"- **{w.title}** ({_when(w)}, {', '.join(tail)})"
    return line + (f"\n  - Why it mattered: {w.impact}" if w.impact else "\n  - Why it mattered: *not written yet*")


def wins_markdown(wins: list[Win], year: int, today: date | None = None) -> str:
    wins = sorted(wins, key=lambda w: (ORDER.get(w.size, 3), w.day))
    counts = {s: sum(1 for w in wins if w.size == s) for s in ORDER}
    missing = sum(1 for w in wins if not w.impact)
    out = [f"# My wins, {year}", "",
           f"{len(wins)} wins: {counts['large']} large, {counts['medium']} medium, {counts['small']} small. "
           f"Exported {(today or date.today()).isoformat()}."]
    if missing:
        out.append(f"{missing} still need a line on why they mattered.")
    big = [w for w in wins if w.size == "large"]
    if big:
        out += ["", "## Highlights", ""] + [_line(w, theme=True) for w in big]
    themes = sorted({w.theme for w in wins if w.theme}) + ([""] if any(not w.theme for w in wins) else [])
    if themes:
        out += ["", "## By theme"]
    for t in themes:
        out += ["", f"### {t or 'No theme yet'}", ""] + [_line(w, theme=False) for w in wins if w.theme == t]
    return "\n".join(out) + "\n"
