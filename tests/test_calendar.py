from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from careeros.config import DataDir
from careeros.google import calendar as gcal
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import JournalAttachment, JournalEntry

D = date.today() - timedelta(days=1)
STAMP = D.strftime("%Y%m%d")


def ics(*events: str) -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//\r\n" + "".join(events) + "END:VCALENDAR\r\n").encode()


def ev(uid, summary, start="T150000Z", end="T153000Z", extra=""):
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20200101T000000Z\r\nDTSTART:{STAMP}{start}\r\n"
            f"DTEND:{STAMP}{end}\r\nSUMMARY:{summary}\r\n{extra}END:VEVENT\r\n")


@pytest.fixture
def s(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as session:
        yield session


def pull(s, *events):
    first, last = D - timedelta(days=3), date.today()
    return gcal.sync(s, gcal.parse_events(ics(*events), first, last), first, last)


def test_sync_adds_updates_and_dedupes(s):
    assert pull(s, ev("a1", "Rollout sync"))["added"] == 1
    assert pull(s, ev("a1", "Rollout sync")) == dict(added=0, updated=0, removed=0)
    assert pull(s, ev("a1", "Rollout sync v2"))["updated"] == 1
    row = s.scalars(select(JournalEntry)).one()
    assert row.source == "calendar" and row.kind == "meeting" and "Rollout sync v2" in row.text


def test_only_title_and_time_are_kept(s):
    pull(s, ev("a1", "Plan", extra="DESCRIPTION:secret agenda\r\nLOCATION:Room 9\r\nATTENDEE:mailto:sam@example.com\r\n"))
    row = s.scalars(select(JournalEntry)).one()
    blob = f"{row.text} {row.external_id}"
    assert "secret" not in blob and "Room" not in blob and "sam@" not in blob


def test_cancelled_and_all_day_skipped(s):
    allday = (f"BEGIN:VEVENT\r\nUID:h\r\nDTSTAMP:20200101T000000Z\r\nDTSTART;VALUE=DATE:{STAMP}\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\n")
    assert pull(s, ev("c", "Nope", extra="STATUS:CANCELLED\r\n"), allday)["added"] == 0


def test_vanished_event_removed_unless_it_has_notes(s):
    pull(s, ev("a1", "Keep me"), ev("a2", "Drop me"))
    keep = s.scalar(select(JournalEntry).where(JournalEntry.text.contains("Keep me")))
    s.add(JournalAttachment(entry_id=keep.id, kind="notes", body="my notes", created_at=datetime.now()))
    s.commit()
    assert pull(s)["removed"] == 1
    assert [e.text for e in s.scalars(select(JournalEntry))] == [keep.text]


def test_typed_entries_never_touched(s):
    s.add(JournalEntry(day=D.isoformat(), kind="meeting", text="typed by me", created_at=datetime.now()))
    s.commit()
    pull(s)
    assert s.scalars(select(JournalEntry)).one().text == "typed by me"


def test_url_stored_owner_only_and_validated(tmp_path):
    dd = DataDir(tmp_path)
    with pytest.raises(gcal.CalendarError):
        gcal.save_url(dd, "http://insecure")
    gcal.save_url(dd, "https://calendar.google.com/x/private-abc/basic.ics")
    assert oct(gcal.url_file(dd).stat().st_mode & 0o777) == "0o600"


def test_bad_file_is_a_clear_error():
    with pytest.raises(gcal.CalendarError):
        gcal.parse_events(b"<html>nope</html>", D, date.today())


def test_old_notebook_gets_new_columns(tmp_path):
    engine = make_engine(tmp_path / "old.db")
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE journal_entry (id INTEGER PRIMARY KEY, day VARCHAR, kind VARCHAR, "
                          "text VARCHAR, created_at DATETIME)")
        c.exec_driver_sql("INSERT INTO journal_entry VALUES (1,'2026-01-01','note','old','2026-01-01 00:00:00')")
    init_db(engine)
    with make_session_factory(engine)() as session:
        assert session.scalars(select(JournalEntry)).one().source == ""


CONNECTOR_TEXT = """Successfully retrieved 3 events from calendar 'primary' for me@x.com:
- "Planning" (Starts: 2026-10-23T10:30:00-04:00, Ends: 2026-10-23T11:00:00-04:00)
  Description: secret agenda
  Attendees: me@x.com, you@x.com
  Attendee Details: me@x.com: accepted
    you@x.com: accepted
  Attachments: Notes by Gemini
    File URL: https://docs.google.com/document/d/abc/edit
    File ID: abc
    MIME Type: application/vnd.google-apps.document
  ID: ev1_20261023T143000Z | Link: https://www.google.com/calendar/event?eid=zzz
- "Skipped" (Starts: 2026-10-23T12:00:00-04:00, Ends: 2026-10-23T12:30:00-04:00)
  Attendee Details: me@x.com: declined
  Attachments: None
  ID: ev2 | Link: x
- "Holiday" (Starts: 2026-10-23, Ends: 2026-10-24)
  Attachments: None
  ID: ev3 | Link: x
"""


def test_connector_text_keeps_title_times_links_only_and_drops_declined_and_all_day():
    from careeros.google import connector
    items = connector.parse_events_text(CONNECTOR_TEXT)
    assert items == [dict(id="ev1_20261023T143000Z", title="Planning", start="2026-10-23T10:30:00-04:00",
                          end="2026-10-23T11:00:00-04:00",
                          links=[dict(title="Notes by Gemini", url="https://docs.google.com/document/d/abc/edit")])]


def test_import_events_dedupes_links_and_removes_vanished(s):
    from careeros.google import connector
    items = connector.parse_events_text(CONNECTOR_TEXT)
    first, last = date(2026, 10, 22), date(2026, 10, 23)
    r = gcal.import_events(s, items, first, last)
    assert (r["added"], r["links"]) == (1, 1)
    assert gcal.import_events(s, items, first, last) == dict(added=0, updated=0, removed=0, links=0)
    assert [a.body for a in s.scalars(select(JournalAttachment))] == ["https://docs.google.com/document/d/abc/edit"]
    assert gcal.import_events(s, [], first, last)["removed"] == 0  # has a link attached, so it is kept
