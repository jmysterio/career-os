"""Drafting, review, approval, and accomplishment versioning (plan §5)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ingest.envelope import Envelope
from ..ingest.importer import Approval, import_envelope
from ..storage.models import (
    AccomplishmentVersion, Activity, AuditEvent, Claim, ClaimSupport, ConnectorInstance,
    ContentBlob, EpisodeMember, Participation, SourceObservation, SourceRecord,
)
from . import rules


class ClaimBlocked(Exception):
    def __init__(self, violations: list[str]):
        super().__init__("; ".join(violations))
        self.violations = violations


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(s: Session, action: str, ref: str) -> None:
    s.add(AuditEvent(at=_now(), action=action, entity_ref=ref))  # ids only, never content


# ---- evidence resolution -------------------------------------------------

def payload(s: Session, observation_id: int) -> dict:
    obs = s.get(SourceObservation, observation_id)
    if obs is None or obs.content_blob_id is None:
        return {}
    return s.get(ContentBlob, obs.content_blob_id).minimized_payload or {}


def excerpt_text(s: Session, sup: ClaimSupport) -> str:
    return str(payload(s, sup.observation_id).get(sup.field_pointer, ""))[sup.excerpt_start:sup.excerpt_end]


def provenance_ref(sup: ClaimSupport) -> str:
    return f"cos://obs/{sup.observation_id}#{sup.field_pointer}[{sup.excerpt_start}:{sup.excerpt_end}]"


def _add_support(s: Session, claim: Claim, obs_id: int, field_name: str,
                 needle: str | None = None, polarity: str = "supports") -> None:
    text = str(payload(s, obs_id).get(field_name, ""))
    start = text.find(needle) if needle else 0
    if start < 0:
        raise ValueError("needle not found in field")
    end = start + len(needle) if needle else len(text)
    s.add(ClaimSupport(claim_id=claim.id, observation_id=obs_id, field_pointer=field_name,
                       excerpt_start=start, excerpt_end=end, polarity=polarity))


def claim_view(s: Session, claim: Claim) -> rules.ClaimView:
    supports = []
    for sup in s.scalars(select(ClaimSupport).where(ClaimSupport.claim_id == claim.id)):
        obs = s.get(SourceObservation, sup.observation_id)
        sr = s.get(SourceRecord, obs.source_record_id)
        act = s.scalar(select(Activity).where(Activity.source_record_id == sr.id))
        roles = {p.role for p in s.scalars(select(Participation).where(
            Participation.activity_id == act.id))} if act else set()
        in_ep = (act is None or act.id == claim.anchor_activity_id or act.type == "manual_note"
                 or s.scalar(select(EpisodeMember).where(
                     EpisodeMember.anchor_activity_id == claim.anchor_activity_id,
                     EpisodeMember.activity_id == act.id, EpisodeMember.status == "linked")) is not None)
        supports.append(rules.SupportView(
            in_episode=in_ep, observation_id=obs.id, excerpt=excerpt_text(s, sup), record_id=sr.native_record_id,
            polarity=sup.polarity, is_current=(sr.current_observation_id == obs.id and obs.state == "present"),
            self_roles=roles))
    return rules.ClaimView(layer=claim.layer, subject=claim.subject, status=claim.status,
                           contribution_role=claim.contribution_role, metric_value=claim.metric_value,
                           metric_unit=claim.metric_unit, metric_scope=claim.metric_scope,
                           authored_by=claim.authored_by, supports=supports)


def violations(s: Session, claim: Claim) -> list[str]:
    return rules.check(claim_view(s, claim))


def render_claim(c: Claim) -> str:
    text = f"{c.subject[:1].upper() + c.subject[1:]} {c.action} {c.object}"
    return text if c.status == "completed" else f"{text} [{c.status}]"


# ---- drafting -------------------------------------------------------------

def _row_payload(s: Session, anchor: Activity) -> tuple[int, dict]:
    return anchor.derived_from_observation_id, payload(s, anchor.derived_from_observation_id)


def _same_key_fresh_approved(s: Session, anchor_id: int, key: tuple) -> bool:
    for c in s.scalars(select(Claim).where(Claim.anchor_activity_id == anchor_id,
                                           Claim.verification_status == "human_approved")):
        if (c.subject, c.action, c.object, c.layer) == key and not violations(s, c):
            return True
    return False


def draft_episode(s: Session, anchor_id: int) -> list[str]:
    """Template drafter: structured claims from evidence fields only. Returns unknowns."""
    anchor = s.get(Activity, anchor_id)
    obs_id, f = _row_payload(s, anchor)
    rid = f["release_id"]
    pinned = {cid for v in s.scalars(select(AccomplishmentVersion).where(
        AccomplishmentVersion.anchor_activity_id == anchor_id)) for cid in v.claim_ids}
    old = [c.id for c in s.scalars(select(Claim).where(
        Claim.anchor_activity_id == anchor_id, Claim.authored_by == "template",
        Claim.verification_status != "human_approved")) if c.id not in pinned]
    if old:
        s.execute(delete(ClaimSupport).where(ClaimSupport.claim_id.in_(old)))
        s.execute(delete(Claim).where(Claim.id.in_(old)))

    def make(key_fields: dict, supports: list[tuple]) -> None:
        key = (key_fields["subject"], key_fields["action"], key_fields["object"], key_fields["layer"])
        if _same_key_fresh_approved(s, anchor_id, key):
            return
        c = Claim(anchor_activity_id=anchor_id, **key_fields)
        s.add(c)
        s.flush()
        for sup in supports:
            _add_support(s, c, *sup)
        s.flush()
        c.verification_status = "unverified" if violations(s, c) else "rule_checked"

    status_map = {"deployed": "completed", "planned": "planned"}
    row_status = f.get("status", "")
    make(dict(subject=f"release {rid}", action="has status", object=row_status, layer="observation",
              status=status_map.get(row_status.lower(), "in_progress")), [(obs_id, "status")])

    notes = f.get("notes", "")
    m = re.search(r"(?i)\b(team)\s+deployed\s+(\d+)\s+(\w+)", notes)
    if m:
        make(dict(subject=m.group(1).lower(), action="deployed", object=f"{m.group(2)} {m.group(3)}",
                  layer="observation", status="completed", metric_value=float(m.group(2)),
                  metric_unit=m.group(3), metric_scope=rid), [(obs_id, "notes", m.group(0))])
    t = re.search(r"(?i)target:\s*(\d+)%\s*([^.]*)", notes)
    if t:
        make(dict(subject=f"release {rid}", action="targeted", object=f"{t.group(1)}% {t.group(2).strip()}",
                  layer="observation", status="planned", metric_value=float(t.group(1)),
                  metric_unit="%", metric_scope=rid), [(obs_id, "notes", t.group(0))])

    for mem in s.scalars(select(EpisodeMember).where(EpisodeMember.anchor_activity_id == anchor_id)):
        act = s.get(Activity, mem.activity_id)
        if mem.status != "linked" or act.type != "merge_commit":
            continue
        cf = payload(s, act.derived_from_observation_id)
        sha, keys = cf["sha"], ", ".join(act.keys)
        make(dict(subject=f"commit {sha}", action="landed on", object=f"{cf.get('branch', 'main')} ({keys})",
                  layer="observation", status="completed"), [(act.derived_from_observation_id, "subject")])
        if s.scalar(select(Participation).where(Participation.activity_id == act.id,
                                                Participation.role == "author")):
            make(dict(subject="I", action="authored", object=f"merge {sha} ({keys})", layer="attribution",
                      status="completed", contribution_role="author"),
                 [(act.derived_from_observation_id, "subject")])

    s.commit()
    return unknowns_for(s, anchor_id)


def unknowns_for(s: Session, anchor_id: int) -> list[str]:
    """Open questions for the user; never filled in by inference."""
    anchor = s.get(Activity, anchor_id)
    status = payload(s, anchor.derived_from_observation_id).get("status", "")
    out: list[str] = []
    for mem in s.scalars(select(EpisodeMember).where(EpisodeMember.anchor_activity_id == anchor_id)):
        if mem.status != "linked":
            act = s.get(Activity, mem.activity_id)
            out.append(f"Unconfirmed link: '{act.title}' ({mem.reason}) - link or ignore it.")
    if not s.scalar(select(Claim).where(Claim.anchor_activity_id == anchor_id,
                                        Claim.layer == "interpretation",
                                        Claim.verification_status != "rejected")):
        out.append("Impact / why it mattered is unknown - add it yourself; it is not inferred.")
    if status.lower() != "deployed":
        out.append(f"Release status is '{status}', not deployed.")
    return out


# ---- review actions -------------------------------------------------------

def approve(s: Session, claim_id: int, *, batch: bool = False) -> None:
    c = s.get(Claim, claim_id)
    if batch and c.layer != "observation":
        raise ClaimBlocked(["batch approval is only allowed for observation claims"])
    v = violations(s, c)
    if v:
        raise ClaimBlocked(v)
    c.verification_status = "human_approved"
    _audit(s, "claim_approved", f"claim:{c.id}")
    s.commit()


def reject(s: Session, claim_id: int) -> None:
    s.get(Claim, claim_id).verification_status = "rejected"
    _audit(s, "claim_rejected", f"claim:{claim_id}")
    s.commit()


def edit_claim(s: Session, claim_id: int, *, object: str) -> None:
    """Editing resets verification: an edited claim must be re-checked and re-approved."""
    c = s.get(Claim, claim_id)
    c.object = object
    c.verification_status = "unverified" if violations(s, c) else "rule_checked"
    _audit(s, "claim_edited", f"claim:{c.id}")
    s.commit()


def add_manual_note(s: Session, text: str, now: datetime | None = None) -> int:
    """User-provided evidence enters through the same observation path."""
    from ..correlate.project import project_activities
    now = now or _now()
    ci = s.get(ConnectorInstance, "manual")
    nid = f"note-{uuid.uuid4().hex[:12]}"
    env = Envelope.model_validate({
        "schema_version": 1, "connector_instance_id": "manual", "export_id": uuid.uuid4().hex,
        "export_mode": "delta", "scope": {"kind": "rows"}, "collection_started_at": now,
        "collection_completed_at": now, "complete": True, "cursor_before": ci.checkpoint,
        "cursor_after": uuid.uuid4().hex,
        "records": [{"native_record_id": nid, "fields": {"text": text, "created_at": now.isoformat()},
                     "source_updated_at": now}]})
    import_envelope(s, env, {"manual": Approval("manual", frozenset({"text", "created_at"}),
                                                now.replace(year=now.year + 10))}, now=now)
    project_activities(s)
    sr = s.scalar(select(SourceRecord).where(SourceRecord.native_record_id == nid))
    return sr.current_observation_id


def add_impact_claim(s: Session, anchor_id: int, text: str) -> int:
    """User-authored interpretation, supported by the user's own note."""
    obs_id = add_manual_note(s, text)
    c = Claim(anchor_activity_id=anchor_id, subject="release", action="mattered because", object=text,
              layer="interpretation", status="completed", authored_by="user")
    s.add(c)
    s.flush()
    _add_support(s, c, obs_id, "text")
    c.verification_status = "unverified" if violations(s, c) else "rule_checked"
    _audit(s, "impact_added", f"claim:{c.id}")
    s.commit()
    return c.id


