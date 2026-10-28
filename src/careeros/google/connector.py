"""Pull meetings through the Google Workspace connector by running Claude Code headless.

Claude is allowed exactly one tool (calendar get_events) and never sees anything but the request. The
app then reads the tool's raw answer itself and keeps only title, times, and Google file links, so no
AI-written text ever reaches the notebook. Meeting titles, times, and attendee details do pass through
the AI tool on the way, which is why this is a button you press, not something that runs by itself.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, datetime, time, timedelta
from pathlib import Path

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


def _tool_result_text(content: object) -> str:
    """The tool's answer, whether it came back inline or was saved to a file because it was large."""
    from ..claude_cli import ClaudeError, _result_text
    try:
        return _result_text(content)
    except ClaudeError as exc:
        raise CalendarError(str(exc)) from None


def fetch(first: date, last: date) -> list[dict]:
    """Meetings from `first` through the end of `last`, via a headless Claude Code run."""
    if (last - first).days > MAX_DAYS:
        raise CalendarError(f"Pick a window of {MAX_DAYS} days or fewer.")
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if not Path(claude).exists():
        raise CalendarError("Couldn't find the `claude` command on this computer.")
    tz = datetime.now().astimezone().tzinfo
    t0 = datetime.combine(first, time.min, tzinfo=tz).isoformat()
    t1 = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz).isoformat()
    prompt = (f"Call the get_events tool exactly once with calendar_id=primary, time_min={t0}, time_max={t1}, "
              "max_results=250, detailed=true, include_attachments=true. When it returns, reply with only DONE.")
    try:
        run = subprocess.run(
            [claude, "-p", prompt, "--allowedTools", TOOL, "--output-format", "stream-json", "--verbose",
             "--max-turns", "5"],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, cwd=Path.home())
    except subprocess.TimeoutExpired:
        raise CalendarError("Claude took too long to answer. Try again.") from None
    answer: str | None = None
    wanted: set[str] = set()
    for line in run.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        for part in (msg.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and part.get("name") == TOOL:
                wanted.add(part["id"])
            elif part.get("type") == "tool_result" and part.get("tool_use_id") in wanted:
                answer = _tool_result_text(part.get("content", ""))
    if answer is None:
        raise CalendarError("Claude didn't return any calendar data. Is Google Workspace connected in Claude Code?"
                            + (f" ({run.stderr.strip()[:150]})" if run.stderr.strip() else ""))
    if answer.startswith("Error"):
        raise CalendarError(f"The calendar tool said: {answer[:200]}")
    return parse_events_text(answer)
