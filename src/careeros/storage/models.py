"""Tables: notebook entries and what hangs off them, wins, the leveling guide, and sync bookkeeping."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JournalEntry(Base):
    """The user's own day-to-day notes (meetings, conversations, documents). Not evidence, no approvals."""
    __tablename__ = "journal_entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    kind: Mapped[str] = mapped_column(String)  # meeting | conversation | document | note
    text: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String, default="")  # "" = typed by the user | calendar
    external_id: Mapped[str | None] = mapped_column(String, index=True, default=None)
    status: Mapped[str] = mapped_column(String, default="")  # tasks only: open | done
    kind_was: Mapped[str] = mapped_column(String, default="")  # the kind before Claude changed it, else ""
    ai_read: Mapped[bool] = mapped_column(Boolean, default=False)  # Claude has read it against the guide
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user checked it in the Intake Review Queue
    work_item_id: Mapped[int | None] = mapped_column(ForeignKey("work_item.id"), nullable=True, default=None)
    grouped: Mapped[bool] = mapped_column(Boolean, default=False)  # Claude has decided which work item it belongs to
    work_fixed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user grouped or split it; Claude leaves it
    activity: Mapped[str] = mapped_column(String, default="")  # one key from guide/activities.py, or "" for none
    activity_read: Mapped[bool] = mapped_column(Boolean, default=False)  # Claude has tagged it
    activity_fixed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user set it; Claude leaves it


class WorkItem(Base):
    """One piece of work (a release, a refresh, a runbook) that several records can describe. Counted once."""
    __tablename__ = "work_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD of its latest record
    started: Mapped[str] = mapped_column(String, default="")  # YYYY-MM-DD of its first record
    by_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RemovedEntry(Base):
    """A journal entry the user removed. Syncs skip its external id so it doesn't come back; Restore re-adds it."""
    __tablename__ = "removed_entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="")
    external_id: Mapped[str | None] = mapped_column(String, index=True, default=None)
    status: Mapped[str] = mapped_column(String, default="")
    removed_at: Mapped[datetime] = mapped_column(DateTime)


class SyncRun(Base):
    """One pull from a source (Slack tracker, Google Calendar, Google Tasks), even when nothing new came in."""
    __tablename__ = "sync_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    added: Mapped[int] = mapped_column(Integer, default=0)


class SkipRule(Base):
    """Calendar events whose title contains this text (any case) are never brought into the notebook."""
    __tablename__ = "skip_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, default="calendar")
    pattern: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class JournalAttachment(Base):
    """Something pasted under a journal entry: a link, meeting notes, a transcript, a canvas, a prompt."""
    __tablename__ = "journal_attachment"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # link | notes | transcript | canvas | prompt | other
    title: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Win(Base):
    """An accomplishment the user chose to keep for reviews, promotion cases, and resumes. Written by the user."""
    __tablename__ = "win"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    title: Mapped[str] = mapped_column(String)  # what I did
    impact: Mapped[str] = mapped_column(Text, default="")  # why it mattered, in the user's words
    size: Mapped[str] = mapped_column(String, default="small")  # small | medium | large
    theme: Mapped[str] = mapped_column(String, default="")
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)  # drafted by Claude, not yet edited or confirmed


class PromoVersion(Base):
    """One drafted promotion case. It keeps the numbered evidence it was written from, so its sources still make
    sense after the notebook changes."""
    __tablename__ = "promo_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    window_start: Mapped[str] = mapped_column(String)
    window_end: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    voice: Mapped[str] = mapped_column(String, default="third")
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{n, kind, text, day, refs}]
    slices: Mapped[dict] = mapped_column(JSON, default=dict)  # section key -> evidence numbers it was written from
    note: Mapped[str] = mapped_column(String, default="")  # how this draft came about, e.g. "Edited Impact"
    google_doc_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)


class PromoSection(Base):
    """One heading of a draft. `sentences` is [{text, sources: [n], valid, reason}]."""
    __tablename__ = "promo_section"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("promo_version.id"), index=True)
    key: Mapped[str] = mapped_column(String)
    heading: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer, default=0)
    sentences: Mapped[list] = mapped_column(JSON, default=list)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(String, default="")


class GuideItem(Base):
    """One line of the leveling guide: a grade's role summary, a key experience, or a rated skill."""
    __tablename__ = "guide_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)  # stable across re-imports, e.g. exp:6:<slug>
    kind: Mapped[str] = mapped_column(String)  # summary | experience | skill
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None for skills
    category: Mapped[str] = mapped_column(String, default="")
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    targets: Mapped[dict] = mapped_column(JSON, default=dict)  # skills: {"6": 3, "7": 4}
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(default=True)  # False once a re-import no longer has it


class GuideLink(Base):
    """The user's statement that a win or a notebook entry shows a guide item."""
    __tablename__ = "guide_link"
    __table_args__ = (UniqueConstraint("item_id", "win_id", "entry_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("guide_item.id"), index=True)
    win_id: Mapped[int | None] = mapped_column(ForeignKey("win.id"), nullable=True, index=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)  # picked by Claude, not yet confirmed