# ---- accomplishment versions ---------------------------------------------

def publish(s: Session, anchor_id: int, claim_ids: list[int]) -> AccomplishmentVersion:
    claims = [s.get(Claim, i) for i in claim_ids]
    bad = [c.id for c in claims if c.verification_status != "human_approved" or violations(s, c)]
    if bad or not claims:
        raise ClaimBlocked([f"claims not approved or failing checks: {bad}"])
    prev = s.scalars(select(AccomplishmentVersion).where(
        AccomplishmentVersion.anchor_activity_id == anchor_id)).all()
    for p in prev:
        if p.state == "active":
            p.state = "superseded"
    v = AccomplishmentVersion(anchor_activity_id=anchor_id, version=len(prev) + 1, claim_ids=claim_ids,
                              rendered_text="\n".join(render_claim(c) for c in claims), state="active")
    s.add(v)
    _audit(s, "accomplishment_published", f"anchor:{anchor_id}")
    s.commit()
    return v


def withdraw(s: Session, version_id: int, reason: str) -> None:
    v = s.get(AccomplishmentVersion, version_id)
    v.state, v.reason = "withdrawn", reason
    _audit(s, "accomplishment_withdrawn", f"version:{v.id}")
    s.commit()


def stale_versions(s: Session) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for v in s.scalars(select(AccomplishmentVersion).where(AccomplishmentVersion.state == "active")):
        reasons = [x for cid in v.claim_ids for x in violations(s, s.get(Claim, cid)) if x.startswith("stale")]
        if reasons:
            out[v.id] = reasons
    return out
