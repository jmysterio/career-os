"""Envelope importer. Enforces plan §2/§3 invariants.

Absence is never deletion unless explicit (tombstone) or a complete snapshot
whose scope is the whole connector. Checkpoints advance in the same
transaction that commits the batch.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import (
    AuditEvent, ConnectorInstance, ContentBlob, ImportBatch, SourceObservation,
    SourceRecord,
)
from .envelope import MAX_RECORDS, Envelope

ADAPTER_VERSION = "0"
POLICY_VERSION = "0"


class ImportRejected(Exception):
    """Whole envelope refused; nothing was written."""


@dataclass(frozen=True)
class Approval:
    connector_instance_id: str
    allowed_fields: frozenset[str]
    expires_at: datetime


@dataclass
class ImportResult:
    status: str  # committed | duplicate | held_out_of_order
    new_observations: int = 0
    deleted: int = 0
    skipped_stale: int = 0
    messages: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(fields: dict) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def import_envelope(
    session: Session, env: Envelope, approvals: dict[str, Approval], now: datetime | None = None
) -> ImportResult:
    now = now or _now()
    ap = approvals.get(env.connector_instance_id)
    if ap is None or ap.expires_at <= now:
        raise ImportRejected("no approved, unexpired Gate 0 record for connector instance")
    if len(env.records) > MAX_RECORDS:
        raise ImportRejected("too many records")
    # Defense in depth: reject (never silently strip) non-allowlisted fields.
    for rec in env.records:
        extra = set(rec.fields) - ap.allowed_fields
        if extra:
            raise ImportRejected(f"non-allowlisted fields: {sorted(extra)}")

    if session.get(ImportBatch, env.export_id) is not None:
        return ImportResult("duplicate")

    ci = session.get(ConnectorInstance, env.connector_instance_id)
    if ci is None:
        raise ImportRejected("unknown connector instance")
    if env.cursor_before != ci.checkpoint:
        session.add(AuditEvent(at=now, action="import_held_out_of_order",
                               entity_ref=f"export:{env.export_id}"))
        session.commit()
        return ImportResult("held_out_of_order")

    res = ImportResult("committed")
    try:
        session.add(ImportBatch(
            export_id=env.export_id, connector_instance_id=ci.id, export_mode=env.export_mode,
            complete=env.complete, cursor_before=env.cursor_before, cursor_after=env.cursor_after,
            coverage_start=env.coverage_start, coverage_end=env.coverage_end,
            status="committed", committed_at=now))
        session.flush()
        seen: set[str] = set()
        for rec in env.records:
            seen.add(rec.native_record_id)
            sr = _source_record(session, ci.id, rec.native_record_id)
            cur = _current(session, sr)
            if (cur and cur.source_updated_at and rec.source_updated_at
                    and rec.source_updated_at < cur.source_updated_at):
                res.skipped_stale += 1
                continue
            h = _hash(rec.fields)
            blob = session.scalar(select(ContentBlob).where(ContentBlob.content_hash == h))
            if blob is None:
                blob = ContentBlob(content_hash=h, minimized_payload=rec.fields)
                session.add(blob)
                session.flush()
            # Compare against the *current* observation only, so A->B->A
            # is recorded as three observations.
            if cur and cur.state == "present" and cur.content_blob_id == blob.id:
                continue
            _observe(session, sr, blob.id, env, rec.source_updated_at, "present", now)
            res.new_observations += 1

        tomb_ids = {t.native_record_id for t in env.explicit_tombstones}
        if env.export_mode == "snapshot" and env.complete and env.scope.get("kind") == "all":
            existing = session.scalars(
                select(SourceRecord.native_record_id).where(SourceRecord.connector_instance_id == ci.id)
            ).all()
            tomb_ids |= set(existing) - seen
        for nid in tomb_ids:
            sr = _source_record(session, ci.id, nid, create=False)
            cur = _current(session, sr) if sr else None
            if sr and cur and cur.state != "deleted":
                _observe(session, sr, None, env, None, "deleted", now)
                res.deleted += 1

        ci.checkpoint = env.cursor_after  # same transaction as the batch
        session.add(AuditEvent(at=now, action="import_committed", entity_ref=f"export:{env.export_id}"))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return res


def _source_record(session: Session, ci_id: str, nid: str, create: bool = True) -> SourceRecord | None:
    sr = session.scalar(select(SourceRecord).where(
        SourceRecord.connector_instance_id == ci_id, SourceRecord.native_record_id == nid))
    if sr is None and create:
        sr = SourceRecord(connector_instance_id=ci_id, native_record_id=nid)
        session.add(sr)
        session.flush()
    return sr


def _current(session: Session, sr: SourceRecord) -> SourceObservation | None:
    return session.get(SourceObservation, sr.current_observation_id) if sr.current_observation_id else None


def _observe(session, sr, blob_id, env, updated, state, now) -> None:
    obs = SourceObservation(
        source_record_id=sr.id, content_blob_id=blob_id, import_batch_id=env.export_id,
        observed_at=env.collection_completed_at, source_updated_at=updated, state=state,
        adapter_version=ADAPTER_VERSION, policy_version=POLICY_VERSION)
    session.add(obs)
    session.flush()
    sr.current_observation_id = obs.id
