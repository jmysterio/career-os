"""Turns Slack canvases into plain work items.

Two layouts are understood: the Slackbot "Slack Work Activity Tracker" (dated sections of templated work
items) and the "Weekly Contributions for Promotion Case" canvases (titled sections, each with a channel
date, a summary, the quoted Slack message, and a link). Both are AI-written by Slackbot.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime

TRACKER = "Slack tracker"
PROMO = "promo canvas"
UNKNOWN = {"", "unknown", "unknown / not determined", "not determined", "[no link available]"}


@dataclass(frozen=True)
class SlackItem:
    key: str      # stable id: the Slack message path when there is a link
    day: str      # YYYY-MM-DD
    text: str     # headline for the notebook entry
    body: str     # the canvas's description, as written
    impact: str
    link: str | None
    origin: str   # TRACKER | PROMO


class CanvasFormatError(ValueError):
    pass


def canvas_markdown(raw: str) -> str:
    """Accepts canvas markdown, or the JSON a canvas read returns ({"markdown_content": ...})."""
    s = raw.strip()
    if s.startswith("{"):
        try:
            data = json.loads(s)
        except ValueError:
            raise CanvasFormatError("That file looks like JSON but couldn't be read.") from None
        if not isinstance(data, dict) or not isinstance(data.get("markdown_content"), str):
            raise CanvasFormatError("That JSON has no canvas text (markdown_content).")
        return data["markdown_content"]
    return raw


def _day(text: str) -> str | None:
    if (m := re.search(r"slack_date:(\d{4}-\d{2}-\d{2})", text)) or (m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)):
        return m.group(1)
    if m := re.search(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b", text):
        try:
            return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            return None
    return None


def _url(text: str) -> str | None:
    m = re.search(r"\((https://[^)\s]+)\)", text) or re.search(r"(https://\S+)", text)
    return m.group(1).rstrip(".,") if m else None


def _key(origin: str, link: str | None, *parts: str) -> str:
    if link and (m := re.search(r"/archives/(\w+)/p(\d+)", link)):
        return f"slack:{m.group(1)}/p{m.group(2)}"
    return "slack:" + hashlib.sha1("\n".join((origin, link or "", *parts)).encode()).hexdigest()[:20]


def _plain(s: str) -> str:
    s = re.sub(r"\*\*|__", "", s)
    s = re.sub(r"^[^\w(\"'<]+", "", s.strip())  # leading emoji or bullets
    return " ".join(s.split())


def parse_tracker(md: str) -> list[SlackItem]:
    items: list[SlackItem] = []
    for sec in re.split(r"^## ", md, flags=re.M)[1:]:
        head, _, rest = sec.partition("\n")
        day = _day(head)
        if not day:
            continue
        work = re.split(r"^\*\*(?:Decisions|Follow-Ups|Workflows Used|Tools Used)\*\*", rest, flags=re.M)[0]
        for block in re.split(r"^\* (?=\*\*)", work, flags=re.M)[1:]:
            first, _, sub = block.partition("\n")
            m = re.match(r"\*\*(.+?)\s+[—–-]\s+(.+?)\*\*", first)
            if not m:
                continue
            category, topic = _plain(m.group(1)), _plain(m.group(2))
            fields: dict[str, str] = {}
            for line in sub.splitlines():
                if f := re.match(r"\s+\* ([A-Za-z /]+?):\s*(.*)$", line):
                    fields[f.group(1).strip().lower()] = f.group(2).strip()
            link = _url(fields.get("link", ""))
            impact = fields.get("impact / why it mattered", "")
            lines = [f"Action: {fields['action']}" if fields.get("action") else "",
                     f"Outcome: {fields['outcome']}" if fields.get("outcome") else "",
                     f"Why it mattered: {impact}" if impact else "",
                     *(f"{label}: {fields[k]}" for k, label in (("workflow", "Workflow"), ("tools", "Tools"))
                       if fields.get(k, "").lower() not in UNKNOWN),
                     f"Tracker category: {category}"]
            items.append(SlackItem(_key(TRACKER, link, day, category, topic), day, f"{category}: {topic}"[:500],
                                   "\n".join(x for x in lines if x), impact, link, TRACKER))
    return items


def parse_promo(md: str, fallback_day: str | None = None) -> list[SlackItem]:
    """Only the dated contribution sections; the summary, focus, and full-year sections are skipped."""
    fallback = fallback_day or _day((re.findall(r"\*\*Canvas Created:\*\*([^\n*]+)", md) or [""])[0]) \
        or date.today().isoformat()
    items: list[SlackItem] = []
    for sec in re.split(r"^## ", md, flags=re.M)[1:]:
        head, _, rest = sec.partition("\n")
        if not re.search(r"contributions|week of", head, re.I):
            continue
        for sub in re.split(r"^### ", rest, flags=re.M)[1:]:
            title_line, _, body = sub.partition("\n")
            title = _plain(title_line)
            day = None
            for chunk in re.split(r"(?=^\*\*Channel:\*\*|^\*\*Summary:\*\*)", body, flags=re.M):
                if chunk.startswith("**Channel:**"):
                    day = _day(chunk.splitlines()[0]) or day
                    continue
                if not chunk.startswith("**Summary:**"):
                    continue
                summary = chunk.split("\n", 1)[0].replace("**Summary:**", "").strip()
                link_line = next((l for l in chunk.splitlines() if l.startswith("**Link:**")), "")
                link = _url(link_line)
                impact = next((l.replace("**Impact:**", "").strip() for l in chunk.splitlines()
                               if l.startswith("**Impact:**")), "")
                quote = "\n".join(l[1:].strip() for l in chunk.splitlines() if l.startswith(">"))
                body_text = "\n".join(x for x in (
                    f"Summary: {summary}", f"Why it mattered: {impact}" if impact else "",
                    f"What I wrote in Slack:\n{quote}" if quote else "") if x)
                d = day or fallback
                items.append(SlackItem(_key(PROMO, link, d, title, summary), d, title[:500], body_text, impact,
                                       link, PROMO))
    return items


def parse_canvas(raw: str, fallback_day: str | None = None) -> list[SlackItem]:
    md = canvas_markdown(raw)
    if "**Primary Work**" in md or "slack_date:" in md:
        items = parse_tracker(md)
    elif "**Summary:**" in md:
        items = parse_promo(md, fallback_day)
    else:
        raise CanvasFormatError("This canvas isn't a Slack Work Activity Tracker or a contributions canvas.")
    seen: set[str] = set()
    return [i for i in items if not (i.key in seen or seen.add(i.key))]
