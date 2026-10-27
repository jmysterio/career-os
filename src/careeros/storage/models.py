"""Core tables: sources, observations, activities, correlation, claims."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ConnectorInstance(Base):
    __tablename__ = "connector_instance"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String)
    namespace: Mapped[str] = mapped_column(String)
    is_fixture: Mapped[bool] = mapped_column(default=True)
    checkpoint: Mapped[str | None] = mapped_column(String, nullable=True)


class ImportBatch(Base):
    __tablename__ = "import_batch"
    export_id: Mapped[str] = mapped_column(String, primary_key=True)
    connector_instance_id: Mapped[str] = mapped_column(ForeignKey("connector_instance.id"))
    export_mode: Mapped[str] = mapped_column(String)
    complete: Mapped[bool]
    cursor_before: Mapped[str | None] = mapped_column(String, nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(String, nullable=True)
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String)  # committed | out_of_order
    committed_at: Mapped[datetime] = mapped_column(DateTime)


class ContentBlob(Base):
    __tablename__ = "content_blob"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String, unique=True)
    minimized_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SourceRecord(Base):
    __tablename__ = "source_record"
    __table_args__ = (UniqueConstraint("connector_instance_id", "native_record_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    connector_instance_id: Mapped[str] = mapped_column(ForeignKey("connector_instance.id"))
    native_record_id: Mapped[str] = mapped_column(String)
    current_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SourceObservation(Base):
    __tablename__ = "source_observation"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"))
    content_blob_id: Mapped[int | None] = mapped_column(ForeignKey("content_blob.id"), nullable=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batch.export_id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    state: Mapped[str] = mapped_column(String)  # present | deleted | inaccessible
    adapter_version: Mapped[str] = mapped_column(String)
    policy_version: Mapped[str] = mapped_column(String)


class AuditEvent(Base):
    """Non-content audit trail: who/what/when and entity ids only."""
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    action: Mapped[str] = mapped_column(String)
    entity_ref: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class Identity(Base):
    __tablename__ = "identity"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # email | name
    value: Mapped[str] = mapped_column(String)
    is_self: Mapped[bool] = mapped_column(default=False)


class Activity(Base):
    """Projection of a source record's current observation."""
    __tablename__ = "activity"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_record.id"), unique=True)
    derived_from_observation_id: Mapped[int] = mapped_column(ForeignKey("source_observation.id"))
    type: Mapped[str] = mapped_column(String)  # release_row | merge_commit | commit | manual_note
    state: Mapped[str] = mapped_column(String, default="present")  # present | deleted
    occurred_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_tz: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    keys: Mapped[list] = mapped_column(JSON, default=list)


class Participation(Base):
    __tablename__ = "participation"
    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"))
    identity_id: Mapped[int] = mapped_column(ForeignKey("identity.id"))
    role: Mapped[str] = mapped_column(String)
    assertion_source: Mapped[str] = mapped_column(String)
    verification_status: Mapped[str] = mapped_column(String, default="asserted")


class EpisodeMember(Base):
    """Episodes are anchored on an activity (a release row) and reconstructible."""
    __tablename__ = "episode_member"
    __table_args__ = (UniqueConstraint("anchor_activity_id", "activity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    anchor_activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"))
    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"))
    origin: Mapped[str] = mapped_column(String)  # explicit | ambiguous | manual
    status: Mapped[str] = mapped_column(String)  # linked | suggested
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String, default="")


class CorrelationConstraint(Base):
    """Durable user decisions, independent of episode membership."""
    __tablename__ = "correlation_constraint"
    __table_args__ = (UniqueConstraint("left_entity", "right_entity", "relation"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    left_entity: Mapped[str] = mapped_column(String)   # "activity:<id>"
    right_entity: Mapped[str] = mapped_column(String)
    relation: Mapped[str] = mapped_column(String)      # must_link | cannot_link
    reason: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str] = mapped_column(String, default="user")


class Claim(Base):
    __tablename__ = "claim"
    id: Mapped[int] = mapped_column(primary_key=True)
    anchor_activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"))
    subject: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    object: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)  # planned | in_progress | completed | cancelled
    contribution_role: Mapped[str | None] = mapped_column(String, nullable=True)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    metric_scope: Mapped[str | None] = mapped_column(String, nullable=True)
    layer: Mapped[str] = mapped_column(String)  # observation | attribution | interpretation
    authored_by: Mapped[str] = mapped_column(String, default="template")  # template | user
    verification_status: Mapped[str] = mapped_column(String, default="unverified")
    # unverified | rule_checked | human_approved | rejected


class ClaimSupport(Base):
    __tablename__ = "claim_support"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"))
    observation_id: Mapped[int] = mapped_column(ForeignKey("source_observation.id"))
    field_pointer: Mapped[str] = mapped_column(String)
    excerpt_start: Mapped[int] = mapped_column(Integer)
    excerpt_end: Mapped[int] = mapped_column(Integer)
    polarity: Mapped[str] = mapped_column(String, default="supports")  # supports | contradicts


class AccomplishmentVersion(Base):
    __tablename__ = "accomplishment_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    anchor_activity_id: Mapped[int | None] = mapped_column(ForeignKey("activity.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    claim_ids: Mapped[list] = mapped_column(JSON)
    rendered_text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String)  # active | superseded | withdrawn
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class ExportRecord(Base):
    __tablename__ = "export_record"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String)
    observation_ids: Mapped[list] = mapped_column(JSON)


class PurgeMarker(Base):
    """Content-free marker that a purge happened."""
    __tablename__ = "purge_marker"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_ref: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    purged_at: Mapped[datetime] = mapped_column(DateTime)


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
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user checked it on the Sheet


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
