"""Pull meetings through the Google Workspace connector by running Claude Code headless.

Claude is allowed exactly one tool (calendar get_events) and never sees anything but the request. The
app then reads the tool's raw answer itself and keeps only title, times, and Google file links, so no
AI-written text ever reaches the notebook. Meeting titles, times, and attendee details do pass through
the AI tool on the way, which is why this is a button you press, not something that runs by itself.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from ..claude_cli import ClaudeError, call_tool, connector_error
from .calendar import CalendarError

TOOL = "mcp__plugin_google-workspace_google-workspace__get_events"
TIMEOUT_SECONDS = 240
MAX_DAYS = 14


def parse_events_text(text: str, me: str | None = None) -> list[dict]:
    """Turn the connector's text listing into plain items, dropping meetings you declined.

    `me` is your address; when None it is taken from the "for you@x.com:" line the connector prints.
    """
    if me is None:
        who = re.search(r"from calendar '[^']*' for (\S+?):", text)
        me = who.group(1) if who else None
    items: list[dict] = []
    for block in re.split(r'\n(?=- ")', text)[1:]:
        head = re.match(r'- "(.*)" \(Starts: (\S+), Ends: (\S+)\)', block)
        eid = re.search(r"^  ID: (\S+)", block, re.M)
        if not head or not eid or "T" not in head.group(2):  # all-day items have a bare date
            continue
        if me and re.search(rf"(?<![\w.@-]){re.escape(me)}: declined", block):
            continue
        links: list[dict] = []
        title = None
        for line in block.splitlines():
            if line.startswith("  Attachments: "):
                title = line[len("  Attachments: "):].strip()
            elif title and (url := re.match(r"\s+File URL: (\S+)", line)) and title != "None":
                links.append({"title": title, "url": url.group(1)})
        items.append({"id": eid.group(1), "title": head.group(1), "start": head.group(2),
                      "end": head.group(3), "links": links})
    return items


def fetch(first: date, last: date) -> list[dict]:
    """Meetings from `first` through the end of `last`, via a headless Claude Code run."""
    if (last - first).days > MAX_DAYS:
        raise CalendarError(f"Pick a window of {MAX_DAYS} days or fewer.")
    tz = datetime.now().astimezone().tzinfo
    t0 = datetime.combine(first, time.min, tzinfo=tz).isoformat()
    t1 = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz).isoformat()
    prompt = (f"Call the get_events tool exactly once with calendar_id=primary, time_min={t0}, time_max={t1}, "
              "max_results=250, detailed=true, include_attachments=true. When it returns, reply with only DONE.")
    try:
        answer = call_tool(prompt, TOOL, TIMEOUT_SECONDS)
    except ClaudeError as exc:
        raise CalendarError(str(exc)) from None
    if err := connector_error(answer, "Google"):  # a failure reply would otherwise look like an empty calendar
        raise CalendarError(err)
    return parse_events_text(answer)
