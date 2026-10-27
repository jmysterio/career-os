"""Reads a leveling guide CSV export (rows are attributes, columns are grades) into flat items."""
from __future__ import annotations

import csv
import re
from pathlib import Path

SKILL_GROUPS = {"transferable skills": "Transferable", "group-specific skills": "Group-specific",
                "group specific skills": "Group-specific", "path-specific skills": "Path-specific",
                "path specific skills": "Path-specific"}


class GuideFormatError(ValueError):
    pass


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u200b", "")).strip()


def parse_guide(path: Path | str) -> list[dict]:
    """Items: {key, kind: summary|experience|skill, grade, category, name, description, targets}."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = [r + [""] * (12 - len(r)) for r in csv.reader(fh)]
    grade_row = next((r for r in rows if r[1].strip().lower() == "grade"), None)
    if grade_row is None:
        raise GuideFormatError("Couldn't find the 'Grade' row; is this a leveling guide export?")
    grades = {i: int(m.group(1)) for i, c in enumerate(grade_row) if (m := re.fullmatch(r"\s*Grade\s+(\d+)\s*", c))}
    items: list[dict] = []
    group = ""
    for r in rows:
        label = r[1].strip().lower()
        if r[0].strip().lower() in SKILL_GROUPS:
            group = SKILL_GROUPS[r[0].strip().lower()]
        if label == "role summary":
            items += [dict(key=f"summary:{g}", kind="summary", grade=g, category="", name=_clean(r[i]),
                           description="", targets={}) for i, g in grades.items() if r[i].strip()]
        elif label == "key experiences":
            for i, g in grades.items():
                for line in re.split(r"\n\s*-\s*|^\s*-\s*", r[i]):
                    if (text := _clean(line)):
                        items.append(dict(key=f"exp:{g}:{slug(text)}", kind="experience", grade=g, category="",
                                          name=text, description="", targets={}))
        elif group and r[1].strip():
            targets = {str(g): int(r[i]) for i, g in grades.items() if r[i].strip().isdigit()}
            if targets:
                name = _clean(r[1]).lstrip("*").strip()
                items.append(dict(key=f"skill:{slug(name)}", kind="skill", grade=None, category=group,
                                  name=name, description=_clean(r[2]), targets=targets))
    if not any(i["kind"] == "experience" for i in items):
        raise GuideFormatError("Couldn't find any key experiences in that file.")
    return items
