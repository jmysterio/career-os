"""Content purge (plan §6). Leaves only a content-free marker and audit event."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..storage.models import (
    AccomplishmentVersion, Activity, AuditEvent, Claim, ClaimSupport, ConnectorInstance,
    ContentBlob, EpisodeMember, ExportRecord, Participation, PurgeMarker, SourceObservation,
    SourceRecord,
)


@dataclass
class PurgeReport:
    observations: int = 0
    claims: int = 0
    versions_withdrawn: int = 0
    files_deleted: list[str] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)


def _obs_for_connectors(s: Session, connector_ids: set[str]) -> set[int]:
    return set(s.scalars(select(SourceObservation.id).join(
        SourceRecord, SourceObservation.source_record_id == SourceRecord.id).where(
        SourceRecord.connector_instance_id.in_(connector_ids))))


def purge_source(s: Session, connector_id: str, *, inbox: Path, export_dir: Path, reason: str,
                 now: datetime | None = None) -> PurgeReport:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    engine = s.get_bind()
    s.connection().exec_driver_sql("PRAGMA secure_delete=ON")
    rep = PurgeReport()
    connectors = {connector_id}
    obs_ids = _obs_for_connectors(s, connectors)

    # Claims touching purged evidence, or anchored on purged activities, hold derived content.
    anchors = set(s.scalars(select(Activity.id).join(SourceRecord).where(
        SourceRecord.connector_instance_id == connector_id)))
    claim_ids = set(s.scalars(select(ClaimSupport.claim_id).where(ClaimSupport.observation_id.in_(obs_ids))))
    claim_ids |= set(s.scalars(select(Claim.id).where(Claim.anchor_activity_id.in_(anchors))))
    # The user's own manual notes cited only by purged claims go too (they echo purged context).
    manual_obs = {o for o in s.scalars(select(ClaimSupport.observation_id).where(
        ClaimSupport.claim_id.in_(claim_ids))) if o not in obs_ids and
        s.get(SourceRecord, s.get(SourceObservation, o).source_record_id).connector_instance_id == "manual"}
    if manual_obs and connector_id != "manual":
        obs_ids |= manual_obs
        connectors.add("manual")

    for v in s.scalars(select(AccomplishmentVersion)):
        if set(v.claim_ids) & claim_ids or v.anchor_activity_id in anchors:
            v.rendered_text, v.state, v.reason = "[withdrawn: content purged]", "withdrawn", "content purged"
            rep.versions_withdrawn += 1

    s.execute(delete(ClaimSupport).where(ClaimSupport.claim_id.in_(claim_ids)))
    s.execute(delete(ClaimSupport).where(ClaimSupport.observation_id.in_(obs_ids)))
    s.execute(delete(Claim).where(Claim.id.in_(claim_ids)))
    rep.claims = len(claim_ids)

    rec_ids = set(s.scalars(select(SourceObservation.source_record_id).where(SourceObservation.id.in_(obs_ids))))
    act_ids = set(s.scalars(select(Activity.id).where(Activity.source_record_id.in_(rec_ids))))
    for v in s.scalars(select(AccomplishmentVersion).where(AccomplishmentVersion.anchor_activity_id.in_(act_ids))):
        v.anchor_activity_id = None  # keep the withdrawn marker, drop the pointer to purged content
    s.flush()
    s.execute(delete(EpisodeMember).where(EpisodeMember.anchor_activity_id.in_(act_ids) |
                                          EpisodeMember.activity_id.in_(act_ids)))
    s.execute(delete(Participation).where(Participation.activity_id.in_(act_ids)))
    s.execute(delete(Activity).where(Activity.id.in_(act_ids)))
    blob_ids = set(s.scalars(select(SourceObservation.content_blob_id).where(
        SourceObservation.id.in_(obs_ids)))) - {None}
    s.execute(delete(SourceObservation).where(SourceObservation.id.in_(obs_ids)))
    s.execute(delete(SourceRecord).where(SourceRecord.id.in_(rec_ids)))
    still_used = set(s.scalars(select(SourceObservation.content_blob_id))) - {None}
    s.execute(delete(ContentBlob).where(ContentBlob.id.in_(blob_ids - still_used)))
    rep.observations = len(obs_ids)

    for er in s.scalars(select(ExportRecord)):
        if set(er.observation_ids) & obs_ids:
            Path(er.path).unlink(missing_ok=True)
            rep.files_deleted.append(er.path)
            s.delete(er)
    for d in ("incoming", "ready", "processed"):
        for p in (inbox / d).glob("*"):
            try:
                cid = json.loads(p.read_text()).get("connector_instance_id")
            except (OSError, ValueError):
                rep.manual_actions.append(f"unreadable file needs manual review: {p}")
                continue
            if cid in connectors:
                p.unlink()
                rep.files_deleted.append(str(p))

    s.add(PurgeMarker(entity_ref=f"connector:{connector_id}", reason=reason, purged_at=now))
    s.add(AuditEvent(at=now, action="purged", entity_ref=f"connector:{connector_id}"))
    s.commit()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        c.exec_driver_sql("VACUUM")
    rep.manual_actions.append("Backups, synced folders, logs outside the managed dirs, and exports "
                              "outside the export dir must be purged manually per Gate 0 policy.")
    return rep
