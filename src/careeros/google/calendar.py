"""Read-only Google Calendar pull through the calendar's private iCal address.

Only the title and the start/end time of each event are kept. Attendees, descriptions, locations,
and meeting links are dropped here, before anything reaches the database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
import icalendar
import recurring_ical_events
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DataDir
from ..storage.models import JournalAttachment, JournalEntry

SOURCE = "calendar"
MAX_ICS_BYTES = 20_000_000


class CalendarError(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    uid: str
    day: str
    start: datetime
    end: datetime | None
    title: str


def url_file(dd: DataDir):
    return dd.root / "calendar.url"


def save_url(dd: DataDir, url: str) -> None:
    url = url.strip()
    if not url.startswith("https://"):
        raise CalendarError("That doesn't look like a calendar address (it should start with https://).")
    fd = os.open(url_file(dd), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(url + "\n")
    os.chmod(url_file(dd), 0o600)


def load_url(dd: DataDir) -> str:
    f = url_file(dd)
    if not f.exists():
        raise CalendarError("No calendar connected yet. Run: uv run careeros calendar connect")
    return f.read_text().strip()


def fetch_ics(url: str) -> bytes:
    try:
        with httpx.stream("GET", url, timeout=30, follow_redirects=False) as r:
            if r.status_code != 200:
                raise CalendarError(f"Google answered {r.status_code}. The secret address may have been reset; "
                                    "run `careeros calendar connect` with the new one.")
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_ICS_BYTES:
                    raise CalendarError("The calendar file is unexpectedly large; stopping.")
            return body
    except httpx.HTTPError as exc:
        raise CalendarError(f"Couldn't reach Google ({type(exc).__name__}).") from None


def parse_events(ics: bytes, first: date, last: date) -> list[Event]:
    """Timed, non-cancelled events whose local start day falls in [first, last]."""
    try:
        cal = icalendar.Calendar.from_ical(ics)
    except ValueError:
        raise CalendarError("That address didn't return a calendar file.") from None
    local = datetime.now().astimezone().tzinfo
    start = datetime.combine(first, datetime.min.time(), tzinfo=local)
    stop = datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=local)
    out: dict[str, Event] = {}
    for ev in recurring_ical_events.of(cal).between(start, stop):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dts = ev.get("DTSTART").dt
        if not isinstance(dts, datetime):  # all-day (holidays, out-of-office banners)
            continue
        if dts.tzinfo is None:
            dts = dts.replace(tzinfo=local)
        dts = dts.astimezone(local)
        if not first <= dts.date() <= last:
            continue
        dte = ev.get("DTEND").dt if ev.get("DTEND") else None
        dte = dte.astimezone(local) if isinstance(dte, datetime) and dte.tzinfo else None
        title = " ".join(str(ev.get("SUMMARY", "")).split())[:200] or "(no title)"
        uid = f"{ev.get('UID')}@{dts.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        out[uid] = Event(uid, dts.date().isoformat(), dts, dte, title)
    return sorted(out.values(), key=lambda e: e.start)


def _clock(d: datetime) -> str:
    return d.strftime("%I:%M %p").lstrip("0")


def headline(e: Event) -> str:
    span = _clock(e.start) + (f"–{_clock(e.end)}" if e.end else "")
    return f"{span}  {e.title}"[:500]


def sync(s: Session, events: list[Event], first: date, last: date) -> dict[str, int]:
    """Add new events, refresh changed ones, drop ones that vanished (unless you attached notes)."""
    existing = {e.external_id: e for e in s.scalars(select(JournalEntry).where(
        JournalEntry.source == SOURCE, JournalEntry.day >= first.isoformat(), JournalEntry.day <= last.isoformat()))}
    added = updated = removed = 0
    for ev in events:
        row = existing.pop(ev.uid, None)
        if row is None:
            s.add(JournalEntry(day=ev.day, kind="meeting", text=headline(ev), created_at=datetime.now(),
                               source=SOURCE, external_id=ev.uid))
            added += 1
        elif row.text != headline(ev) or row.day != ev.day:
            row.text, row.day = headline(ev), ev.day
            updated += 1
    from ..guide.service import keeps_entry
    for gone in existing.values():
        has_notes = s.scalar(select(JournalAttachment.id).where(JournalAttachment.entry_id == gone.id).limit(1))
        if not has_notes and not keeps_entry(s, gone):
            s.delete(gone)
            removed += 1
    s.commit()
    return dict(added=added, updated=updated, removed=removed)


def events_from_items(items: list[dict], local=None) -> tuple[list[Event], dict[str, list[tuple[str, str]]]]:
    """Plain event data (id, title, start, end, links) handed over by a connector run, not read from iCal.

    Only the title, the times, and Google file links are kept; anything else in an item is ignored.
    """
    local = local or datetime.now().astimezone().tzinfo
    events: dict[str, Event] = {}
    links: dict[str, list[tuple[str, str]]] = {}
    for it in items:
        try:
            uid, start = str(it["id"]), datetime.fromisoformat(str(it["start"])).astimezone(local)
            end = datetime.fromisoformat(str(it["end"])).astimezone(local) if it.get("end") else None
        except (KeyError, ValueError):
            raise CalendarError(f"Couldn't read this calendar item: {str(it)[:120]}") from None
        title = " ".join(str(it.get("title", "")).split())[:200] or "(no title)"
        events[uid] = Event(uid, start.date().isoformat(), start, end, title)
        links[uid] = [(" ".join(str(link.get("title", "")).split())[:200], str(link["url"]))
                      for link in it.get("links", []) if str(link.get("url", "")).startswith("https://")]
    return sorted(events.values(), key=lambda e: e.start), links


def import_events(s: Session, items: list[dict], first: date, last: date) -> dict[str, int]:
    """Like sync(), for connector data; also attaches each meeting's file links (notes, recordings) once."""
    events, links = events_from_items(items)
    counts = sync(s, events, first, last)
    rows = {e.external_id: e for e in s.scalars(select(JournalEntry).where(
        JournalEntry.source == SOURCE, JournalEntry.external_id.in_(list(links))))}
    linked = 0
    for uid, pairs in links.items():
        row = rows.get(uid)
        if row is None:
            continue
        have = set(s.scalars(select(JournalAttachment.body).where(
            JournalAttachment.entry_id == row.id, JournalAttachment.kind == "link")))
        for title, url in pairs:
            if url not in have:
                s.add(JournalAttachment(entry_id=row.id, kind="link", title=title, body=url, created_at=datetime.now()))
                have.add(url)
                linked += 1
    s.commit()
    return dict(counts, links=linked)
