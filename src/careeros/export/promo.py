"""Promotion case draft in Markdown: each leveling-guide item with the user's own wins and entries behind it."""
from __future__ import annotations

from datetime import date


def _when(day: str) -> str:
    d = date.fromisoformat(day)
    return d.strftime("%b ") + str(d.day) + d.strftime(", %Y")


def _evidence(x: dict) -> list[str]:
    out = []
    for w in x["wins"]:
        out.append(f"  - **{w.title}** ({_when(w.day)}, {w.size} win)"
                   + (f": {w.impact}" if w.impact else ". *Why it mattered isn't written yet.*"))
    out += [f"  - {e.text} ({_when(e.day)}, notebook entry)" for e in x["entries"]]
    return out


def promo_markdown(pm: dict, today: date | None = None) -> str:
    grades = pm["grades"]
    out = [f"# Promotion case draft: Grade {pm['current']} to Grade {grades[0]}"
           + (f", with Grade {grades[-1]} evidence" if len(grades) > 1 else ""), "",
           f"Drafted from my work notebook on {(today or date.today()).isoformat()}. "
           "Every line below is something I logged and linked to the leveling guide myself."]
    for gr in grades:
        p = pm["progress"][gr]
        out.append(f"- Grade {gr}: {p['shown'] + p['strong']} of {p['total']} key experiences shown "
                   f"({p['strong']} strong), {p['started']} started, {p['gap']} not yet.")
    for gr in grades:
        out += ["", f"## Grade {gr} key experiences"]
        if pm["summaries"].get(gr):
            out += ["", f"> {pm['summaries'][gr]}"]
        for row in pm["rows"]:
            xs = [x for x in row["cells"][gr] if x["wins"] or x["entries"]]
            if xs:
                out += ["", f"### {row['topic'].name}"]
                for x in xs:
                    out += ["", f"- {x['item'].name} *({x['status_label']})*", *_evidence(x)]
    skills = [x for x in pm["rising"] + pm["steady"] if x["wins"] or x["entries"]]
    if skills:
        out += ["", "## Skills"]
        for x in skills:
            targets = ", ".join(f"Grade {gr} asks for {x[f'g{gr}']}" for gr in grades if x[f"g{gr}"])
            out += ["", f"- {x['item'].name} ({targets})", *_evidence(x)]
    gaps = [(gr, x) for gr in grades for row in pm["rows"] for x in row["cells"][gr] if x["status"] == "gap"]
    if gaps:
        out += ["", "## Not shown yet", "", "Work to aim for before the case is submitted:", ""]
        out += [f"- Grade {gr}: {x['item'].name}" for gr, x in gaps]
    return "\n".join(out) + "\n"
